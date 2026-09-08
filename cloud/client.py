"""Google login and revision-safe cloud drawings for the Windows desktop app.

Bundled into workflow_v50.py to retain the installed three-file update protocol.
No privileged server keys or Google client secrets are shipped to the desktop.
"""
import base64
import ctypes
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import webbrowser
import zipfile
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, filedialog

CLOUD_URL = 'https://fbjluujeorqhzihwmkii.supabase.co'
CLOUD_KEY = 'sb_publishable_hc5zIiTpjdTZLa9s_Oey8Q_qZH1cIko'
CLOUD_CALLBACK = 'http://127.0.0.1:43851/callback'
CLOUD_MAX_ZIP = 8 * 1024 * 1024
CLOUD_MAX_EXPANDED = 128 * 1024 * 1024
CLOUD_FILES = {'working.sqlite3', 'before.sqlite3', 'after.sqlite3'}


class CloudError(Exception):
    def __init__(self, message, code=''):
        super().__init__(message)
        self.code = code


class CloudNoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def cloud_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def cloud_json(path, data):
    cloud_atomic(path, json.dumps(data, ensure_ascii=False).encode('utf-8'))


def cloud_http(path, body=None, token=None):
    if not path.startswith('/') or path.startswith('//'):
        raise ValueError('Invalid API path')
    headers = {'apikey': CLOUD_KEY, 'Accept': 'application/json', 'User-Agent': 'Telecom-Core-Desktop'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(CLOUD_URL + path, data=data, headers=headers)
    try:
        with urllib.request.build_opener(CloudNoRedirect()).open(req, timeout=25) as response:
            content = response.read(13 * 1024 * 1024 + 1)
            if len(content) > 13 * 1024 * 1024:
                raise CloudError('서버 응답이 허용 크기를 초과했습니다.')
            return json.loads(content) if content else None
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read(4096))
        except (ValueError, OSError):
            detail = {}
        code = str(detail.get('code') or e.code)
        message = str(detail.get('message') or detail.get('msg') or detail.get('error_description') or '서버 요청 실패')
        friendly = {'DRAWING_CONFLICT': '다른 PC에서 수정된 도면입니다.',
                    'APPROVAL_REQUIRED': '관리자 승인이 필요하거나 사용이 차단됐습니다.',
                    'GOOGLE_LOGIN_REQUIRED': 'Google 계정으로 다시 로그인해 주세요.',
                    'ADMIN_REQUIRED': '관리자 권한이 필요합니다.'}
        raise CloudError(friendly.get(message, message[:250]), code) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise CloudError('서버에 연결할 수 없습니다. PC의 작업 내용은 보존됩니다.', 'network') from None


def cloud_protect(data, decrypt=False):
    if os.name != 'nt':
        raise CloudError('로그인 정보 저장은 Windows에서 지원됩니다.')
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = Blob(len(data), buffer)
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    function = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise CloudError('Windows 로그인 정보 보호에 실패했습니다.')
    try:
        return ctypes.string_at(output.data, output.length)
    finally:
        kernel.LocalFree(output.data)


class CloudSession:
    def __init__(self, tokens, cache=None):
        self.tokens = dict(tokens)
        self.tokens.setdefault('expires_at', time.time() + int(tokens.get('expires_in', 3600)))
        self.cache = Path(cache) if cache else None
        self.profile = None
        self.lock = threading.RLock()

    def remember(self):
        if self.cache:
            try:
                cloud_atomic(self.cache, cloud_protect(json.dumps(self.tokens).encode()))
            except (CloudError, OSError):
                self.cache = None

    def refresh(self):
        tokens = cloud_http('/auth/v1/token?grant_type=refresh_token',
                            {'refresh_token': self.tokens['refresh_token']})
        self.tokens = dict(tokens, expires_at=time.time() + int(tokens.get('expires_in', 3600)))
        self.remember()

    def call(self, action, **values):
        with self.lock:
            if self.tokens['expires_at'] < time.time() + 60:
                self.refresh()
            result = cloud_http('/rest/v1/rpc/telecom_call',
                                {'request': dict(values, action=action)}, self.tokens['access_token'])
            if action == 'profile':
                self.profile = result
            return result


class CloudJobs:
    """All HTTP stays off Tk's thread; completions are applied by the Tk event loop."""
    def __init__(self, root):
        self.root = root
        self.busy = False
        self.closed = False
        self.results = queue.Queue()
        self.poll_id = self.root.after(100, self.poll)

    def stop(self):
        self.closed = True
        try:
            self.root.after_cancel(self.poll_id)
        except tk.TclError:
            pass

    def run(self, function, done, failed):
        if self.busy or self.closed:
            return False
        self.busy = True
        def work():
            try:
                result, error = function(), None
            except Exception as e:
                result, error = None, e
            self.results.put((done, failed, result, error))
        threading.Thread(target=work, daemon=True).start()
        return True

    def poll(self):
        if self.closed:
            return
        try:
            done, failed, result, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            if error:
                failed(error)
            else:
                try:
                    done(result)
                except Exception as callback_error:
                    failed(callback_error)
        if not self.closed:
            self.poll_id = self.root.after(100, self.poll)


def cloud_google_login(cancel):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    codes = queue.Queue()
    class Callback(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path != '/callback' or self.headers.get('Host') != '127.0.0.1:43851':
                self.send_error(404)
                return
            params = urllib.parse.parse_qs(parsed.query)
            if 'code' not in params and 'error' not in params:
                self.send_error(400)
                return
            codes.put(params)
            body = '<!doctype html><meta charset="utf-8"><title>통신 코어 도면</title><p>로그인 응답을 받았습니다. 통신 코어 도면 프로그램으로 돌아가 주세요.</p>'.encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(body)
    try:
        server = http.server.HTTPServer(('127.0.0.1', 43851), Callback)
    except OSError:
        raise CloudError('로그인 포트가 사용 중입니다. 다른 통신 코어 프로그램을 닫고 다시 시도하세요.') from None
    try:
        server.timeout = 0.5
        url = CLOUD_URL + '/auth/v1/authorize?' + urllib.parse.urlencode({
            'provider': 'google', 'redirect_to': CLOUD_CALLBACK, 'code_challenge': challenge,
            'code_challenge_method': 's256', 'prompt': 'select_account'})
        if not webbrowser.open(url):
            raise CloudError('브라우저를 열지 못했습니다. 기본 브라우저 설정을 확인하세요.')
        deadline = time.monotonic() + 180
        while codes.empty() and not cancel.is_set() and time.monotonic() < deadline:
            server.handle_request()
        if codes.empty():
            raise CloudError('로그인이 취소됐거나 시간이 지났습니다. 다시 시도해 주세요.')
        params = codes.get()
        if params.get('error'):
            raise CloudError('Google 로그인이 완료되지 않았습니다. 계정과 로그인 설정을 확인해 주세요.')
        return cloud_http('/auth/v1/token?grant_type=pkce',
                          {'auth_code': params['code'][0], 'code_verifier': verifier})
    finally:
        server.server_close()


class CloudLogin(tk.Tk):
    def __init__(self, namespace, home):
        super().__init__()
        self.title('통신 코어 도면 · Google 로그인')
        self.geometry('590x380')
        self.minsize(530,340)
        self.configure(bg='#172033')
        self.session = None
        self.candidate = None
        self.home = Path(home)
        self.cache = self.home / 'cloud_login.bin'
        self.cancel = threading.Event()
        self.jobs = CloudJobs(self)
        self.protocol('WM_DELETE_WINDOW', self.close)
        tk.Label(self, text='통신 코어 도면', bg='#172033', fg='white',
                 font=('Malgun Gothic',20,'bold')).pack(pady=(30,8))
        tk.Label(self, text='Google 계정으로 로그인하고 내 도면을 이어서 작업하세요.',
                 bg='#172033', fg='#d7e1ef', font=('Malgun Gothic',10)).pack(pady=6)
        self.info = tk.StringVar(value='처음 로그인한 사용자는 관리자 승인이 필요합니다.')
        tk.Label(self, textvariable=self.info, bg='#172033', fg='#ffe08a',
                 wraplength=500, font=('Malgun Gothic',10)).pack(pady=20)
        self.login_button = ttk.Button(self, text='Google 계정으로 로그인', command=self.login)
        self.login_button.pack(ipadx=25, ipady=8)
        self.check_button = ttk.Button(self, text='승인 상태 다시 확인', command=self.check)
        self.check_button.pack(pady=10)
        self.remember = tk.BooleanVar(value=True)
        ttk.Checkbutton(self, text='이 PC에서 로그인 유지', variable=self.remember).pack()
        self.resume_id = self.after(150,self.resume)

    def resume(self):
        if not self.cache.exists():
            return
        try:
            tokens = json.loads(cloud_protect(self.cache.read_bytes(), decrypt=True))
            self.candidate = CloudSession(tokens, self.cache)
        except Exception:
            self.info.set('저장된 로그인을 사용할 수 없습니다. Google 계정으로 로그인해 주세요.')
            return
        self.info.set('저장된 계정의 승인 상태를 확인하고 있습니다…')
        self.jobs.run(lambda:(self.candidate.refresh(),self.candidate.call('profile'))[1],self.checked,self.failed)

    def login(self):
        if self.jobs.busy:
            return
        self.cancel.clear()
        self.info.set('브라우저에서 Google 로그인을 완료해 주세요.')
        remember = self.remember.get()
        def work():
            session = CloudSession(cloud_google_login(self.cancel), self.cache if remember else None)
            session.call('profile')
            return session
        def done(session):
            if not remember:
                self.cache.unlink(missing_ok=True)
            self.candidate = session
            self.checked(session.profile)
        self.jobs.run(work,done,self.failed)

    def check(self):
        if self.candidate:
            self.jobs.run(lambda:self.candidate.call('profile'),self.checked,self.failed)

    def checked(self, profile):
        self.candidate.remember()
        if profile['status'] == 'approved':
            self.session = self.candidate
            self.jobs.stop()
            self.after_cancel(self.resume_id)
            self.destroy()
        else:
            state = '관리자 승인 대기 중입니다.' if profile['status']=='pending' else '사용이 차단된 계정입니다. 관리자에게 확인해 주세요.'
            self.info.set(profile['email']+'\n'+state)

    def failed(self, error):
        self.info.set(str(error))

    def close(self):
        self.cancel.set()
        self.jobs.stop()
        self.after_cancel(self.resume_id)
        self.destroy()


def cloud_sqlite_copy(source, destination):
    from contextlib import closing
    with closing(sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro',uri=True)) as src:
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
            dst.commit()


def cloud_bundle(store, scenario_folder):
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        store.backup_to(folder/'working.sqlite3')
        for name in ('before','after'):
            source = Path(scenario_folder)/(name+'.sqlite3')
            if source.exists():
                cloud_sqlite_copy(source,folder/source.name)
        output = io.BytesIO()
        with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(folder.iterdir()):
                item=zipfile.ZipInfo(path.name,(2026,1,1,0,0,0))
                item.compress_type=zipfile.ZIP_DEFLATED
                archive.writestr(item,path.read_bytes())
        data=output.getvalue()
        if len(data)>CLOUD_MAX_ZIP:
            raise CloudError('도면의 압축 크기가 8MB를 넘었습니다. 작업은 PC에 저장되며 동기화는 보류됩니다.')
        return data


def cloud_unpack(data):
    if len(data)>CLOUD_MAX_ZIP:
        raise CloudError('도면 파일이 허용 크기를 초과했습니다.')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos=archive.infolist()
        names=[i.filename for i in infos]
        if not names or 'working.sqlite3' not in names or len(names)!=len(set(names)) or not set(names)<=CLOUD_FILES:
            raise CloudError('도면 파일 구성이 올바르지 않습니다.')
        if sum(i.file_size for i in infos)>CLOUD_MAX_EXPANDED:
            raise CloudError('도면의 압축 해제 크기가 허용 범위를 넘었습니다.')
        contents={name:archive.read(name) for name in names}
    with tempfile.TemporaryDirectory() as temp:
        for name,content in contents.items():
            if not content.startswith(b'SQLite format 3\x00'):
                raise CloudError('올바른 SQLite 도면이 아닙니다.')
            path=Path(temp)/name
            path.write_bytes(content)
            conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
            try:
                if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                    raise CloudError('손상된 도면입니다. PC의 기존 작업을 유지합니다.')
                tables={r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
                if not {'nodes','cables','cores','splices'}<=tables:
                    raise CloudError('통신 코어 도면 파일이 아닙니다.')
            finally:
                conn.close()
    return contents


class CloudController:
    def __init__(self, app, session, namespace, root_home):
        self.app, self.session, self.ns = app, session, namespace
        self.root_home = Path(root_home)
        self.home = self.ns['app_dir']()
        self.index_path = self.home/'cloud_index.json'
        try:
            self.index = json.loads(self.index_path.read_bytes())
            if self.index.get('owner') != session.profile['user_id']:
                raise ValueError('Wrong account')
        except FileNotFoundError:
            self.index = {'owner':session.profile['user_id'],'docs':{},'current':None}
        self.current = None
        self.switching = False
        self.closing = False
        self.logout_requested = False
        self.access_lost = False
        self.retry_at = 0
        self.refresh_at = 0
        self.dialog = None
        self.jobs = CloudJobs(app)
        self.bar = tk.Frame(app,bg='#eaf0f8',padx=8,pady=5)
        self.bar.pack(fill='x',before=app.winfo_children()[0])
        role='관리자 · 사용자' if session.profile['role']=='admin' else '사용자'
        ttk.Label(self.bar,text=session.profile['email']+' · '+role).pack(side='left',padx=4)
        ttk.Button(self.bar,text='내 도면',command=self.projects).pack(side='left',padx=4)
        ttk.Button(self.bar,text='지금 동기화',command=self.sync_now).pack(side='left',padx=4)
        if session.profile['role']=='admin':
            ttk.Button(self.bar,text='사용자 승인 관리',command=self.admin).pack(side='left',padx=4)
        ttk.Button(self.bar,text='로그아웃',command=self.logout).pack(side='right',padx=4)
        self.status=tk.StringVar(value='내 도면을 불러오고 있습니다…')
        self.status_label=tk.Label(self.bar,textvariable=self.status,bg='#eaf0f8',fg='#155e42')
        self.status_label.pack(side='right',padx=10)
        self.projects_id = self.app.after(200,self.projects)
        self.tick_id = self.app.after(2000,self.tick)

    def persist(self):
        if self.index_path.exists():
            cloud_atomic(self.index_path.with_suffix('.previous.json'),self.index_path.read_bytes())
        cloud_json(self.index_path,self.index)

    def entry(self, drawing_id=None):
        return self.index['docs'][drawing_id or self.current]

    def working(self, entry):
        stem=entry['stem']
        if not re.fullmatch(r'[a-f0-9_]{32,70}',stem):
            raise CloudError('도면 저장 경로가 올바르지 않습니다.')
        folder=self.home/'data'/'cloud'
        folder.mkdir(parents=True,exist_ok=True)
        return folder/(stem+'.sqlite3')

    def outbox(self):
        folder=self.home/'cloud_outbox'
        folder.mkdir(parents=True,exist_ok=True)
        return folder

    def signature(self):
        if not self.current:
            return ''
        stats=[]
        for name in ('before','after'):
            p=self.app.scenario_path(name)
            stats.append([p.stat().st_mtime_ns,p.stat().st_size] if p.exists() else None)
        return json.dumps([self.app.store.data_revision(),stats,self.app.scenario_kind()])

    def editable_idle(self):
        return not (self.app.store.conn.hold_commit or self.app.store._history_depth or self.app.pending_drag)

    def capture(self):
        if not self.current:
            return
        if not self.editable_idle():
            raise CloudError('진행 중인 편집을 마친 뒤 동기화합니다.')
        path=self.outbox()/(self.current+'.json')
        if path.exists():
            return
        entry=self.entry()
        signature=self.signature()
        if entry.get('synced_signature')==signature:
            return
        data=cloud_bundle(self.app.store,self.app.scenario_folder())
        digest=hashlib.sha256(data).hexdigest()
        if entry.get('synced_sha')==digest and entry.get('synced_name')==entry['name']:
            entry['synced_signature']=signature
            self.persist()
            return
        request={'id':self.current,'name':entry['name'],'base_revision':entry.get('base_revision',0),
                 'operation_id':str(uuid.uuid4()),'sha256':digest,
                 'payload':base64.b64encode(data).decode(),'_signature':signature}
        cloud_json(path,request)
        self.status.set('PC 저장 완료 · 클라우드 동기화 대기')

    def send_next(self, done=None, failed=None):
        if self.jobs.busy:
            return False
        pending=sorted(self.outbox().glob('*.json'))
        if not pending:
            if done:
                done()
            return True
        path=pending[0]
        request=json.loads(path.read_bytes())
        drawing_id=str(uuid.UUID(request['id']))
        if path.stem!=drawing_id or drawing_id not in self.index['docs']:
            raise CloudError('계정의 동기화 대기 파일을 확인해 주세요.')
        self.status.set('클라우드에 저장하는 중…')
        def work():
            return self.session.call('save',**{k:v for k,v in request.items() if not k.startswith('_')})
        def succeeded(result):
            entry=self.entry(drawing_id)
            entry.update(base_revision=result['revision'],synced_sha=request['sha256'],
                         synced_name=request['name'],synced_signature=request['_signature'])
            self.persist()
            path.unlink(missing_ok=True)
            self.status.set('동기화 완료 · '+time.strftime('%H:%M:%S'))
            self.status_label.configure(fg='#155e42')
            self.send_next(done,failed)
        def failure(error):
            if isinstance(error,CloudError) and error.code=='40001':
                # Keep both revisions: local changes become a distinct cloud drawing.
                if '_conflict_id' not in request:
                    entry=dict(self.entry(drawing_id))
                    entry.update(name=(entry['name'][:75]+' · 충돌 보관 '+time.strftime('%m-%d %H-%M')),
                                 base_revision=0,synced_sha=None,synced_signature=None)
                    request.update(_conflict_id=str(uuid.uuid4()),_conflict_entry=entry,
                                   _conflict_operation_id=str(uuid.uuid4()))
                    # Persist the split decision before changing the index so a crash can resume it.
                    cloud_json(path,request)
                new_id=request['_conflict_id']
                entry=dict(request['_conflict_entry'])
                new_request={k:v for k,v in request.items() if not k.startswith('_conflict')}
                new_request.update(id=new_id,name=entry['name'],base_revision=0,
                                   operation_id=request['_conflict_operation_id'])
                self.index['docs'][new_id]=entry
                # Original cache is intentionally not reused for the server's newer original.
                self.index['docs'][drawing_id] = dict(self.entry(drawing_id),stem=uuid.uuid4().hex,
                                                     synced_signature=None)
                if self.current==drawing_id:
                    self.current=new_id
                    self.index['current']=new_id
                self.persist()
                cloud_json(self.outbox()/(new_id+'.json'),new_request)
                path.unlink(missing_ok=True)
                self.app.update_title()
                messagebox.showinfo('동시에 수정된 도면',
                    '다른 PC의 변경과 겹쳤습니다.\n이 PC의 작업은 “'+entry['name']+'”으로 따로 보관합니다.\n다른 PC의 원본도 내 도면 목록에 그대로 남습니다.',parent=self.app)
                self.send_next(done,failed)
                return
            self.failed(error)
            if failed:
                failed(error)
        return self.jobs.run(work,succeeded,failure)

    def failed(self,error):
        self.retry_at=time.monotonic()+20
        self.status.set('PC에 저장됨 · '+str(error))
        self.status_label.configure(fg='#a03c16')
        if isinstance(error,CloudError) and error.code in ('42501','401','PGRST301'):
            self.access_lost=True
            if self.dialog and self.dialog.winfo_exists():
                self.dialog.destroy()
            notice=tk.Toplevel(self.app)
            notice.title('계정 확인 필요')
            ttk.Label(notice,text='로그인 또는 관리자 승인을 다시 확인해야 합니다.\n현재 작업은 이 계정의 PC 저장 공간에 보존됩니다.',padding=20).pack()
            ttk.Button(notice,text='저장하고 종료',command=self.finish_close).pack(pady=15)
            notice.protocol('WM_DELETE_WINDOW',self.finish_close)
            notice.grab_set()

    def sync_now(self):
        if self.jobs.busy or self.access_lost:
            return
        try:
            self.capture()
            self.send_next(done=lambda:self.status.set('동기화 완료 · '+time.strftime('%H:%M:%S')))
        except Exception as error:
            self.failed(error)

    def tick(self):
        if self.closing:
            return
        try:
            if not self.access_lost and not self.jobs.busy and self.current and time.monotonic()>=self.retry_at:
                if self.editable_idle():
                    self.capture()
                if any(self.outbox().glob('*.json')):
                    self.send_next()
                elif time.monotonic()>=self.refresh_at and not self.has_dialogs():
                    self.refresh_at=time.monotonic()+20
                    self.poll_remote()
        except Exception as error:
            self.failed(error)
        if not self.closing:
            self.tick_id = self.app.after(2000,self.tick)

    def has_dialogs(self):
        return any(isinstance(w,tk.Toplevel) and w.winfo_exists() for w in self.app.winfo_children())

    def poll_remote(self):
        drawing_id=self.current
        signature=self.signature()
        def checked(rows):
            row=next((r for r in rows if r['id']==drawing_id),None)
            if not row or self.current!=drawing_id or self.signature()!=signature or self.has_dialogs():
                return
            if row['revision']>self.entry()['base_revision']:
                self.fetch_drawing(drawing_id,expected_signature=signature)
        self.jobs.run(lambda:self.session.call('list'),checked,self.failed)

    def ensure_saved(self, continuation):
        if self.jobs.busy:
            messagebox.showinfo('동기화 중','진행 중인 연결이 끝난 뒤 다시 눌러 주세요.',parent=self.app)
            return
        try:
            self.capture()
            self.send_next(done=continuation)
        except Exception as error:
            self.failed(error)

    def install(self, drawing, contents):
        drawing_id=str(uuid.UUID(drawing['id']))
        stem=uuid.UUID(drawing_id).hex+'_'+uuid.uuid4().hex
        entry={'name':drawing['name'],'stem':stem,'base_revision':drawing['revision'],
               'synced_sha':drawing['sha256'],'synced_name':drawing['name']}
        path=self.working(entry)
        folder=self.home/'scenarios'/stem
        folder.mkdir(parents=True,exist_ok=True)
        for name,data in contents.items():
            cloud_atomic(path if name=='working.sqlite3' else folder/name,data)
        # Change one small pointer only after every new generation file is valid and complete.
        self.index['docs'][drawing_id]=entry
        self.persist()
        self.activate(drawing_id,downloaded=True)

    def fetch_drawing(self,drawing_id,expected_signature=None):
        old_current=self.current
        def work():
            drawing=self.session.call('load',id=drawing_id)
            data=base64.b64decode(drawing['payload'],validate=True)
            if hashlib.sha256(data).hexdigest()!=drawing['sha256']:
                raise CloudError('다운로드한 도면의 검증에 실패했습니다.')
            return drawing,cloud_unpack(data)
        def done(result):
            if expected_signature is not None and (self.current!=old_current or self.signature()!=expected_signature or self.has_dialogs()):
                return
            self.install(*result)
            if self.dialog and self.dialog.winfo_exists():
                self.dialog.destroy()
            self.status.set('클라우드 최신 도면을 열었습니다.')
        self.jobs.run(work,done,self.failed)

    def activate(self,drawing_id,downloaded=False):
        self.current=drawing_id
        self.index['current']=drawing_id
        self.switching=True
        try:
            self.app.switch_project(self.working(self.entry()))
        finally:
            self.switching=False
        if downloaded:
            self.entry()['synced_signature']=self.signature()
        self.persist()
        self.app.update_title()

    def open_drawing(self,row):
        def open_it():
            entry=self.index['docs'].get(row['id'])
            if entry and self.working(entry).exists():
                # Open the cache first, including edits made immediately before a crash.
                # Capture and CAS-save those edits before considering a newer remote revision.
                self.activate(row['id'])
                if self.dialog and self.dialog.winfo_exists():
                    self.dialog.destroy()
                self.sync_now()
                self.refresh_at=0
            else:
                self.fetch_drawing(row['id'])
        self.ensure_saved(open_it)

    def new_drawing(self):
        name=simpledialog.askstring('새 도면','도면 이름을 입력하세요.',parent=self.dialog or self.app)
        if not name or not name.strip():
            return
        def create():
            drawing_id=str(uuid.uuid4())
            entry={'name':name.strip()[:120],'stem':uuid.UUID(drawing_id).hex,'base_revision':0}
            self.ns['Store'](self.working(entry)).close()
            self.index['docs'][drawing_id]=entry
            self.activate(drawing_id)
            if self.dialog and self.dialog.winfo_exists():
                self.dialog.destroy()
            self.sync_now()
        self.ensure_saved(create)

    def import_external(self,path=None,legacy=False):
        if path is None:
            path=filedialog.askopenfilename(parent=self.dialog or self.app,title='기존 SQLite 도면 가져오기',filetypes=[('통신 코어 도면','*.sqlite3')])
        if not path:
            return
        source=Path(path)
        def load():
            drawing_id=str(uuid.uuid4())
            stem=uuid.UUID(drawing_id).hex
            entry={'name':source.stem[:120],'stem':stem,'base_revision':0}
            target=self.working(entry)
            cloud_sqlite_copy(source,target)
            with sqlite3.connect(target) as check:
                tables={r[0] for r in check.execute("select name from sqlite_master where type='table'")}
                if not {'nodes','cables','cores','splices'}<=tables:
                    raise CloudError('통신 코어 도면 파일을 선택해 주세요.')
            scenario=None
            candidates=[self.home/'scenarios'/source.stem,self.root_home/'scenarios'/source.stem,source.parent/'scenarios'/source.stem,
                        source.parent.parent/'scenarios'/source.stem]
            for candidate in candidates:
                if candidate.exists():
                    scenario=candidate
                    break
            dest=self.home/'scenarios'/stem
            dest.mkdir(parents=True,exist_ok=True)
            if scenario:
                for kind in ('before','after'):
                    if (scenario/(kind+'.sqlite3')).exists():
                        cloud_sqlite_copy(scenario/(kind+'.sqlite3'),dest/(kind+'.sqlite3'))
            store=self.ns['Store'](target)
            try:
                cloud_unpack(cloud_bundle(store,dest))
            finally:
                store.close()
            self.index['docs'][drawing_id]=entry
            self.activate(drawing_id)
            if self.dialog and self.dialog.winfo_exists():
                self.dialog.destroy()
            self.sync_now()
        self.ensure_saved(load)

    def import_previous(self):
        source=self.root_home/'data'/'telecom_core.sqlite3'
        marker=self.root_home/'data'/'current_project.txt'
        if marker.exists():
            remembered=Path(marker.read_text(encoding='utf-8').strip())
            if remembered.is_file():
                source=remembered
        if not source.exists():
            self.import_external()
            return
        if messagebox.askyesno('기존 도면 가져오기','이 PC에서 마지막으로 사용한 도면을 현재 Google 계정에 복사하고 동기화할까요?\n\n'+str(source),parent=self.dialog or self.app):
            self.import_external(source,legacy=True)

    def projects(self):
        if self.dialog and self.dialog.winfo_exists():
            self.dialog.lift()
            return
        window=tk.Toplevel(self.app)
        self.dialog=window
        window.title('내 도면 · '+self.session.profile['email'])
        window.geometry('840x500')
        window.transient(self.app)
        window.grab_set()
        window.protocol('WM_DELETE_WINDOW',window.destroy if self.current else self.close)
        ttk.Label(window,text='같은 Google 계정으로 다른 PC에서도 이 목록의 도면을 열 수 있습니다.',padding=12).pack(fill='x')
        tree=ttk.Treeview(window,columns=('name','version','updated'),show='headings',selectmode='browse')
        for key,title,width in [('name','도면 이름',420),('version','서버 버전',80),('updated','수정 시각',250)]:
            tree.heading(key,text=title)
            tree.column(key,width=width)
        tree.pack(fill='both',expand=True,padx=10)
        rows={}
        label=ttk.Label(window,text='목록 불러오는 중…',padding=8)
        label.pack(fill='x')
        def populate(remote):
            if not window.winfo_exists():
                return
            rows.clear()
            rows.update({r['id']:r for r in remote})
            for key,entry in self.index['docs'].items():
                if key not in rows:
                    rows[key]={'id':key,'name':entry['name'],'revision':entry.get('base_revision',0),'updated_at':'PC 저장 · 동기화 대기'}
            tree.delete(*tree.get_children())
            for key,row in rows.items():
                tree.insert('','end',iid=key,values=(row['name'],row['revision'],row['updated_at']))
            if self.index.get('current') in rows:
                tree.selection_set(self.index['current'])
            label.configure(text='도면을 선택하고 열기를 누르세요.' if rows else '새 도면을 만들거나 기존 PC 도면을 가져오세요.')
        def load_rows():
            if not window.winfo_exists():
                return
            if not self.jobs.run(lambda:self.session.call('list'),populate,lambda e:(populate([]),label.configure(text=str(e)))):
                window.after(300,load_rows)
        def selected():
            if tree.selection():
                self.open_drawing(rows[tree.selection()[0]])
        buttons=ttk.Frame(window,padding=10)
        buttons.pack(fill='x')
        for text,command in [('열기',selected),('새 도면',self.new_drawing),('기존 PC 도면 가져오기',self.import_previous),('파일 선택해서 가져오기',self.import_external),('새로고침',load_rows)]:
            ttk.Button(buttons,text=text,command=command).pack(side='left',padx=3)
        tree.bind('<Double-1>',lambda e:selected())
        load_rows()

    def admin(self):
        if self.session.profile['role']!='admin':
            return
        window=tk.Toplevel(self.app)
        window.title('사용자 승인 관리')
        window.geometry('750x440')
        tree=ttk.Treeview(window,columns=('email','role','status'),show='headings',selectmode='browse')
        for key,title,width in [('email','Google 이메일',430),('role','권한',100),('status','승인 상태',150)]:
            tree.heading(key,text=title)
            tree.column(key,width=width)
        tree.pack(fill='both',expand=True,padx=10,pady=10)
        states={'pending':'승인 대기','approved':'승인됨','blocked':'차단됨'}
        def populate(rows):
            if not window.winfo_exists():
                return
            tree.delete(*tree.get_children())
            for row in rows:
                tree.insert('','end',iid=row['user_id'],values=(row['email'],'관리자' if row['role']=='admin' else '사용자',states[row['status']]))
        def refresh():
            if not window.winfo_exists():
                return
            if not self.jobs.run(lambda:self.session.call('users'),populate,self.failed):
                window.after(300,refresh)
        def change(status):
            if not tree.selection() or self.jobs.busy:
                return
            target=tree.selection()[0]
            email=tree.item(target,'values')[0]
            if not messagebox.askyesno('승인 상태 변경',email+'\n'+states[status]+' 상태로 변경할까요?',parent=window):
                return
            self.jobs.run(lambda:self.session.call('set_status',user_id=target,status=status),lambda r:refresh(),lambda e:messagebox.showerror('변경 실패',str(e),parent=window))
        bar=ttk.Frame(window,padding=10)
        bar.pack(fill='x')
        for text,status in [('승인','approved'),('차단','blocked'),('승인 대기로','pending')]:
            ttk.Button(bar,text=text,command=lambda s=status:change(s)).pack(side='left',padx=4)
        ttk.Button(bar,text='새로고침',command=refresh).pack(side='right')
        refresh()

    def logout(self):
        self.logout_requested=True
        self.close()

    def close(self):
        if self.closing:
            return
        if self.jobs.busy:
            self.status.set('진행 중인 동기화를 마친 후 종료합니다…')
            self.app.after(300,self.close)
            return
        try:
            self.capture()
        except Exception as error:
            self.failed(error)
            messagebox.showwarning('종료 보류','동기화를 준비하지 못했습니다.\n'+str(error)+'\n\n편집을 마친 뒤 다시 종료해 주세요.',parent=self.app)
            return
        if self.access_lost:
            self.finish_close()
            return
        def failure(error):
            if messagebox.askyesno('동기화 대기 중','서버 저장을 완료하지 못했습니다.\n작업과 전송 대기 파일은 이 PC에 보존됩니다.\n다음 로그인 때 이어서 전송합니다. 지금 종료할까요?',parent=self.app):
                self.finish_close()
            else:self.logout_requested=False
        self.send_next(done=self.close_after_flush,failed=failure)

    def close_after_flush(self):
        # The user may have edited while the prior snapshot was being uploaded.
        self.capture()
        if any(self.outbox().glob('*.json')):
            self.send_next(done=self.close_after_flush,failed=lambda e:self.failed(e))
        else:
            if self.logout_requested:
                self.jobs.run(lambda:cloud_http('/auth/v1/logout?scope=local',{},self.session.tokens['access_token']),
                              lambda r:self.finish_close(),lambda e:self.finish_close())
            else:self.finish_close()

    def finish_close(self):
        self.closing=True
        self.jobs.stop()
        for timer in (self.projects_id,self.tick_id):
            try:self.app.after_cancel(timer)
            except tk.TclError:pass
        if self.logout_requested:
            (self.root_home/'cloud_login.bin').unlink(missing_ok=True)
        self.app.on_close()


def run_cloud_editor(namespace, session, root_home):
    root_home=Path(root_home)
    user_id=str(uuid.UUID(session.profile['user_id']))
    account=root_home/'accounts'/user_id
    account.mkdir(parents=True,exist_ok=True)
    namespace['_CLOUD_ACTIVE']=True
    namespace['_CLOUD_ROOT_HOME']=root_home
    os.environ['TELECOM_APP_HOME']=str(account)
    app=namespace['App']()
    app.cloud=CloudController(app,session,namespace,root_home)
    app.mainloop()
