"""V84: unchanged installed BAT/updater exits while a console-free GUI owns its lock."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from build_release import build_release
from telecom_updater import InstanceLock,UpdateError

ROOT=Path(__file__).resolve().parents[1]
APP=ROOT/'app'/'telecom_core_app.pyw'
VERSION=json.loads((ROOT/'app'/'version.json').read_text())['version']


def until(check,timeout=15):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        result=check()
        if result:return result
        time.sleep(.05)
    raise AssertionError('Timed out waiting for launcher/GUI condition')


def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}


def alive(pid):
    api=ctypes.windll.kernel32
    api.OpenProcess.restype=ctypes.c_void_p
    api.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
    api.CloseHandle.argtypes=[ctypes.c_void_p]
    handle=api.OpenProcess(0x100000,False,pid)
    if not handle:return False
    try:return api.WaitForSingleObject(handle,0)==258
    finally:api.CloseHandle(handle)


def write_program(folder,version,gui=True):
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'version.json').write_text(json.dumps(dict(schema=1,product='telecom-core-python',version=version,launcher_min=1)))
    shutil.copy(ROOT/'app'/f'workflow_v{VERSION}.py',folder/f'workflow_v{version}.py')
    if not gui:
        (folder/'telecom_core_app.pyw').write_text("from pathlib import Path\nPath('fallback.ok').write_text('ok')\n")
        return
    driver=f'''import workflow_v{version}
import ctypes,json,os,runpy,sys
from pathlib import Path
sys.path.insert(0,{str(APP.parent)!r})
code=runpy.run_path({str(APP)!r},run_name='desktop_gate')
g=code['run_desktop'].__globals__;g['__file__']=__file__
home=Path(os.environ['TELECOM_APP_HOME'])
if os.environ.get('TELECOM_GUI_DETACHED')!='1':
    (home/'bootstrap.json').write_text(json.dumps(dict(pid=os.getpid(),console=ctypes.windll.kernel32.GetConsoleWindow())))
class Login(g['tk'].Tk):
    def __init__(self,*args):
        if (home/'fail-start').exists():
            (home/'data'/'sentinel.txt').write_text('candidate partial write')
            (home/'failed_pid.json').write_text(json.dumps(dict(pid=os.getpid())))
            raise RuntimeError('Synthetic failure before readiness')
        super().__init__();self.session=None;self.title('Telecom console integration gate');self.geometry('360x150')
        g['tk'].Label(self,text='GUI stays open after BAT exits').pack()
        self.after(50,self.poll)
    def poll(self):
        (home/'gui.json').write_text(json.dumps(dict(pid=os.getpid(),console=ctypes.windll.kernel32.GetConsoleWindow(),mapped=self.winfo_ismapped(),ready=os.environ.get('TELECOM_READY_PATH'),token=os.environ.get('TELECOM_READY_TOKEN'))))
        if (home/'close.gui').exists():self.destroy()
        else:self.after(100,self.poll)
g['workflow'].CloudLogin=Login
result=g['launch_windowless_copy']()
if result is not None:sys.exit(result)
g['run_desktop']()
'''
    (folder/'telecom_core_app.pyw').write_text(driver,encoding='utf-8')


def run_case(mode):
    with tempfile.TemporaryDirectory(prefix='telecom console ') as temp:
        home=Path(temp);pid=None;cmd=None
        try:
            shutil.copy(ROOT/'tools'/'telecom_updater.py',home/'telecom_updater.py')
            write_program(home,VERSION if mode=='normal' else VERSION-1,gui=mode=='normal')
            (home/'data').mkdir();(home/'data'/'sentinel.txt').write_text('original data')
            config=dict(enabled=False,source='')
            if mode!='normal':
                candidate=home/'candidate';write_program(candidate,VERSION)
                build_release(candidate,home/'release')
                config=dict(enabled=True,source=str(home/'release'/'latest.json'))
            if mode=='failure':(home/'fail-start').touch()
            (home/'update_config.json').write_text(json.dumps(config))
            bat=home/'run.bat'
            bat.write_text('@echo off\ncd /d "%~dp0"\n"'+sys.executable+'" -u telecom_updater.py\nexit /b %errorlevel%\n')
            env=os.environ.copy()
            # The English CI worker redirects the Korean installed launcher's
            # console output to a file; give that pipe an explicit UTF-8 codec.
            env['PYTHONIOENCODING']='utf-8';env['PYTHONUTF8']='1'
            for key in ('TELECOM_APP_HOME','TELECOM_LAUNCHED','TELECOM_GUI_DETACHED','TELECOM_READY_PATH','TELECOM_READY_TOKEN'):env.pop(key,None)
            with (home/'cmd.log').open('wb') as log:
                cmd=subprocess.Popen([os.environ['COMSPEC'],'/d','/c',str(bat)],cwd=home,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NEW_CONSOLE)
                assert cmd.wait(timeout=20)==0,(home/'cmd.log').read_text(errors='replace')
            assert (home/'data'/'sentinel.txt').read_text()=='original data'
            state=read(home/'update_state.json')
            if mode=='failure':
                assert (home/'fallback.ok').exists();assert not state.get('pending') and state['active']=='.' and state['rejected']
                failed=read(home/'failed_pid.json');assert failed and not alive(failed['pid'])
                assert 'Synthetic failure' in (home/'desktop_output.log').read_text(errors='replace')
                print('PASS Windows failed detached startup exits before old launcher rollback; original data and previous version restored')
                return
            gui=until(lambda:read(home/'gui.json') if read(home/'gui.json').get('mapped') else None);pid=gui['pid']
            assert gui['console']==0 and alive(pid),gui
            assert read(home/'bootstrap.json')['console']!=0
            with InstanceLock(home):pass # Parent launcher really exited and released its lock.
            try:
                with InstanceLock(home,'telecom_app.lock'):pass
            except UpdateError:pass
            else:raise AssertionError('Detached GUI did not retain the app lifetime lock')
            with (home/'second.log').open('wb') as log:
                second=subprocess.run([sys.executable,str(home/'telecom_updater.py')],cwd=home,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
            assert second.returncode!=0 and read(home/'gui.json')['pid']==pid and alive(pid)
            if mode=='update':
                assert state['active'].startswith(f'program_versions/v{VERSION}-') and not state.get('pending'),state
                assert Path(gui['ready']).read_text()==gui['token'] # Never delete updater's commit marker.
            else:assert not Path(gui['ready']).exists() # Private normal-start marker is cleaned up.
            (home/'close.gui').touch();until(lambda:not alive(pid));pid=None
            with InstanceLock(home,'telecom_app.lock'):pass
            print('PASS Windows '+mode+': real CMD exited, GUI mapped without console, launcher lock released/app lock retained, duplicate blocked, normal close cleaned up')
        finally:
            (home/'close.gui').touch()
            pid=pid or read(home/'gui.json').get('pid')
            if pid:
                try:until(lambda:not alive(pid),3)
                except AssertionError:subprocess.run(['taskkill','/PID',str(pid),'/F'],capture_output=True)
            if cmd and cmd.poll() is None:cmd.terminate();cmd.wait(timeout=5)


if __name__=='__main__':
    if sys.platform!='win32':print('Windows process integration gate runs on Windows only.')
    else:
        for mode in ('normal','update','failure'):run_case(mode)
