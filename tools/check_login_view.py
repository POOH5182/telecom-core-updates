"""V216: Google 로그인 as an HTML page.

CloudLogin (the login window) also serves a page that only this PC can reach.
The page runs the window's own login / 승인 확인 methods, keeps showing its
status after the window closed (approved), and the program hands the
작업도면 address to the same tab. Without AUTO_HTML_ON_START (checks, tests)
no page server starts and no browser opens."""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from check_field_survey import code, wf


def request(url, token=None, body=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), method='GET' if body is None else 'POST')
    if token:
        req.add_header('X-Telecom-Token', token)
    req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.status, response.read().decode('utf-8')
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode('utf-8')


def pure_checks():
    state = wf.login_view_state()
    state.update(info='hello', next='http://127.0.0.1:1/?t=x', approved=True)
    value = wf.login_view_status(state)
    assert value['next'] and state['taken'] and '_server' not in value
    page = wf.login_view_document({'token': 'T<', 'version': '26.11.21.02'})
    assert 'Google 계정으로 로그인' in page and 'T\\u003c' in page and '<script src' not in page
    with tempfile.TemporaryDirectory() as temp:
        assert wf.login_view_enabled(temp) is True
        (Path(temp) / 'data').mkdir()
        (Path(temp) / 'data' / 'work_view_start.json').write_text('{"open_on_start": false}', encoding='utf-8')
        assert wf.login_view_enabled(temp) is False
    # handoff from the program to the waiting login page
    holder = code['App'].login_page_handoff.__globals__
    later = []
    fake = SimpleNamespace(after=lambda ms, fn: later.append(fn))
    old = holder.get('LOGIN_WEB')
    try:
        holder['LOGIN_WEB'] = None
        assert code['App'].login_page_handoff(fake, 'http://a') is False
        web = wf.login_view_state(); web['approved'] = True; holder['LOGIN_WEB'] = web
        assert code['App'].login_page_handoff(fake, 'http://a') is True and web['next'] == 'http://a'
        assert code['App'].login_page_handoff(fake, 'http://b') is False, 'only once'
        opened = []
        with patch.object(code['webbrowser'], 'open', lambda url: opened.append(url)):
            later[0]()
        assert opened == ['http://a'], 'page never took it -> new tab'
        web['taken'] = True; opened.clear()
        with patch.object(code['webbrowser'], 'open', lambda url: opened.append(url)):
            later[0]()
        assert opened == []
        code['App'].login_page_message(fake, 'msg'); assert web['message'] == 'msg'
    finally:
        holder['LOGIN_WEB'] = old
    print('PASS login page status, enable switch and handoff to the work drawing')


def ui_checks():
    if sys.platform != 'win32' and not os.environ.get('TELECOM_CHECK_UI'):
        return
    with tempfile.TemporaryDirectory() as temp:
        opened = []
        with patch.object(wf.webbrowser, 'open', lambda url: opened.append(url) or True):
            quiet = wf.CloudLogin({'AUTO_HTML_ON_START': False}, temp)
            quiet.update(); assert quiet.web is None and opened == []; quiet.close()
            login = wf.CloudLogin({'AUTO_HTML_ON_START': True, 'APP_VERSION_LABEL': '26.11.21.02'}, temp)
        try:
            login.update()
            assert login.web is not None and len(opened) == 1, opened
            url = opened[0]; token = url.split('t=', 1)[1]; base = url.split('/?', 1)[0]
            calls = []
            login.login = lambda: calls.append('login')
            box = {}

            def client():
                try:
                    box['page'] = request(url)
                    box['bad'] = request(base + '/?t=wrong')
                    box['status'] = request(base + '/api/status', token)
                    box['nostatus'] = request(base + '/api/status')
                    box['login'] = request(base + '/api/login', token, {'remember': False})
                    box['check'] = request(base + '/api/check', token, {})
                    box['show'] = request(base + '/api/show', token, {})
                except Exception as error:
                    box['error'] = repr(error)
            thread = threading.Thread(target=client); thread.start(); deadline = time.time() + 60
            while thread.is_alive() and time.time() < deadline:
                login.update(); time.sleep(.02)
            thread.join(1)
            assert 'error' not in box, box.get('error')
            assert box['page'][0] == 200 and 'Google 계정으로 로그인' in box['page'][1] and '26.11.21.02' in box['page'][1]
            assert box['bad'][0] == 403 and box['nostatus'][0] == 403
            status = json.loads(box['status'][1]); assert status['ok'] and status['value']['info'], status
            assert json.loads(box['login'][1])['ok'] and calls == ['login'] and login.remember.get() is False
            check = json.loads(box['check'][1]); assert check['ok'] is False and '로그인' in check['error'], check
            assert json.loads(box['show'][1])['ok']
            login.info.set('승인 대기'); assert login.web_state['info'] == '승인 대기'
            login.candidate = SimpleNamespace(remember=lambda: None)
            login.checked({'status': 'approved', 'email': 'a@b'})
            assert login.session is login.candidate and login.web_state['approved'] and login.web.closed
            login.web_state['next'] = 'http://127.0.0.1:9/?t=z'
            done = {}

            def after_close():
                done['status'] = request(base + '/api/status', token)
                done['login'] = request(base + '/api/login', token, {'remember': True})
            thread = threading.Thread(target=after_close); thread.start(); thread.join(30)
            value = json.loads(done['status'][1])['value']
            assert value['approved'] and value['next'].startswith('http://127.0.0.1:9') and login.web_state['taken']
            assert json.loads(done['login'][1])['ok'] is False, 'window gone: actions refused, status still served'
        finally:
            try:
                login.close()
            except Exception:
                pass
    print('PASS Windows login window serves the HTML login page, runs its own login/check, keeps status after approval')


if __name__ == '__main__':
    pure_checks()
    ui_checks()
