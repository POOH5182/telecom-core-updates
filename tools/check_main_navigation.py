"""V139: pages opened from the main drawing share one window with Back/Forward."""
import faulthandler
import os
import sys
import tempfile
from unittest.mock import patch
from check_after_plan import code,wf


def windows_ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    faulthandler.dump_traceback_later(100,exit=True)
    tk=code['tk']
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp),patch.object(code['messagebox'],'showwarning') as warning,patch.object(code['messagebox'],'showerror') as error,patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'askyesno',return_value=True):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','after')");s.conn.commit()
            a=s.add_node('RN 시작',140,180,node_type='rn');b=s.add_node('RN 끝',600,180,node_type='rn');s.add_cable(a,b,'RN 구간','12C','기설')
            app.update_title();app.refresh();app.update()
            before=wf.plan_snapshot(s.conn);history=s.history_rows()
            # First page opened from the main drawing.
            rn=code['open_detail_dialog'](app,s,'node',a);app.update();rn.name_var.set('저장 전 RN 이름')
            rn.geometry('1000x700+10+20');app.update()
            nav=rn._navigation;assert app._navigation_main is nav and nav.active() is rn
            # A second main-menu page replaces it in the same window.
            check=code['CoreCheckDialog'](app,s);app.update();app.update()
            assert check._navigation is nav and nav.active() is check,(getattr(check,'_navigation',None),nav.history)
            assert rn.state()=='withdrawn' and check.state()=='normal'
            if sys.platform=='win32':
                assert abs(check.winfo_rootx()-rn.winfo_rootx())<=40 and abs(check.winfo_rooty()-rn.winfo_rooty())<=60
            def key(widget,name):
                widget.focus_force();app.update();widget.event_generate('<Alt-KeyPress-'+name+'>');widget.event_generate('<Alt-KeyRelease-'+name+'>');app.update()
            key(check,'Left');assert nav.active() is rn and rn.state()=='normal' and check.state()=='withdrawn'
            assert rn.name_var.get()=='저장 전 RN 이름'
            key(rn.name_entry,'Right');assert nav.active() is check and rn.state()=='withdrawn'
            # Nested pages join the same single history.
            check._navigation_back.invoke();app.update()
            rn.connection_diagram_button.invoke();app.update();app.update()
            diagram=next(w for w in app.winfo_children() if isinstance(w,wf.NodeConnectionDiagramDialog))
            assert diagram._navigation is nav and nav.active() is diagram and rn.state()=='withdrawn'
            # Code that reuses a hidden page by deiconify makes it current.
            rn.deiconify();app.update();app.update()
            assert nav.active() is rn and diagram.state()=='withdrawn',(nav.history,nav.index)
            # Small number prompts stay over the window that asked.
            seen=[]
            def answer():
                prompt=next((w for w in rn.winfo_children() if isinstance(w,code['simpledialog'].Dialog)),None)
                seen.append((prompt is not None,rn.state()))
                if prompt is not None:prompt.cancel()
            app.after(400,answer)
            code['simpledialog'].askinteger('번호','번호를 입력하세요.',parent=rn);app.update()
            assert seen==[(True,'normal')],seen
            assert nav.active() is rn and rn.state()=='normal'
            # Independent drawing windows keep their own window.
            free=tk.Toplevel(app);free._stage_independent=True;free.geometry('300x200');app.update();app.update()
            assert free._navigation is not nav and rn.state()=='normal';free.destroy();app.update()
            # Closing the current page returns to the previous retained page.
            check_page=code['AllCoreDialog'](app,s);app.update();app.update();assert nav.active() is check_page and rn.state()=='withdrawn'
            check_page.tk.eval(check_page.protocol('WM_DELETE_WINDOW'));app.update()
            assert not check_page.winfo_exists() and nav.active() is rn and rn.state()=='normal'
            assert all(w.winfo_exists() for w in nav.history)
            assert wf.plan_snapshot(s.conn)==before and s.history_rows()==history
            assert not errors and not warning.called and not error.called,(errors,warning.call_args,error.call_args)
            print('PASS main drawing pages share one window: RN editor <-> core check <-> diagram, Alt arrows/buttons, drafts, deiconify reuse, prompts, independent windows, close and no writes')
        finally:app.on_close();faulthandler.cancel_dump_traceback_later()


if __name__=='__main__':windows_ui()
