"""V136: start main-map core allocation straight from the incomplete-core list."""
import faulthandler
import os
import sys
import tempfile
from unittest.mock import patch

from check_after_plan import code,wf
from check_after_routes import drawing
from check_manual_allocation import clear_old_connector


def windows_ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):
        print('Incomplete-list map allocation gate runs on Windows.');return
    faulthandler.dump_traceback_later(100,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showerror') as error,patch.object(code['messagebox'],'showwarning') as warning, \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'askyesno',return_value=True):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            app.geometry('1450x950+0+0');s=app.store
            s.conn.execute("INSERT INTO meta VALUES('active_scenario','after') ON CONFLICT(key) DO UPDATE SET value='after'");s.conn.commit()
            i=drawing(app);clear_old_connector(app,i);app.refresh();app.update()
            original=wf.plan_snapshot(s.conn);history=s.history_rows()
            dialog=code['IncompleteCoresDialog'](app,s);app.update()
            # Nothing selected: explain, never open a panel.
            dialog.tree.selection_remove(*dialog.tree.selection());app.update()
            dialog.map_allocation_button.invoke();app.update()
            assert warning.called and not getattr(app,'_map_allocation_panel',None);warning.reset_mock()
            iid=next(k for k,e in enumerate(dialog.entries) if e['core_id']=='CORE-1');iid=str(iid)
            dialog.tree.selection_set(iid);dialog.tree.focus(iid);app.update()
            assert app.highlight_owner is dialog,'clicking the core still shows its incomplete route'
            assert (i['left'],1) in dialog.allocation_sources(),dialog.allocation_sources()
            dialog.map_allocation_button.invoke();app.update()
            panel=app._map_allocation_panel
            assert isinstance(panel,wf.MapCoreAllocationPanel),panel
            assert panel.service.core_id=='CORE-1' and panel.service.source==(i['left'],1)
            assert dialog.state()=='withdrawn' and app.highlight_owner is panel
            # Pressing again on the same core reuses the open panel.
            dialog.deiconify();dialog.map_allocation_button.invoke();app.update()
            assert app._map_allocation_panel is panel and dialog.state()=='withdrawn'
            # Returning brings the reloaded list back with the same core selected.
            panel.close_requested();app.update()
            assert app._map_allocation_panel is None and dialog.state()=='normal'
            assert dialog.entries[int(dialog.tree.selection()[0])]['core_id']=='CORE-1'
            assert wf.plan_snapshot(s.conn)==original and s.history_rows()==history
            # Not available outside the after drawing.
            with patch.object(app,'scenario_kind',return_value='before'):
                dialog.map_allocation_button.invoke();app.update()
            assert warning.called and '후도면' in str(warning.call_args) and not getattr(app,'_map_allocation_panel',None)
            dialog.destroy();app.update()
            assert not errors,errors;assert not error.called,error.call_args_list
        finally:app.on_close();faulthandler.cancel_dump_traceback_later()
    print('PASS incomplete list: core click route, map allocation button, panel reuse, return to reloaded list and after-only guard')


if __name__=='__main__':windows_ui()
