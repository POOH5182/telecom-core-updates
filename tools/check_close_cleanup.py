"""V145: closing the program while a list window keeps the map highlighted must not show an error box."""
import os
import sys
import time
from unittest.mock import patch
from check_route_legend import RouteLegendTests,code


def pump(app,seconds=0.6):
    end=time.time()+seconds
    try:
        while time.time()<end:app.update();time.sleep(0.02)
    except code['tk'].TclError:pass


def new_app(case):
    app=code['App']();app.store.close();app.store=case.s
    for i,nid in enumerate(case.nodes):case.s.update_node_pos(nid,150+i*300,260)
    app.refresh();app.update();return app


def main():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    tk=code['tk']
    case=RouteLegendTests();case.setUp()
    try:
        (case.home/'ui').mkdir()
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error, \
             patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showwarning'):
            case.connect_all()
            # 1) 코어확인 목록이 지도를 깜빡이게 하는 중에 프로그램 종료 (사용자 화면 그대로 재현)
            app=new_app(case)
            dialog=code['CoreCheckDialog'](app,case.s);dialog.kind.set('전체코어');dialog.reload();app.update()
            dialog.tree.selection_set(next(iter(dialog.row_meta)));app.update()
            assert app.highlight_owner is dialog and app.highlight_blink_job is not None
            app.schedule_refresh()
            assert str(app.canvas)=='.!frame5.!canvas',str(app.canvas)
            app.on_close();pump(app)
            assert not error.called,error.call_args
            print('PASS closing with a blinking core route window shows no error box')
            # 3) 이미 사라진 창에 대한 늦은 Tk 오류는 기록만, 진짜 오류는 그대로 알림
            app=code['App']();app.update()
            stale=tk.TclError('invalid command name ".!frame99.!canvas"')
            app.report_callback_exception(tk.TclError,stale,None)
            assert 'frame99' in (code['app_dir']()/'error.log').read_text(encoding='utf-8')
            app.report_callback_exception(tk.TclError,tk.TclError('invalid command name "139822456577856run"'),None)
            assert not error.called,error.call_args
            app.report_callback_exception(ValueError,ValueError('real problem'),None)
            assert error.called,'real errors must still be shown'
            error.reset_mock()
            live=str(app.canvas)
            app.report_callback_exception(tk.TclError,tk.TclError(f'invalid command name "{live}"'),None)
            assert error.called,'errors on a live widget must still be shown'
            error.reset_mock()
            app.schedule_refresh();app.after(5000,lambda:None)
            app.on_close()
            assert not error.called,error.call_args
            print('PASS stale-widget errors are logged quietly; real errors still show; pending jobs cancelled on close')
    finally:case.tearDown()


if __name__=='__main__':
    main()
