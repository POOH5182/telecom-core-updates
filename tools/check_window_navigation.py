"""Native nested editor navigation, retained drafts, shortcuts and close lifecycle."""
import faulthandler
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from check_after_plan import code,wf


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(100,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp),patch.object(code['messagebox'],'showwarning') as warning,patch.object(code['messagebox'],'showerror') as error,patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'askyesno',return_value=True):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','after')");s.conn.commit()
            a=s.add_node('RN 시작',140,180,node_type='rn');b=s.add_node('RN 끝',600,180,node_type='rn');c=s.add_cable(a,b,'RN 구간','12C','기설')
            s.update_core('PORT:'+a,1,('TEST','보존할 코어','normal','','on'));app.update_title();app.refresh();app.update()
            root=code['open_detail_dialog'](app,s,'node',a);app.update();root.name_var.set('저장 전 RN 이름')
            root.geometry('1000x700+10+20');app.update();before=wf.plan_snapshot(s.conn);history=s.history_rows()
            root.connection_diagram_button.invoke();app.update()
            diagram=next(w for w in app.winfo_children() if isinstance(w,wf.NodeConnectionDiagramDialog))
            nav=root._navigation;assert diagram._navigation is nav and nav.active() is diagram
            assert root.state()=='withdrawn' and diagram.state()=='normal'
            def key(widget,name):
                widget.focus_force();app.update();widget.event_generate('<Alt-KeyPress-'+name+'>');widget.event_generate('<Alt-KeyRelease-'+name+'>');app.update()
            key(diagram.canvas,'Left');assert nav.active() is root and root.state()=='normal' and diagram.state()=='withdrawn'
            assert root.name_var.get()=='저장 전 RN 이름'
            key(root.name_entry,'Right');assert nav.active() is diagram and root.name_var.get()=='저장 전 RN 이름'
            diagram._navigation_back.invoke();app.update();root.rn_identity_button.invoke();app.update();identity=root._rn_identity_dialog
            assert nav.active() is identity and root.state()=='withdrawn'
            identity.focus_core(1);identity.detail.set('작성 중 내역');app.update()
            identity._navigation_back.invoke();app.update();assert root.state()=='normal'
            root._navigation_forward.invoke();app.update();assert identity.detail.get()=='작성 중 내역'
            # A rejected close cannot discard hidden child input.
            identity._navigation_back.invoke();app.update()
            with patch.object(code['messagebox'],'askyesno',return_value=False):root.destroy()
            assert root.winfo_exists() and identity.winfo_exists() and identity.detail.get()=='작성 중 내역'
            root._navigation_forward.invoke();app.update()
            from check_desktop_design import screenshot
            screenshot(identity,Path(temp)/'v138-window-navigation.png')
            assert wf.plan_snapshot(s.conn)==before and s.history_rows()==history
            identity.detail.set(identity.original[1][1]);identity.close();app.update();assert nav.active() is root and root.state()=='normal'
            # Allocation history retains the live source selection and no main-map interception on Back.
            root.rn_identity_button.invoke();app.update();identity=root._rn_identity_dialog;identity.focus_core(1);app.update()
            identity.allocation_button.invoke();app.update();panel=app._map_allocation_panel
            assert panel._navigation is nav and nav.active() is panel
            panel._navigation_back.invoke();app.update();assert nav.active() is identity and app._map_allocation_panel is None
            identity._navigation_forward.invoke();app.update();assert app._map_allocation_panel is panel and panel.state()=='normal'
            panel.close_requested();app.update();assert identity.state()=='normal'
            # Closed pages must not be resurrected; buttons match actual history.
            assert all(w.winfo_exists() for w in nav.history)
            assert not errors and not warning.called and not error.called,(errors,warning.call_args,error.call_args)
            print('PASS Windows RN editor -> diagram -> ID editor -> allocation, single visible history, native Alt arrows/buttons, unsaved drafts, close cancel, source routing and no writes')
        finally:app.on_close();faulthandler.cancel_dump_traceback_later()


if __name__=='__main__':windows_ui()
