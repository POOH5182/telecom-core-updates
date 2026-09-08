"""Real Tk/SQLite/DPAPI tests with an in-memory revision server; no customer data."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import runpy
import sys
import tempfile
import threading
import time
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
code=runpy.run_path(str(ROOT/'app'/'telecom_core_app.pyw'),run_name='cloud_smoke')
ns=code['App'].__init__.__globals__
cloud=ns['workflow']
ns['_CLOUD_ACTIVE']=True
HEADLESS='--headless' in sys.argv


class Value:
    def __init__(self):self.value=''
    def set(self,value):self.value=value
    def configure(self,**kw):pass


class LocalJobs:
    """Deterministic event delivery for the platform-independent persistence gate."""
    def __init__(self):self.busy=False;self.closed=False;self.pending=None
    def run(self,work,done,failed):
        if self.busy or self.closed:return False
        self.busy=True;self.pending=(work,done,failed)
        return True
    def step(self):
        if not self.pending:return
        work,done,failed=self.pending;self.pending=None
        try:result=work()
        except Exception as error:
            self.busy=False;failed(error)
        else:
            self.busy=False;done(result)


class LocalApp:
    """Only the Tk shell is replaced; Store, bundle and controller are production code."""
    def __init__(self,home):
        home.mkdir(parents=True,exist_ok=True)
        self.home=home;self.store=ns['Store'](home/'empty.sqlite3');self.pending_drag=False
    def switch_project(self,path):
        self.store.close();self.store=ns['Store'](path)
    def scenario_folder(self):
        p=self.home/'scenarios'/self.store.path.stem;p.mkdir(parents=True,exist_ok=True);return p
    def scenario_path(self,kind):return self.scenario_folder()/(kind+'.sqlite3')
    def scenario_kind(self):return 'before'
    def update_title(self):pass
    def update(self):self.cloud.jobs.step()
    def update_idletasks(self):pass
    def winfo_children(self):return []
    def on_close(self):self.store.close()
    def after(self,*args):pass


class Server:
    def __init__(self):
        self.rows={}
        self.fail=None
        self.profile={'user_id':str(uuid.uuid4()),'email':'synthetic@example.invalid',
                      'role':'admin','status':'approved'}
        self.lock=threading.Lock()

    def call(self,action,**request):
        with self.lock:
            if self.fail=='network':
                raise cloud.CloudError('Synthetic network outage','network')
            if action=='list':
                return [{k:v for k,v in r.items() if k!='payload'} for r in copy.deepcopy(list(self.rows.values()))]
            if action=='load':
                return copy.deepcopy(self.rows[request['id']])
            if action=='save':
                old=self.rows.get(request['id'])
                if old and old['operation_id']==request['operation_id']:
                    return copy.deepcopy(old)
                if (old['revision'] if old else 0)!=request['base_revision']:
                    raise cloud.CloudError('DRAWING_CONFLICT','40001')
                assert hashlib.sha256(base64.b64decode(request['payload'])).hexdigest()==request['sha256']
                row=dict(request,revision=request['base_revision']+1,updated_at='synthetic')
                self.rows[request['id']]=row
                if self.fail=='lost_ack':
                    self.fail=None
                    raise cloud.CloudError('Synthetic lost acknowledgement','network')
                return copy.deepcopy(row)
            raise AssertionError(action)


def pump(app,controller):
    deadline=time.monotonic()+20
    while controller.jobs.busy:
        app.update()
        if time.monotonic()>deadline:
            raise AssertionError('Cloud task did not finish')
        time.sleep(.01)
    if not controller.closing:
        app.update_idletasks()


def make_app(home,server):
    os.environ['TELECOM_APP_HOME']=str(home)
    ns['_CLOUD_ROOT_HOME']=home.parent
    if HEADLESS:
        app=LocalApp(home)
        controller=cloud.CloudController.__new__(cloud.CloudController)
        controller.app,controller.session,controller.ns=app,server,ns
        controller.root_home,controller.home=home.parent,home
        controller.index_path=home/'cloud_index.json'
        controller.index=json.loads(controller.index_path.read_bytes()) if controller.index_path.exists() else {
            'owner':server.profile['user_id'],'docs':{},'current':None}
        controller.current=None;controller.switching=False;controller.closing=False
        controller.logout_requested=False;controller.access_lost=False
        controller.retry_at=0;controller.refresh_at=0;controller.dialog=None
        controller.jobs=LocalJobs();controller.status=Value();controller.status_label=Value()
        app.cloud=controller
        return app,controller
    app=ns['App']()
    app.withdraw()
    with patch.object(cloud.CloudController,'projects'),patch.object(cloud.CloudController,'tick'):
        controller=cloud.CloudController(app,server,ns,home.parent)
    app.cloud=controller
    return app,controller


def new_drawing(app,controller,name):
    key=str(uuid.uuid4())
    entry={'name':name,'stem':uuid.UUID(key).hex,'base_revision':0}
    ns['Store'](controller.working(entry)).close()
    controller.index['docs'][key]=entry
    controller.activate(key)
    controller.sync_now()
    pump(app,controller)
    return key


def names(app):
    return {n['name'] for n in app.store.nodes()}


def run():
    assert HEADLESS or sys.platform=='win32','Run this gate on Windows or pass --headless for persistence only.'
    bundled=(ROOT/'app'/'workflow_v50.py').read_text(encoding='utf-8').split('\n\n# BEGIN TELECOM CLOUD CLIENT\n')[1]
    assert bundled==(ROOT/'cloud'/'client.py').read_text(encoding='utf-8')
    if not HEADLESS:
        secret=b'synthetic-refresh-token-only'
        encrypted=cloud.cloud_protect(secret)
        assert secret not in encrypted and cloud.cloud_protect(encrypted,True)==secret
    errors=[]
    with tempfile.TemporaryDirectory() as tmp, \
         patch.object(cloud.messagebox,'showinfo'), \
         patch.object(cloud.messagebox,'showwarning'), \
         patch.object(cloud.messagebox,'showerror',side_effect=lambda *a,**k:errors.append(str(a))):
        root=Path(tmp)
        if not HEADLESS:
            login=cloud.CloudLogin(ns,root)
            login.withdraw()
            class Candidate:
                profile={'email':'pending@example.invalid','status':'pending'}
                def remember(self):pass
            login.candidate=Candidate()
            login.checked(login.candidate.profile)
            assert login.session is None and login.winfo_exists(),'Pending user entered editor'
            login.checked(dict(login.candidate.profile,status='approved'))
            assert login.session is login.candidate

        server=Server()
        home=root/'pc-one'
        app,c=make_app(home,server)
        app.report_callback_exception=lambda *e:errors.append(str(e))
        key=new_drawing(app,c,'Synthetic drawing')
        a=app.store.add_node('first',0,0)
        app.store.backup_to(app.scenario_path('before'))
        app.store.add_node('after',100,0)
        app.store.backup_to(app.scenario_path('after'))
        c.sync_now();pump(app,c)
        contents=cloud.cloud_unpack(base64.b64decode(server.rows[key]['payload']))
        assert set(contents)==cloud.CLOUD_FILES,'Before/after snapshots missing'
        assert c.entry()['base_revision']==2

        # A save accepted by the server but not acknowledged must retry exactly once.
        app.store.add_node('lost acknowledgement',200,0)
        server.fail='lost_ack'
        c.sync_now();pump(app,c)
        assert list(c.outbox().glob('*.json'))
        revision=server.rows[key]['revision']
        c.finish_close()
        app,c=make_app(home,server)
        c.open_drawing({'id':key});pump(app,c)
        assert server.rows[key]['revision']==revision,'Lost ACK duplicated the server revision'
        assert not list(c.outbox().glob('*.json'))
        assert 'lost acknowledgement' in names(app)

        # An edit during upload remains dirty and is included when closing.
        app.store.add_node('first snapshot',300,0)
        c.capture()
        app.store.add_node('late edit',400,0)
        c.close();pump(app,c)
        data=cloud.cloud_unpack(base64.b64decode(server.rows[key]['payload']))
        verify=root/'verify.sqlite3';verify.write_bytes(data['working.sqlite3'])
        check=ns['Store'](verify)
        assert {'first snapshot','late edit'}<={r['name'] for r in check.nodes()}
        check.close()

        # Crash without capturing: local edits must not be replaced by a newer remote copy.
        app,c=make_app(home,server)
        c.open_drawing({'id':key});pump(app,c)
        app.store.add_node('local unqueued edit',500,0)
        c.finish_close()
        old=copy.deepcopy(server.rows[key])
        remote_db=root/'remote.sqlite3';remote_db.write_bytes(data['working.sqlite3'])
        remote_store=ns['Store'](remote_db)
        remote_store.add_node('other PC edit',600,0)
        remote_payload=cloud.cloud_bundle(remote_store,root/'remote-snapshots')
        remote_store.close()
        server.call('save',id=key,name=old['name'],base_revision=old['revision'],operation_id=str(uuid.uuid4()),
                    payload=base64.b64encode(remote_payload).decode(),sha256=hashlib.sha256(remote_payload).hexdigest())
        app,c=make_app(home,server)
        c.open_drawing({'id':key});pump(app,c)
        conflict=c.current
        assert conflict!=key and set(server.rows)=={key,conflict},'Conflict did not preserve both drawings'
        assert 'local unqueued edit' in names(app) and 'other PC edit' not in names(app)
        assert '충돌 보관' in server.rows[conflict]['name']
        c.open_drawing({'id':key});pump(app,c)
        assert 'other PC edit' in names(app) and 'local unqueued edit' not in names(app)

        # A download completed after a new local edit must not install its stale snapshot.
        before=set(names(app))
        c.fetch_drawing(key,expected_signature=c.signature())
        app.store.add_node('edit during download',700,0)
        pump(app,c)
        assert before|{'edit during download'}==names(app)
        c.finish_close()

        # A second PC loads the account's server drawing including undo history.
        app,c=make_app(root/'pc-two',server)
        c.fetch_drawing(conflict);pump(app,c)
        assert 'local unqueued edit' in names(app)
        app.store.undo()
        assert 'local unqueued edit' not in names(app),'Undo history did not travel with the drawing'
        app.store.redo()
        assert 'local unqueued edit' in names(app)
        c.finish_close()
        assert not errors,errors
    if not HEADLESS:print('PASS Windows DPAPI, approval gate and Tk editor')
    print('PASS SQLite before/after bundle, lost-ACK retry, close flush, crash recovery, two-PC conflict preservation, stale-download protection and cloud undo history')


if __name__=='__main__':
    run()
