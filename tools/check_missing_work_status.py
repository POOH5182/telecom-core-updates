"""Missing after allocations retain explicit broken/exception/cancel reasons."""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_work_classification import WorkApp,code,wf,fixture,phase
from check_field_work_endpoints import fixture as temporary_fixture


class MissingStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=WorkApp(self.temp.name);self.s=self.app.store
        self.nodes,self.cables=fixture(self.s)
        with self.s.action('합성 현장 작업'):self.s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(self.cables[1],))
    def tearDown(self):self.s.close();self.temp.cleanup()
    def baseline(self):
        self.s.backup_to(self.app.scenario_path('before'));self.before=self.app.scenario_path('before').read_bytes();phase(self.s,'after')
    def mark(self,labels):wf.save_annotations(self.s,(self.cables[0],1),labels,'합성 처리 사유')
    def remove(self):
        with self.s.action('합성 코어 배정 삭제'):
            for cable,index in zip(self.cables,(1,2,3)):self.s.delete_core_assignment(cable,index)
    def row(self):return self.app.work_report()['rows'][0]
    def assert_handled(self,label):
        row=self.row();self.assertEqual(row['result'],label);self.assertFalse(row['missing']);self.assertFalse(row['error'])
        self.assertTrue(row['handled_missing']);self.assertIn(label,row['note'])
        self.assertEqual(row['complete'],label=='예외 처리');self.assertEqual(row['excluded'],label!='예외 처리')
        report=self.app.work_report();self.assertEqual(report['pending'],0)
        self.assertEqual((report['total'],report['done']),(1,1) if label=='예외 처리' else (0,0))
        self.assertEqual(self.app.scenario_path('before').read_bytes(),self.before)

    def test_after_status_survives_last_allocation_and_annotation_deletion(self):
        self.baseline()
        for labels,result in ((['끊김'],'끊김'),(['예외코어'],'예외 처리'),(['해지'],'해지')):
            with self.subTest(result=result):
                self.mark(labels);self.remove();self.assert_handled(result)
                self.assertIsNone(self.s.conn.execute("SELECT 1 FROM core_annotations WHERE core_id='SYNTH-WORK'").fetchone())
                snapshot=wf.plan_snapshot(self.s.conn);history=self.s.history_rows();ledger=wf.work_removed_status_ledger(self.s)
                self.assert_handled(result)
                self.assertEqual(wf.plan_snapshot(self.s.conn),snapshot);self.assertEqual(self.s.history_rows(),history)
                self.assertEqual(wf.work_removed_status_ledger(self.s),ledger)
                self.s.undo();self.s.undo()

    def test_field_disposition_is_available_without_after_deletion_history(self):
        self.mark(['해지']);self.baseline()
        with self.s.no_history():
            self.s.conn.execute('DELETE FROM splices');self.s.conn.execute("UPDATE cores SET core_id='',detail='',status1='',status2='',signal=''")
            self.s.conn.execute('DELETE FROM core_annotations')
        self.assert_handled('해지');self.assertIn('현장반영 도면 상태',self.row()['note'])

    def test_old_drawing_recovers_last_deletion_without_writing_a_migration(self):
        self.baseline();self.mark(['예외코어'])
        with patch.object(wf,'preserve_removed_work_status'):self.remove()
        self.assertEqual(wf.work_removed_status_ledger(self.s),{})
        self.assert_handled('예외 처리');self.assertIn('삭제 직전 기록',self.row()['note'])
        self.assertEqual(wf.work_removed_status_ledger(self.s),{})

    def test_durable_reason_survives_history_pruning_and_reopen(self):
        self.baseline();self.mark(['끊김']);self.remove()
        for i in range(105):
            with self.s.action('합성 위치 수정'):self.s.conn.execute('UPDATE nodes SET x=x+1 WHERE id=?',(self.nodes[0],))
        self.assertEqual(wf.work_removed_status_history(self.s),{})
        self.s.close();self.s=code['Store'](self.app.home/'working.sqlite3');self.app.store=self.s
        self.assert_handled('끊김')

    def test_explicit_status_clear_does_not_revive_field_or_old_reason(self):
        self.mark(['해지']);self.baseline();self.mark([]);self.remove()
        self.assertEqual(self.row()['result'],'누락');self.assertTrue(self.row()['missing'])
        self.s.undo();self.s.undo();self.remove();self.assert_handled('해지')

    def test_signal_exception_and_expected_cancel_are_not_status_dispositions(self):
        self.baseline();self.mark(['해지예상'])
        with self.s.action('신호 예외'):self.s.conn.execute("UPDATE cores SET signal='exception' WHERE core_id='SYNTH-WORK'")
        self.remove();self.assertEqual(self.row()['result'],'누락')

    def test_missing_without_record_stays_missing_and_incomplete_route_is_unchanged(self):
        self.baseline();self.mark(['끊김'])
        self.s.delete_core_assignment(self.cables[1],2)
        row=self.row();self.assertFalse(row.get('handled_missing'));self.assertNotEqual(row['result'],'끊김')
        self.s.undo();self.mark([]);self.remove();self.assertEqual(self.row()['result'],'누락')

    def test_undo_redo_and_restored_identity_invalidate_old_removal(self):
        self.baseline();self.mark(['해지']);self.remove();self.assert_handled('해지')
        self.s.undo();self.assertFalse(self.row().get('handled_missing'));self.assertEqual(wf.work_removed_status_ledger(self.s),{})
        self.s.redo();self.assert_handled('해지');self.s.undo();self.mark([]);self.remove()
        self.assertEqual(self.row()['result'],'누락')

    def test_multiple_explicit_states_keep_all_reasons_with_exception_completion(self):
        self.baseline();self.mark(['끊김','해지','예외코어']);self.remove();self.assert_handled('예외 처리')
        for label in ('끊김','해지','예외 처리'):self.assertIn(label,self.row()['reason'])

    def test_valid_work_exclusion_still_takes_priority(self):
        self.baseline();row=self.row();wf.Workflow(self.app).disposition([row],'이번 작업 제외','별도 승인')
        self.mark(['해지']);self.remove();self.assertEqual(self.row()['result'],'이번 작업 제외')
        self.assertIn('별도 승인',self.row()['note'])

    def test_restore_connection_required_overrides_handled_reason_and_undo(self):
        self.baseline();self.mark(['해지']);self.remove();row=self.row()
        wf.Workflow(self.app).disposition([row],'연결 필요','다시 연결')
        self.assertEqual(self.row()['result'],'누락');self.assertTrue(self.row()['missing'])
        self.s.undo();self.assert_handled('해지')

    def test_workbench_and_route_targets_share_handled_missing_reasons(self):
        self.baseline()
        for labels,result in ((['끊김'],'끊김'),(['예외코어'],'예외 처리'),(['해지'],'해지')):
            self.mark(labels);self.remove()
            row=wf.AfterPlanner(self.app).report()['rows'][0]
            self.assertEqual(row['status'],result);self.assertTrue(row['complete']);self.assertFalse(row['blocking'])
            entries=wf.AfterRoutePlanner(self.app).context()['entries']
            if result=='예외 처리':self.assertTrue(next(iter(entries.values()))['exception_complete'])
            else:self.assertEqual(entries,{})
            self.s.undo();self.s.undo()

    def test_renamed_temporary_core_uses_removed_physical_end_record(self):
        self.s.close();self.s=code['Store'](self.app.home/'temporary.sqlite3');self.app.store=self.s
        nodes,cables=temporary_fixture(self.s);self.s.backup_to(self.app.scenario_path('before'))
        self.before=self.app.scenario_path('before').read_bytes();phase(self.s,'after')
        with self.s.action('합성 임시ID 변경'):self.s.conn.execute("UPDATE cores SET core_id='임시-99' WHERE core_id LIKE '임시-%'")
        wf.save_annotations(self.s,(cables[0],3),['해지'],'')
        with self.s.action('합성 임시 배정 삭제'):
            for cable,index in zip(cables,(3,4,5)):self.s.delete_core_assignment(cable,index)
        self.assert_handled('해지');self.assertEqual(len(self.app.work_report()['rows']),1)

    def test_unrelated_core_status_and_undone_history_do_not_supply_reason(self):
        self.baseline()
        with self.s.action('별개 코어'):
            self.s.conn.execute("UPDATE cores SET core_id='OTHER',status1='cancel' WHERE cable_id=? AND core_index=10",(self.cables[0],))
        self.s.delete_core_assignment(self.cables[0],10);self.remove();self.assertEqual(self.row()['result'],'누락')

    def test_inherited_field_or_gis_history_cannot_supply_after_reason(self):
        self.mark(['끊김']);self.remove()
        with self.s.no_history():
            for cable,index in zip(self.cables,(1,2,3)):
                self.s.conn.execute("UPDATE cores SET core_id='SYNTH-WORK',status1='',status2='',signal='on' WHERE cable_id=? AND core_index=?",(cable,index))
            self.s.conn.execute('DELETE FROM core_annotations')
        self.baseline()
        with self.s.no_history():
            self.s.conn.execute("UPDATE cores SET core_id='',status1='',status2='',signal=''")
        self.assertEqual(self.row()['result'],'누락');self.assertTrue(self.row()['missing'])


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showwarning'), \
         patch.object(code['messagebox'],'showerror') as error:
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;nodes,cables=fixture(s)
            with s.action('합성 네 작업'):
                s.conn.execute('DELETE FROM splices');s.conn.execute("UPDATE cores SET core_id='',detail='',signal=''")
                s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(cables[1],))
                for index in range(1,5):
                    for cable in cables:s.conn.execute("UPDATE cores SET core_id=?,detail='처리 사유 검증',signal='on' WHERE cable_id=? AND core_index=?",('WORK-'+str(index),cable,index))
            s.backup_to(app.scenario_path('before'));before=app.scenario_path('before').read_bytes();phase(s,'after')
            for index,label in ((1,'끊김'),(2,'예외코어'),(3,'해지')):wf.save_annotations(s,(cables[0],index),[label],'합성 사용자 처리')
            with s.action('합성 모든 배정 삭제'):
                for index in range(1,5):
                    for cable in cables:s.delete_core_assignment(cable,index)
            app.refresh();dialog=code['CoreCheckDialog'](app,s);progress=code['WorkRequiredDialog'](app,s);app.update()
            assert {r[2]:r[4] for r in dialog.rows}=={'WORK-1':'끊김','WORK-2':'예외 처리','WORK-3':'해지','WORK-4':'누락'},dialog.rows
            assert [r['core_id'] for r in progress.visible]==['WORK-4'],progress.visible
            assert (app.work_progress()['total'],app.work_progress()['done'],app.work_progress()['excluded'])==(2,1,2)
            dialog.kind.set('코어연결필요');dialog.reload();assert [r[2] for r in dialog.rows]==['WORK-4']
            dialog.kind.set('작업필요코어(전체)');dialog.reload();dialog.copy_actions.copy(all_rows=True)
            assert all(v in dialog.clipboard_get() for v in ('끊김','예외 처리','해지'))
            for chosen,expected in (('끊김','WORK-1'),('예외 처리','WORK-2'),('완료','WORK-2'),('해지','WORK-3'),('누락','WORK-4')):
                progress.filter.set(chosen);progress.show_rows();assert [r['core_id'] for r in progress.visible]==[expected]
            path=Path(temp)/'work.csv'
            with patch.object(code['filedialog'],'asksaveasfilename',return_value=str(path)):dialog.csv_save()
            with path.open(encoding='utf-8-sig') as f:exported=list(csv.reader(f))
            assert {r[2]:r[4] for r in exported[1:]}=={'WORK-1':'끊김','WORK-2':'예외 처리','WORK-3':'해지','WORK-4':'누락'}
            with patch.object(code['webbrowser'],'open'):dialog.print_view()
            printed=next((Path(temp)/'print').glob('*.html')).read_text(encoding='utf-8')
            assert all(v in printed for v in ('끊김','예외 처리','해지'))
            progress.filter.set('전체');s.undo();app.refresh();progress.reload();app.update()
            assert all(not r.get('handled_missing') for r in progress.visible)
            s.redo();app.refresh();progress.reload();app.update();assert sum(r.get('handled_missing',False) for r in progress.visible)==3
            assert s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0]==0
            assert app.scenario_path('before').read_bytes()==before and not errors and not error.called,(errors,error.call_args)
            progress.destroy();dialog.destroy()
        finally:app.on_close()
    print('PASS Windows missing-work reason rows, remaining/handled filters, totals, clipboard, CSV, print and atomic undo/redo')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MissingStatusTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
