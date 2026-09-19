"""Regression for an uninitialized Tk widget returned by a blocked workbench."""
import faulthandler
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import code,wf,update
from legacy_field_fixture import existing_field


class EntryTests(unittest.TestCase):
    def test_blocked_stages_return_safely_through_real_tcl_callback(self):
        for stage in ('gis','before'):
            with self.subTest(stage=stage):
                app=type('Stage',(),{'scenario_kind':lambda self:stage})()
                tcl=wf.tk.Tcl()
                with patch.object(wf.messagebox,'showinfo') as info, \
                     patch.object(wf.RememberedToplevel,'__init__') as create:
                    self.assertIsNone(wf.AfterPlanDialog(app))
                    tcl.tk.createcommand('open_workbench',lambda:wf.AfterPlanDialog(app))
                    try:
                        # The old return value raises AttributeError on _w at
                        # the Python-to-Tcl boundary, outside the constructor.
                        tcl.tk.call('open_workbench')
                        self.assertEqual(tcl.eval('expr {6 * 7}'),'42')
                    finally:tcl.tk.deletecommand('open_workbench')
                    self.assertEqual(info.call_count,2)
                    self.assertIs(info.call_args.kwargs['parent'],app)
                    self.assertIn('4 후도면',info.call_args.args[1])
                    create.assert_not_called()


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(120,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(wf.messagebox,'showinfo') as info, \
         patch.object(wf.messagebox,'showwarning'),patch.object(wf.messagebox,'showerror') as error, \
         patch.object(wf.messagebox,'askyesno',return_value=True), \
         patch.object(wf.messagebox,'askyesnocancel',return_value=True):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;a=s.add_node('SYNTH-A',0,0);h=s.add_node('SYNTH-H',200,0);b=s.add_node('SYNTH-B',400,0)
            first=s.add_cable(a,h,'SYNTH-LEFT','12C','기설');second=s.add_cable(h,b,'SYNTH-RIGHT','12C','기설')
            update(s,first,1,{'core_id':'SYNTH-ID','detail':'Synthetic service'})
            s.connect(h,(first,1),(second,2));existing_field(app);assert app.load_scenario('before')
            s=app.store
            wf.FieldSurvey(s,a).save('SYNTH-LEFT\n1')
            wf.FieldSurvey(s,h).save('SYNTH-LEFT\tSYNTH-RIGHT\n1\t2')
            wf.FieldSurvey(s,b).save('SYNTH-RIGHT\n2');app.save_current_drawing(silent=True)
            assert not app.scenario_path('after').exists()
            config=dict(app.drawing_tools.config,enabled=app.drawing_tools.config['enabled']+['after_plan'])
            app.drawing_tools.apply(config)
            if not app.advanced_tools_visible:app.toggle_advanced_tools()
            app.refresh();app.update()
            editor=code['CableDialog'](app,s,first);app.update();editor.lot_var.set('Unsaved LOT draft')
            app.selected={a};app.set_mode('hamche')
            def snapshot():
                return (wf.plan_snapshot(app.store.conn),wf.state(app.store),app.store.history_rows(),
                        app.store.data_revision(),app.scenario_kind(),app.mode,set(app.selected),app.view_scale,
                        {p.name:p.read_bytes() for p in app.scenario_folder().glob('*.sqlite3')})
            controls=[app.workflow_buttons['complete'],app.drawing_tools.buttons['after_plan']]
            pending=list(app.advanced_tools_frame.winfo_children())
            while pending:
                widget=pending.pop();pending.extend(widget.winfo_children())
                if isinstance(widget,(wf.ttk.Button,wf.tk.Button)) and widget.cget('text')=='후도면 작업실':controls.append(widget)
            assert len(controls)==3,len(controls)
            baseline=snapshot();children=set(app.winfo_children());previous_grab=app.grab_current()
            print('ENTRY: field-only drawing, all three real buttons and repeated Tk mainloop callbacks',flush=True)
            for button in controls*2:
                count=info.call_count
                app.after(0,button.invoke);app.after(50,app.quit);app.mainloop();app.update()
                assert info.call_count==count+1
                assert snapshot()==baseline
                assert set(app.winfo_children())==children and app.grab_current() is previous_grab
                assert editor.lot_var.get()=='Unsaved LOT draft'
                assert not app.scenario_path('after').exists() and app.winfo_exists()
            assert not errors,errors
            editor.destroy()
            print('ENTRY: explicit after creation, normal workbench and saved-after/current-field guard',flush=True)
            app.workflow_buttons['after'].invoke();app.update();assert app.scenario_kind()=='after'
            app.workflow_buttons['complete'].invoke();app.update()
            dialogs=[w for w in app.winfo_children() if isinstance(w,wf.AfterPlanDialog)]
            assert len(dialogs)==1 and dialogs[0].tables and dialogs[0].tabs.tabs()
            dialogs[0].destroy();app.update();assert app.load_scenario('before');app.update()
            baseline=snapshot();count=info.call_count
            app.workflow_buttons['complete'].invoke();app.update()
            assert info.call_count==count+1 and snapshot()==baseline and app.scenario_path('after').exists()
            assert not errors,errors;assert not error.called,error.call_args
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows field-only workbench entry: all buttons, repeated mainloops, no phantom window, data/drafts preserved, explicit after creation and normal opening')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EntryTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
