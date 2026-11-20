"""V209: the 작업도면 HTML page can edit the drawing.

The desktop app starts a tiny web server that only this PC can reach
(127.0.0.1, random port, random token). The browser page asks it for the
drawing and sends edits; every request is handed to the app's own window
thread, so the same Store methods and rules as the desktop screens run
(update_core, locks, 오류코어 checks, undo history).

- WorkViewServer(routes) serves GET / (page), GET /api/scene and POST /api/<name>
- run_ui(fn) waits for pump() (called from the Tk thread) to run fn
"""
import http.server as _wv_http
import queue as _wv_queue
import secrets as _wv_secrets
import threading as _wv_threading
from urllib.parse import urlparse as _wv_urlparse, parse_qs as _wv_parse_qs


WORK_SERVER_MAX_BODY=64*1024


class WorkViewServer:
    """routes: {'page': fn()->html, 'scene': fn()->dict, '<name>': fn(payload)->dict}.
    Route functions run on the UI thread via pump()."""

    def __init__(self,routes,host='127.0.0.1',direct=()):
        # V216: names in `direct` run on the server thread (must be thread safe),
        # e.g. the login page status that is still read after the login window closed.
        self.direct=set(direct);self.routes=dict(routes);self.token=_wv_secrets.token_urlsafe(24);self.requests=_wv_queue.Queue();self.closed=False
        server=self

        class Handler(_wv_http.BaseHTTPRequestHandler):
            def log_message(self,*args):pass

            def send_text(self,code,text,ctype='application/json; charset=utf-8'):
                body=text.encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)))
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                self.send_header('Referrer-Policy','no-referrer')
                self.end_headers();self.wfile.write(body)

            def send_json(self,code,value):self.send_text(code,html_view_json(value))

            def allowed_host(self):
                return self.headers.get('Host','') in (f'127.0.0.1:{server.port}',f'localhost:{server.port}')

            def header_token(self):
                return _wv_secrets.compare_digest(str(self.headers.get('X-Telecom-Token','')),server.token)

            def do_GET(self):
                if not self.allowed_host():return self.send_json(403,{'ok':False,'error':'허용되지 않은 주소입니다.'})
                parsed=_wv_urlparse(self.path)
                if parsed.path=='/':
                    token=(_wv_parse_qs(parsed.query).get('t') or [''])[0]
                    if not _wv_secrets.compare_digest(token,server.token):return self.send_text(403,'<!doctype html><meta charset="utf-8">프로그램의 「작업도면 전·중·후」 버튼으로 다시 여세요.','text/html; charset=utf-8')
                    return self.answer('page',None,html=True)
                if parsed.path in ('/api/scene','/api/status') and parsed.path.rsplit('/',1)[-1] in server.routes:
                    if not self.header_token():return self.send_json(403,{'ok':False,'error':'다시 열어 주세요.'})
                    return self.answer(parsed.path.rsplit('/',1)[-1],None)
                return self.send_json(404,{'ok':False,'error':'없는 주소입니다.'})

            def do_POST(self):
                if not self.allowed_host() or not self.header_token():return self.send_json(403,{'ok':False,'error':'다시 열어 주세요.'})
                name=_wv_urlparse(self.path).path.rsplit('/',1)[-1]
                if not self.path.startswith('/api/') or name in ('page','scene','status') or name not in server.routes:return self.send_json(404,{'ok':False,'error':'없는 기능입니다.'})
                try:size=int(self.headers.get('Content-Length') or 0)
                except ValueError:size=-1
                if size<0 or size>WORK_SERVER_MAX_BODY:return self.send_json(413,{'ok':False,'error':'요청이 너무 큽니다.'})
                try:payload=json.loads(self.rfile.read(size).decode('utf-8') or '{}')
                except (ValueError,UnicodeDecodeError):return self.send_json(400,{'ok':False,'error':'요청을 읽지 못했습니다.'})
                if not isinstance(payload,dict):return self.send_json(400,{'ok':False,'error':'요청을 읽지 못했습니다.'})
                return self.answer(name,payload)

            def do_OPTIONS(self):self.send_json(405,{'ok':False})

            def answer(self,name,payload,html=False):
                route=server.routes[name]
                call=route if payload is None else (lambda:route(payload))
                try:value=call() if name in server.direct else server.run_ui(call)
                except ValueError as error:return self.send_json(200,{'ok':False,'error':str(error)})
                except Exception as error:return self.send_json(500,{'ok':False,'error':'처리하지 못했습니다: '+str(error)[:300]})
                if html:return self.send_text(200,value,'text/html; charset=utf-8')
                return self.send_json(200,value if isinstance(value,dict) and 'ok' in value else {'ok':True,'value':value})

        self.httpd=_wv_http.ThreadingHTTPServer((host,0),Handler);self.httpd.daemon_threads=True
        self.port=self.httpd.server_address[1]
        self.thread=_wv_threading.Thread(target=self.httpd.serve_forever,name='work-view-server',daemon=True);self.thread.start()

    def url(self):
        return f'http://127.0.0.1:{self.port}/?t={self.token}'

    def run_ui(self,fn,timeout=120):
        if self.closed:raise ValueError('프로그램이 닫혔습니다.')
        holder={};done=_wv_threading.Event();self.requests.put((fn,holder,done))
        if not done.wait(timeout):raise ValueError('프로그램이 응답하지 않습니다. 열린 창을 닫고 다시 시도하세요.')
        if 'error' in holder:raise holder['error']
        return holder.get('value')

    def pump(self):
        """Run waiting requests. Call only from the UI thread."""
        count=0
        while True:
            try:fn,holder,done=self.requests.get_nowait()
            except _wv_queue.Empty:return count
            try:holder['value']=fn()
            except Exception as error:holder['error']=error
            finally:done.set();count+=1

    def close(self):
        if self.closed:return
        self.closed=True
        try:self.httpd.shutdown();self.httpd.server_close()
        except Exception:pass
        self.pump()

    def close_later(self,seconds=3):
        """V216: stop serving from any thread after a short delay (login page done)."""
        def stop():
            _wv_threading.Event().wait(seconds)
            try:self.httpd.shutdown();self.httpd.server_close()
            except Exception:pass
        _wv_threading.Thread(target=stop,name='work-view-server-stop',daemon=True).start()
