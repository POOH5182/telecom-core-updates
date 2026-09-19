"""Stage deletion: real databases, backups, stale guards, rollback and Windows UI."""
import faulthandler
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from check_after_plan import code,wf,update


class Drawing:
    def __init__(self,home):
        self.home=Path(home);self.store=code['Store'](self.home/'drawing.sqlite3')
    def scenario_folder(self):
        p=self.home/'scenarios'/self.store.path.stem;p.mkdir(parents=True,exist_ok=True);return p
    def scenario_path(self,kind):return self.scenario_folder()/(kind+'.sqlite3')
    def scenario_kind(self):
        row=self.store.conn.execute("SELECT value FROM meta WHERE key='active_scenario'").fetchone()
        return row[0] if row else 'gis'


def stage(app,kind):
    app.store.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario',?)",(kind,));app.store.conn.commit()


def fixture(app):
    s=app.store;a=s.add_node('SYNTH-A',0,0);h=s.add_node('SYNTH-H',200,0);b=s.add_node('SYNTH-B',400,0)
    left=s.add_cable(a,h,'SYNTH-LEFT','12C','기설');right=s.add_cable(h,b,'SYNTH-RIGHT','12C','기설')
    update(s,left,1,{'core_id':'SYNTH-ID','detail':'Synthetic service','signal':'on'})
    s.connect(h,(left,1),(right,2))
    for kind in wf.STAGE_ORDER:
        stage(app,kind);update(s,left,1,{'core_id':'SYNTH-ID','detail':'Saved '+kind,'signal':'on'})
        s.backup_to(app.scenario_path(kind))
    update(s,left,1,{'detail':'Unsaved active after'})
    return a,h,b,left,right


class StageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=Drawing(self.temp.name)
        self.a,self.h,self.b,self.left,self.right=fixture(self.app)
    def tearDown(self):self.app.store.close();self.temp.cleanup()
    def token(self):return wf.stage_state_token(self.app)
    def delete(self):return wf.stage_delete_commit(self.app,wf.stage_delete_preview(self.app))
    def restore(self):return wf.stage_restore_commit(self.app,wf.stage_restore_preview(self.app))
    def activate(self,kind):wf.stage_restore_store(self.app.store,self.app.scenario_path(kind))

    def test_after_delete_loads_saved_field_preserves_other_stages_and_restores_drafts_history(self):
        before=self.token();history=self.app.store.history_rows();revision=self.app.store.data_revision();folder=self.delete()
        self.assertEqual(self.app.scenario_kind(),'before');self.assertFalse(self.app.scenario_path('after').exists())
        self.assertEqual(self.app.store.core(self.left,1)['detail'],'Saved before')
        self.assertGreater(self.app.store.data_revision(),revision)
        for kind in ('gis','before'):self.assertEqual(self.token()['snapshots'][kind],before['snapshots'][kind])
        self.assertTrue((folder/'working.sqlite3').exists())
        with zipfile.ZipFile(io.BytesIO(wf.cloud_bundle(self.app.store,self.app.scenario_folder()))) as archive:
            self.assertEqual(set(archive.namelist()),{'working.sqlite3','gis.sqlite3','before.sqlite3'})
        self.restore();self.assertEqual(self.token(),before);self.assertEqual(self.app.store.history_rows(),history)
        self.assertEqual(self.app.store.core(self.left,1)['detail'],'Unsaved active after')

    def test_field_delete_returns_gis_retains_after_and_undo_survives_reopen(self):
        self.activate('before');before=self.token();self.delete()
        self.assertEqual(self.app.scenario_kind(),'gis');self.assertEqual(self.app.store.core(self.left,1)['detail'],'Saved gis')
        self.assertFalse(self.app.scenario_path('before').exists());self.assertEqual(self.token()['snapshots']['after'],before['snapshots']['after'])
        path=self.app.store.path;self.app.store.close();self.app.store=code['Store'](path)
        self.restore();self.assertEqual(self.token(),before)

    def test_gis_delete_returns_blank_and_preserves_field_after(self):
        self.activate('gis');before=self.token();self.delete()
        self.assertEqual(self.app.scenario_kind(),'gis');self.assertFalse(self.app.scenario_path('gis').exists())
        for table in ('nodes','cables','cores','splices'):
            self.assertEqual(self.app.store.conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(self.app.store.history_rows(),[])
        for kind in ('before','after'):self.assertEqual(self.token()['snapshots'][kind],before['snapshots'][kind])
        self.restore();self.assertEqual(self.token(),before)

    def test_unsaved_stage_without_own_snapshot_is_backed_up_and_restored(self):
        self.app.scenario_path('after').unlink();before=self.token();self.delete();self.restore();self.assertEqual(self.token(),before)

    def test_missing_or_invalid_previous_refuses_without_change(self):
        path=self.app.scenario_path('before');original=path.read_bytes();path.unlink();before=self.token()
        with self.assertRaisesRegex(ValueError,'저장본'):self.delete()
        self.assertEqual(self.token(),before);path.write_bytes(b'not a drawing');before=self.token()
        with self.assertRaises(sqlite3.Error):self.delete()
        self.assertEqual(self.token(),before);path.write_bytes(original)

    def test_stale_review_and_postdelete_edits_refuse(self):
        preview=wf.stage_delete_preview(self.app);update(self.app.store,self.left,1,{'detail':'New edit'});before=self.token()
        with self.assertRaisesRegex(ValueError,'바뀌'):wf.stage_delete_commit(self.app,preview)
        self.assertEqual(self.token(),before);self.delete();update(self.app.store,self.left,1,{'detail':'Keep new field edit'});before=self.token()
        with self.assertRaisesRegex(ValueError,'변경'):self.restore()
        self.assertEqual(self.token(),before)

    def test_busy_and_current_locks_refuse_but_unchanged_locked_destination_can_be_undone(self):
        before=self.token();self.app.cloud=type('Cloud',(),{'jobs':type('Jobs',(),{'busy':True})()})()
        with self.assertRaisesRegex(ValueError,'동기화'):self.delete()
        self.assertEqual(self.token(),before);self.app.cloud=None
        with patch.object(wf,'any_node_locked',return_value=True):
            with self.assertRaisesRegex(ValueError,'잠금'):self.delete()
        self.assertEqual(self.token(),before)
        field=code['Store'](self.app.scenario_path('before'))
        try:
            settings=wf.state(field);settings['options']['before_locked']=True;wf.write_state(field,settings)
        finally:field.close()
        before=self.token();self.delete();self.assertTrue(wf.locked(self.app.store))
        self.restore();self.assertEqual(self.token(),before)

    def test_delete_failure_rolls_back_working_snapshots_and_previous_undo_record(self):
        self.delete();self.restore();marker=wf.stage_recovery_marker(self.app);marker.write_text('previous marker',encoding='utf-8')
        before=self.token();original=wf.stage_write_json
        def fail(path,value):
            if path==marker:raise OSError('Synthetic marker write failure')
            return original(path,value)
        with patch.object(wf,'stage_write_json',side_effect=fail):
            with self.assertRaisesRegex(OSError,'Synthetic'):self.delete()
        self.assertEqual(self.token(),before);self.assertEqual(marker.read_text(encoding='utf-8'),'previous marker')

    def test_restore_failure_preserves_postdelete_state_and_retry(self):
        before=self.token();self.delete();post=self.token();original=wf.stage_restore_store;calls=[]
        def fail(store,path):
            calls.append(path)
            if len(calls)==1:raise OSError('Synthetic restore failure')
            return original(store,path)
        with patch.object(wf,'stage_restore_store',side_effect=fail):
            with self.assertRaisesRegex(OSError,'Synthetic'):self.restore()
        self.assertEqual(self.token(),post);self.restore();self.assertEqual(self.token(),before)

    def test_changed_backup_refuses_without_change(self):
        folder=self.delete();before=self.token();(folder/'working.sqlite3').write_bytes(b'changed backup')
        with self.assertRaisesRegex(ValueError,'백업 파일'):self.restore()
        self.assertEqual(self.token(),before)


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(150,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(wf.messagebox,'showinfo') as info,patch.object(wf.messagebox,'showwarning'), \
         patch.object(wf.messagebox,'showerror') as error,patch.object(wf.messagebox,'askyesno',return_value=True), \
         patch.object(wf.messagebox,'askyesnocancel',return_value=True) as save_question:
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            a,h,b,left,right=fixture(app);app.refresh();app.update()
            app.geometry('1024x720');app.update();before=wf.stage_state_token(app)
            saved_revision=app.scenario_saved_revision;assert app.scenario_dirty()
            # Cancellation leaves all database/history/snapshot state unchanged.
            dialog=wf.open_stage_delete(app);app.update();assert dialog and dialog.winfo_exists()
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True)
                screenshot(dialog,Path('dist')/'v117-stage-delete.png')
            assert dialog.apply_button.winfo_y()+dialog.apply_button.winfo_height()<=dialog.apply_button.master.winfo_height()
            dialog.cancel_button.invoke();app.update();assert wf.stage_state_token(app)==before
            # Drafts in an open real cable editor cannot be discarded by deletion.
            editor=code['CableDialog'](app,app.store,left);app.update();editor.lot_var.set('Unsaved LOT draft')
            assert wf.open_stage_delete(app) is None and editor.lot_var.get()=='Unsaved LOT draft'
            assert wf.stage_state_token(app)==before;editor.destroy();app.update()
            # Exercise toolbar commands and the nested management window, including its wait_window.
            config=dict(app.drawing_tools.config,enabled=app.drawing_tools.config['enabled']+['stage_delete','stage_restore'])
            app.drawing_tools.apply(config);app.update()
            app.drawing_tools.buttons['stage_delete'].invoke();app.update()
            dialog=next(w for w in app.winfo_children() if isinstance(w,wf.StageDeleteDialog))
            dialog.apply_button.invoke();app.update();assert app.scenario_kind()=='before'
            assert not app.scenario_path('after').exists();assert app.mode=='select'
            app.drawing_tools.buttons['stage_restore'].invoke();app.update();assert wf.stage_state_token(app)==before
            assert app.scenario_dirty() and app.scenario_saved_revision==saved_revision
            save_question.return_value=None;question_count=save_question.call_count
            assert not app.load_scenario('gis') and save_question.call_count==question_count+1
            assert wf.stage_state_token(app)==before;save_question.return_value=True
            # Ensure refresh did not rewrite state and invalidate the local undo record.
            for kind,previous in (('before','gis'),('gis','gis')):
                wf.stage_restore_store(app.store,app.scenario_path(kind));app.refresh();app.update();baseline=wf.stage_state_token(app)
                manager=code['ScenarioDialog'](app);app.update()
                def apply_nested():
                    nested=[w for w in manager.winfo_children() if isinstance(w,wf.StageDeleteDialog)]
                    assert len(nested)==1;nested[0].apply_button.invoke()
                app.after(100,apply_nested);manager.clear();app.update()
                assert app.scenario_kind()==previous and not app.scenario_path(kind).exists()
                if kind=='gis':
                    empty_state=wf.stage_state_token(app)
                    assert not app.load_scenario('gis') and wf.stage_state_token(app)==empty_state
                manager.restore_deleted();app.update();assert wf.stage_state_token(app)==baseline
                manager.destroy();app.update()
            assert not errors,errors;assert not error.called,error.call_args
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows stage deletion: all three stages, cancel, actual toolbar/management buttons, backup/undo, unsaved editor protection, state preserved after refresh')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StageTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
