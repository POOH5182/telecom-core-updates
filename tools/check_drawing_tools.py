"""Custom toolbar persistence and actual Windows check/reorder/action controls."""
import copy
import faulthandler
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_field_survey import code,wf


class DrawingToolSettingsTests(unittest.TestCase):
    def setUp(self):
        self.catalog=[dict(id='select',default=True),dict(id='create',default=True),dict(id='work'),dict(id='find')]

    def test_defaults_and_explicit_empty_selection_are_distinct(self):
        self.assertEqual(wf.drawing_tools_config(self.catalog)['enabled'],['select','create'])
        empty=wf.drawing_tools_config(self.catalog,dict(order=[],enabled=[]))
        self.assertEqual(empty['enabled'],[]);self.assertEqual(empty['order'],['select','create','work','find'])

    def test_invalid_unknown_duplicate_values_are_safe_and_order_is_preserved(self):
        value=dict(order=['work','work',None,{},'gone','select'],enabled=['work','work',{},'gone'])
        actual=wf.drawing_tools_config(self.catalog,value)
        self.assertEqual(actual['order'],['work','select','create','find']);self.assertEqual(actual['enabled'],['work'])
        for malformed in (None,[],{'order':None},{'order':[],'enabled':'work'}):
            self.assertEqual(wf.drawing_tools_config(self.catalog,malformed)['enabled'],['select','create'])

    def test_atomic_save_reopen_and_failure_leave_previous_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'data'/'drawing_tools.json'
            chosen=dict(order=['work','find','select','create'],enabled=['work','find'])
            saved=wf.save_drawing_tools(path,self.catalog,chosen)
            self.assertEqual(wf.read_drawing_tools(path,self.catalog),saved)
            original=path.read_bytes()
            with patch.object(wf.os,'replace',side_effect=OSError('Synthetic disk failure')),self.assertRaises(OSError):
                wf.save_drawing_tools(path,self.catalog,dict(order=[],enabled=[]))
            self.assertEqual(path.read_bytes(),original);self.assertFalse(list(path.parent.glob('*.tmp')))

    def test_invalid_file_reads_do_not_write_or_replace_user_preferences(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'drawing_tools.json';path.write_text('{invalid',encoding='utf-8')
            self.assertEqual(wf.read_drawing_tools(path,self.catalog)['enabled'],['select','create'])
            self.assertEqual(path.read_text(),'{invalid')


def check_right_edge(app):
    for _ in range(3):app.update()
    tools=app.drawing_tools;gear=tools.edit_button
    assert gear.winfo_ismapped() and gear.cget('image')
    assert abs(app.winfo_rootx()+app.winfo_width()-(gear.winfo_rootx()+gear.winfo_width())-12)<=2
    assert gear.winfo_rooty()==app.drawing_toolbar_frame.winfo_rooty()+5
    for widget in app.drawing_toolbar.controls:
        assert widget.winfo_ismapped()
        assert widget.winfo_rootx()+widget.winfo_width()<=gear.winfo_rootx()
        assert widget.winfo_y()+widget.winfo_height()<=app.drawing_toolbar.winfo_height()


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(120,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showwarning'), \
         patch.object(code['messagebox'],'showerror') as error:
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            print('TOOLS: right-edge gear and editor draft',flush=True)
            s=app.store;a=s.add_node('Synthetic A',100,100);b=s.add_node('Synthetic B',400,100)
            cable=s.add_cable(a,b,'SYNTH-CABLE','12C','기설');app.refresh();app.update()
            tools=app.drawing_tools;assert len(tools.config['enabled'])==10
            assert len(tools.by_id)==len(tools.catalog) and len(tools.by_id)>35
            for width in (1450,1000):app.geometry(f'{width}x700+0+0');check_right_edge(app)
            app.geometry('1450x900+0+0');app.update()
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True);screenshot(app,Path('dist')/'v111-toolbar-gear.png')
            baseline=(wf.plan_snapshot(s.conn),s.history_rows(),s.data_revision())
            draft=code['CableDialog'](app,s,cable);app.update();draft.id_var.set('Unsaved cable name');draft.lot_var.set('Unsaved LOT')
            app.set_mode('hamche');app.selected={a};mode=app.mode;view=app.view_scale
            tools.edit_button.invoke();app.update();editor=tools.dialog
            tools.edit_button.invoke();assert tools.dialog is editor
            editor.checks['core_worklist'].invoke();editor.top_button.invoke()
            assert editor.order[0]=='core_worklist'
            editor.checks['mode_rn'].invoke();editor.cancel();app.update()
            assert len(tools.buttons)==10 and not tools.path.exists() and app.mode==mode

            tools.edit_button.invoke();app.update();editor=tools.dialog
            editor.set_all(False)
            for key in ('mode_select','mode_hamche','core_worklist','core_errors','all_tools','files'):
                editor.checks[key].invoke()
            editor.select('core_worklist');editor.top_button.invoke()
            editor.down_button.invoke();assert editor.order[1]=='core_worklist'
            editor.up_button.invoke();assert editor.order[0]=='core_worklist'
            if '--emit-screenshots' in sys.argv:screenshot(editor,Path('dist')/'v111-tool-editor.png')
            editor.apply_button.invoke();app.update()
            print('TOOLS: saved order, live buttons and cable drafts',flush=True)
            selected_config=copy.deepcopy(tools.config);saved=tools.path.read_bytes()
            assert list(tools.buttons)==['core_worklist','mode_select','mode_hamche','files','all_tools','core_errors']
            assert 'mode_rn' not in tools.buttons and app.mode_buttons['hamche'].cget('style')=='Active.Tool.TButton'
            assert app.mode==mode and app.selected=={a} and app.view_scale==view
            assert draft.id_var.get()=='Unsaved cable name' and draft.lot_var.get()=='Unsaved LOT'
            assert (wf.plan_snapshot(s.conn),s.history_rows(),s.data_revision())==baseline
            tools.buttons['mode_select'].invoke();assert app.mode=='select'
            tools.buttons['all_tools'].invoke();app.update();assert app.advanced_tools_visible and '접기' in tools.buttons['all_tools'].cget('text')
            app.tools_toggle_button.invoke();app.update();assert not app.advanced_tools_visible and '펼치기' in tools.buttons['all_tools'].cget('text')
            with patch.object(app,'error_core_count',return_value=3):app.refresh_error_core_button()
            assert '(3개)' in tools.buttons['core_errors'].cget('text') and tools.buttons['core_errors'].cget('bg')=='#d32f2f'
            app.refresh_error_core_button()
            # Native Windows popup menus run a nested input loop. Assert the
            # real toolbar callback's anchor/menu without waiting for a person.
            with patch.object(wf,'desktop_popup_menu') as popup:
                tools.buttons['files'].invoke();popup.assert_called_once_with(tools.buttons['files'],app.file_menu)
            tools.buttons['core_worklist'].invoke();app.update()
            opened=[w for w in app.winfo_children() if isinstance(w,code['CoreCheckDialog'])]
            assert len(opened)==1;opened[0].destroy()

            print('TOOLS: cancellation, disk failure and all/empty layouts',flush=True)
            tools.edit_button.invoke();app.update();editor=tools.dialog;editor.reset_button.invoke();editor.cancel()
            assert tools.config==selected_config and tools.path.read_bytes()==saved
            tools.edit_button.invoke();app.update();editor=tools.dialog;editor.set_all(False)
            with patch.object(wf,'save_drawing_tools',side_effect=OSError('Synthetic disk full')):editor.apply_button.invoke()
            assert editor.winfo_exists() and tools.config==selected_config and tools.path.read_bytes()==saved and error.called
            error.reset_mock();editor.cancel()

            tools.edit_button.invoke();app.update();editor=tools.dialog;editor.set_all(True);editor.apply_button.invoke()
            assert len(tools.buttons)==len(tools.catalog)
            for width in (1450,1000):app.geometry(f'{width}x700+0+0');check_right_edge(app);assert app.canvas.winfo_height()>100
            tools.edit_button.invoke();app.update();editor=tools.dialog;editor.set_all(False);editor.apply_button.invoke()
            check_right_edge(app);assert not tools.buttons and not app.drawing_toolbar.controls
            tools.edit_button.invoke();app.update();editor=tools.dialog;editor.reset_button.invoke();editor.apply_button.invoke()
            assert len(tools.buttons)==10
            tools.apply(selected_config);app.update();check_right_edge(app)
            assert (wf.plan_snapshot(s.conn),s.history_rows(),s.data_revision())==baseline
            assert draft.id_var.get()=='Unsaved cable name';draft.destroy()
            assert not errors and not error.called,(errors,error.call_args)
        finally:app.on_close()
        # A real second App instance reads the persisted ordering and selection.
        print('TOOLS: restart and project switch',flush=True)
        app=code['App']();app.report_callback_exception=lambda *args:errors.append(args)
        try:
            app.update();assert app.drawing_tools.config==selected_config;check_right_edge(app)
            assert app.store.cable(cable)['cable_id']=='SYNTH-CABLE'
            other=Path(temp)/'other.sqlite3';code['Store'](other).close();app.switch_project(other);app.update()
            assert app.drawing_tools.config==selected_config;check_right_edge(app)
            assert not errors and not error.called,(errors,error.call_args)
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows right-edge gear, checkbox/order/apply/cancel/reset, narrow/all/empty layouts, live actions, draft/data preservation, atomic failure and restart/project persistence')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DrawingToolSettingsTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
