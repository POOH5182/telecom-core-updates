"""Owner-monitor centering, native message semantics and negative desktop positions."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_after_plan import code,wf


class MonitorTests(unittest.TestCase):
    def test_three_monitors_and_vertical_negative_taskbar_areas(self):
        for bounds,expected in (
            ((-1920,0,1920,1040),(-1190,405)),
            ((0,0,2560,1400),(1050,585)),
            ((2560,-240,1920,1040),(3290,165)),
            ((0,-1440,2560,1400),(1050,-855)),
            ((48,0,1872,1080),(754,425))):
            self.assertEqual(wf.centered_popup_position(460,230,bounds),expected)
        self.assertEqual(wf.centered_popup_position(2200,1400,(-1920,0,1920,1040)),(-1920,0))


def native_rect(window):
    import ctypes
    from ctypes import wintypes
    rect=wintypes.RECT();api=ctypes.windll.user32
    api.GetWindowRect.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.RECT)]
    assert api.GetWindowRect(wf.popup_window_handle(window),ctypes.byref(rect))
    return rect.left,rect.top,rect.right-rect.left,rect.bottom-rect.top


def assert_centered(window,parent,bounds=None):
    window.update_idletasks();x,y,w,h=native_rect(window)
    expected=wf.centered_popup_position(w,h,bounds or wf.popup_monitor_bounds(parent))
    assert abs(x-expected[0])<=2 and abs(y-expected[1])<=2,((x,y,w,h),expected)


def windows_ui():
    if sys.platform!='win32':return
    import ctypes
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            app.geometry('1000x720+30+50');app.update()
            # Obsolete saved coordinates on another monitor must never win.
            path=Path(temp)/'data'/'popup_positions.json'
            wf.save_dialog_position(path,'RememberedToplevel',-1800,-1200);saved=path.read_bytes()
            first=wf.RememberedToplevel(app);first.geometry('460x230');app.update();assert_centered(first,app)
            first.geometry('+55+60');app.update();first.destroy()
            assert path.read_bytes()==saved
            second=wf.RememberedToplevel(app);second.geometry('460x230');app.update();assert_centered(second,app)
            child=wf.TableDialog(second,'합성 중첩 확인',('항목',),[('내용',)]);app.update();assert_centered(child,second)
            child.destroy()
            # Exercise actual SetWindowPos with simulated three-monitor work
            # areas; the hosted Windows runner itself has only one display.
            for bounds in ((-1920,0,1920,1040),(0,0,2560,1400),(2560,-240,1920,1040),(0,-1440,2560,1400)):
                owners=[]
                def monitor(parent):owners.append(parent);return bounds
                with patch.object(wf,'popup_monitor_bounds',side_effect=monitor):
                    child=wf.RememberedToplevel(second);child.geometry('460x230');app.update()
                    assert owners and all(p is second for p in owners),owners
                    assert_centered(child,second,bounds);child.destroy()
            plain=code['tk'].Toplevel(second);plain.geometry('360x160');app.update();assert_centered(plain,second);plain.destroy()
            # Native notice keeps native OK semantics while its activation hook
            # centers it. Post the OK command so the gate needs no human input.
            real=wf.center_native_popup;seen=[];api=ctypes.windll.user32
            api.PostMessageW.argtypes=[ctypes.c_void_p,ctypes.c_uint,ctypes.c_size_t,ctypes.c_ssize_t]
            def native_center(hwnd,bounds):
                result=real(hwnd,bounds);seen.append((hwnd,bounds,result));api.PostMessageW(hwnd,0x111,1,0);return result
            import threading
            api.FindWindowW.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p];api.FindWindowW.restype=ctypes.c_void_p
            def close_failed_hook():
                hwnd=api.FindWindowW(None,'합성 중앙 알림')
                if hwnd:api.PostMessageW(hwnd,0x111,1,0)
            timeout=threading.Timer(3,close_failed_hook);timeout.daemon=True;timeout.start()
            try:
                with patch.object(wf,'center_native_popup',side_effect=native_center):
                    answer=wf.messagebox.showinfo('합성 중앙 알림','확인',parent=second)
            finally:timeout.cancel()
            assert answer=='ok' and len(seen)==1,(answer,seen)
            second.destroy();app.update();assert not errors,errors
        finally:app.on_close()
    print('PASS Windows owner-monitor centering, ignored stale position, nested/plain/native dialogs and synthetic three-display negative coordinates')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MonitorTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
