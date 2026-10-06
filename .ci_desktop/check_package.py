"""Windows check: unzip the desktop package and start it exactly via 실행.bat."""
import ctypes, json, os, subprocess, sys, tempfile, time, zipfile
from pathlib import Path

ZIP = Path(sys.argv[1]).resolve()
user32 = ctypes.windll.user32
TITLE = '통신 코어 도면 · Google 로그인'


def until(check, timeout=60):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError('timeout')


def run(case):
    base = Path(tempfile.mkdtemp(prefix='pkg check '))
    zipfile.ZipFile(ZIP).extractall(base)
    home = base / '통신코어도면'
    assert (home / '실행.bat').is_file(), list(base.rglob('*'))
    if case == 'old':
        meta = json.loads((home / 'version.json').read_text())
        meta['version'] -= 1
        (home / 'version.json').write_text(json.dumps(meta))
    env = {k: v for k, v in os.environ.items() if not k.startswith('TELECOM_')}
    log = home / 'cmd.log'
    with log.open('wb') as out:
        proc = subprocess.Popen([os.environ['COMSPEC'], '/d', '/c', str(home / '실행.bat')], cwd=base,
                                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env,
                                creationflags=subprocess.CREATE_NEW_CONSOLE)
        rc = proc.wait(timeout=120)
    text = log.read_bytes().decode('utf-8', 'replace')
    print(text)
    assert rc == 0, rc
    hwnd = until(lambda: user32.FindWindowW(None, TITLE))
    assert user32.IsWindowVisible(hwnd)
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    state = json.loads((home / 'update_state.json').read_text(encoding='utf-8'))
    print(case, state)
    if case == 'old':
        assert state['active'].startswith('program_versions/v125-') and state['last_result'] == 'V125 업데이트 완료', state
    else:
        assert state['active'] == '.' and state['last_result'] == 'V125 사용 중 · 새 업데이트 없음', state
    user32.PostMessageW(hwnd, 0x0010, 0, 0)
    until(lambda: not user32.IsWindow(hwnd), 20)
    handle = ctypes.windll.kernel32.OpenProcess(0x100000, False, pid.value)
    if handle:
        assert ctypes.windll.kernel32.WaitForSingleObject(handle, 15000) == 0
    print(f'PASS {case}: 실행.bat exited 0, login window shown (pid {pid.value}), closed cleanly')


for case in ('fresh', 'old'):
    run(case)
