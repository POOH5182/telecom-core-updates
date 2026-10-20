"""V148: the title-bar X / Ctrl+W closes the whole window with every stacked page."""
import faulthandler
import os
import sys
import tempfile
from unittest.mock import patch
from check_after_plan import code,wf


def windows_ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    faulthandler.dump_traceback_later(100,exit=True)
    messagebox=code['messagebox']
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp),patch.object(messagebox,'showwarning') as warning,patch.object(messagebox,'showerror') as error,patch.object(messagebox,'showinfo'):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','after')");s.conn.commit()
            h=s.add_node('함체 A',140,180);r=s.add_node('RN 끝',600,180,node_type='rn');s.add_cable(h,r,'구간','12C','기설')
            s.update_core('PORT:'+r,1,('TEST','보존할 코어','normal','','on'))
            app.update_title();app.refresh();app.update()
            before=wf.plan_snapshot(s.conn);history=s.history_rows()
            def stack(node):
                root=code['open_detail_dialog'](app,s,'node',node);app.update();app.update()
                # V149: the diagram replaces the editor; both are never shown at once.
                maps=[]
                def mapped(event):
                    if isinstance(event.widget,wf.NodeConnectionDiagramDialog):maps.append(root.state())
                old=app.bind_class('Toplevel','<Map>');app.bind_class('Toplevel','<Map>',mapped,add='+')
                root.connection_diagram_button.invoke();app.update();app.update()
                app.bind_class('Toplevel','<Map>',old)
                assert maps and all(state=='withdrawn' for state in maps),maps
                diagram=next(w for w in app.winfo_children() if isinstance(w,wf.NodeConnectionDiagramDialog) and w.winfo_exists())
                assert diagram._navigation is root._navigation and root._navigation.active() is diagram and root.state()=='withdrawn'
                return root,diagram
            def x(window):window.tk.eval(window.protocol('WM_DELETE_WINDOW'));app.update();app.update()
            # 1. Enclosure -> connection diagram, X closes both without questions.
            root,diagram=stack(h)
            shown=[];root.bind('<Map>',lambda e:shown.append(e.widget) if e.widget is root else None,add='+')
            with patch.object(messagebox,'askyesno') as ask,patch.object(messagebox,'askyesnocancel') as ask3:
                x(diagram)
            assert not diagram.winfo_exists() and not root.winfo_exists() and not ask.called and not ask3.called
            assert not shown,'X must not flash the hidden enclosure editor'
            # 2. Unsaved enclosure name: one question; No keeps everything.
            root,diagram=stack(h);root.name_var.set('저장 전 이름');app.update()
            root._navigation.move(1);app.update()
            with patch.object(messagebox,'askyesno',return_value=False) as ask:x(diagram)
            assert ask.call_count==1 and ask.call_args[0][0]=='창 닫기' and '저장하지 않은 입력' in ask.call_args[0][1]
            assert diagram.winfo_exists() and root.winfo_exists() and root.name_var.get()=='저장 전 이름'
            assert root._navigation.active() is diagram and diagram.state()=='normal'
            # Back/Alt+Left still goes to the previous page.
            diagram._navigation_back.invoke();app.update();assert root.state()=='normal' and diagram.state()=='withdrawn'
            diagram._navigation.move(1);app.update()
            # Yes discards and closes the whole window; nothing is written.
            with patch.object(messagebox,'askyesno',return_value=True) as ask,patch.object(messagebox,'askyesnocancel') as ask3:x(diagram)
            assert ask.call_count==1 and not ask3.called
            assert not diagram.winfo_exists() and not root.winfo_exists() and s.node(h)['name']=='함체 A'
            # 3. Ctrl+W behaves as the window X.
            root,diagram=stack(r)
            diagram.canvas.focus_force();app.update()
            diagram.canvas.event_generate('<Control-KeyPress-w>');diagram.canvas.event_generate('<Control-KeyRelease-w>');app.update();app.update()
            assert not diagram.winfo_exists() and not root.winfo_exists()
            # 4. RN editor -> ID editor draft: one question covers both pages.
            root=code['open_detail_dialog'](app,s,'node',r);app.update();app.update()
            root.rn_identity_button.invoke();app.update();identity=root._rn_identity_dialog
            identity.focus_core(1);identity.detail.set('작성 중 내역');app.update()
            with patch.object(messagebox,'askyesno',return_value=True) as ask,patch.object(messagebox,'askyesnocancel') as ask3:x(identity)
            assert ask.call_count==1 and not ask3.called,(ask.call_args_list,)
            assert not identity.winfo_exists() and not root.winfo_exists()
            # 5. Main-menu pages are the same window too.
            root=code['open_detail_dialog'](app,s,'node',r);app.update();app.update()
            check=code['CoreCheckDialog'](app,s);app.update();app.update()
            assert check._navigation is root._navigation and root.state()=='withdrawn'
            with patch.object(messagebox,'askyesno') as ask:x(check)
            assert not check.winfo_exists() and not root.winfo_exists() and not ask.called
            # A page's own close button still returns to the previous page.
            root=code['open_detail_dialog'](app,s,'node',r);app.update();app.update()
            check=code['CoreCheckDialog'](app,s);app.update();app.update()
            check.destroy();app.update();assert root.state()=='normal' and root._navigation.active() is root
            root.destroy();app.update()
            assert wf.plan_snapshot(s.conn)==before and s.history_rows()==history
            assert not errors and not warning.called and not error.called,(errors,warning.call_args,error.call_args)
            print('PASS Windows X/Ctrl+W close the whole stacked window: enclosure->diagram, one unsaved question (no keeps, yes discards), RN ID draft, main-menu pages, Back kept, page close returns, no writes')
        finally:app.on_close();faulthandler.cancel_dump_traceback_later()


if __name__=='__main__':
    try:windows_ui()
    except BaseException:
        import traceback
        print('::error::'+traceback.format_exc().strip()[-3000:].replace('\n','%0A'),flush=True);raise
