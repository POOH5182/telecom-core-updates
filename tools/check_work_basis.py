"""Only current field/after drawings may create transfer-work targets."""
import copy
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_work_classification import WorkApp, code, wf, fixture, phase


def legacy_gis_capture(app):
    """A different GIS drawing and its old, untagged accepted work snapshot."""
    path=app.scenario_path('gis');app.store.backup_to(path);gis=code['Store'](path)
    try:
        phase(gis,'gis')
        with gis.action('합성 GIS 임의 입력'):
            gis.conn.execute("UPDATE nodes SET status='철거',name='GIS 전용 시설'")
            gis.conn.execute("UPDATE cables SET status='절단'")
            cable=gis.conn.execute('SELECT id FROM cables LIMIT 1').fetchone()[0]
            gis.conn.execute("UPDATE cores SET core_id='GIS-ONLY',detail='GIS 전용 내역',signal='on' WHERE cable_id=? AND core_index=6",(cable,))
        captured=wf.capture(gis,gis.conn)
        for row in captured['items'].values():row['method']='시설철거절체'
        return captured
    finally:gis.close()


def install_legacy_capture(app,captured):
    value=wf.state(app.store);value['accepted']=copy.deepcopy(captured)
    value['decisions']['SYNTH-WORK']=dict(kind='이번 작업 제외',reason='GIS 과거 판단',signature=captured['items']['SYNTH-WORK']['signature'])
    wf.write_state(app.store,value,'합성 이전 버전 작업기록')


class WorkBasisTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=WorkApp(self.temp.name);self.s=self.app.store
        self.nodes,self.cables=fixture(self.s);self.s.backup_to(self.app.scenario_path('before'))
        self.gis=legacy_gis_capture(self.app);install_legacy_capture(self.app,self.gis);phase(self.s,'after')
    def tearDown(self):self.s.close();self.temp.cleanup()
    def report(self):return self.app.work_report()
    def field(self,*states):
        s=code['Store'](self.app.scenario_path('before'))
        try:
            with s.action('합성 현장 상태 변경'):
                for cable,status in zip(self.cables,states):s.conn.execute('UPDATE cables SET status=? WHERE id=?',(status,cable))
        finally:s.close()

    def test_gis_only_and_same_id_legacy_work_never_reappear(self):
        before=wf.plan_snapshot(self.s.conn);saved=wf.state(self.s);history=self.s.history_rows()
        report=self.report();self.assertEqual(report['rows'],[]);self.assertEqual((report['total'],report['pending']),(0,0))
        self.assertEqual(wf.plan_snapshot(self.s.conn),before);self.assertEqual(wf.state(self.s),saved);self.assertEqual(self.s.history_rows(),history)

    def test_gis_edits_and_legacy_capture_changes_do_not_change_work_or_review(self):
        self.field('기설','철거','기설');first=self.report()
        with self.app.scenario_path('gis').open('ab') as f:f.write(b'ignored GIS reference bytes')
        value=wf.state(self.s);value['accepted']['items']['GIS-ONLY']['detail']='또 바꾼 GIS'
        value['accepted']['items']['SYNTH-WORK']['method']='절단절체'
        wf.write_state(self.s,value,'합성 GIS 과거기록 변경')
        self.assertEqual(self.report(),first)
        row=first['rows'][0];self.assertEqual(row['method'],'코어절체');self.assertFalse(row['excluded'])
        self.assertNotIn('GIS',row['note']);self.assertNotIn('GIS',str(row['source_routes']))

    def test_current_field_and_after_move_take_priority_over_gis(self):
        self.field('기설','철거','기설');self.assertEqual(self.report()['rows'][0]['method'],'코어절체')
        self.field('기설','기설','기설');self.assertEqual(self.report()['rows'],[])
        self.s.commit_core_move(self.s.preview_core_move(self.cables[1],2,4))
        row=self.report()['rows'][0];self.assertEqual(row['method'],'코어절체');self.assertTrue(row['complete'])
        self.assertIn('코어번호 변경',row['note']);self.assertFalse(row['excluded'])
        self.s.undo();self.assertEqual(self.report()['rows'],[])
        self.s.redo();self.assertEqual(len(self.report()['rows']),1)
        self.field('절단','철거','기설');self.assertEqual(self.report()['rows'][0]['method'],'절단절체')

    def test_deleted_field_targets_do_not_resurrect_even_from_proven_field_acceptance(self):
        self.field('절단','기설','기설');wf.Workflow(self.app).accept()
        self.assertEqual(wf.state(self.s)['accepted']['source_kind'],'before')
        self.field('기설','기설','기설');self.assertEqual(self.report()['rows'],[])
        self.assertEqual(self.report()['pending'],0)

    def test_missing_field_does_not_fall_back_to_gis_or_accepted(self):
        self.field('절단','기설','기설');wf.Workflow(self.app).accept()
        self.app.scenario_path('before').unlink();report=self.report()
        self.assertTrue(report['missing_before']);self.assertEqual(report['rows'],[])
        self.assertEqual(report['pending'],0);self.assertEqual(wf.Workflow(self.app).changes(),[])

    def test_missing_after_allocations_still_use_current_field_only(self):
        with self.s.action('합성 후도면 배정 삭제'):
            self.s.conn.execute('DELETE FROM splices')
            self.s.conn.execute("UPDATE cores SET core_id='',detail='',signal=''")
        rows=self.report()['rows'];self.assertEqual([r['core_id'] for r in rows],['SYNTH-WORK'])
        self.assertTrue(rows[0]['missing']);self.assertEqual(rows[0]['method'],'코어절체')

    def test_matching_legacy_decisions_and_new_field_stale_guards_are_preserved(self):
        self.field('기설','철거','기설');row=self.report()['rows'][0]
        value=wf.state(self.s);value['decisions']['SYNTH-WORK'].update(signature=row['signature'],reason='현장 검토')
        wf.write_state(self.s,value,'합성 기존 현장 승인');self.assertTrue(self.report()['rows'][0]['excluded'])
        wf.Workflow(self.app).disposition([row],'이번 작업 제외','현재 현장 검토')
        self.field('절단','철거','기설');row=self.report()['rows'][0]
        self.assertEqual(row['result'],'제외 재확인');self.assertFalse(row['excluded'])

    def test_field_open_gis_stage_and_reopen(self):
        phase(self.s,'before');self.assertEqual(self.report()['rows'],[])
        with self.s.action('합성 현재 현장 절단'):self.s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(self.cables[1],))
        self.assertEqual([r['core_id'] for r in self.report()['rows']],['SYNTH-WORK'])
        phase(self.s,'gis');self.assertEqual(self.report()['rows'],[]);self.assertEqual(wf.Workflow(self.app).changes(),[])
        phase(self.s,'after');self.s.close();self.s=code['Store'](self.app.home/'working.sqlite3');self.app.store=self.s
        self.assertEqual(self.report()['rows'],[])


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showwarning'), \
         patch.object(code['messagebox'],'showerror') as error:
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;nodes,cables=fixture(s);s.backup_to(app.scenario_path('before'))
            gis=legacy_gis_capture(app);install_legacy_capture(app,gis)
            for kind in ('before','after','gis'):
                phase(s,kind);app.refresh();dialog=code['CoreCheckDialog'](app,s);progress=code['WorkRequiredDialog'](app,s)
                progress.filter.set('전체');progress.show_rows();app.update()
                assert dialog.rows==[] and progress.visible==[] and app.work_progress()['total']==0
                assert 'GIS' in dialog.work_basis.get()
                progress.destroy();dialog.destroy()
            phase(s,'after');wf.after_auto_activate(s)
            s.commit_core_move(s.preview_core_move(cables[1],2,4));app.refresh()
            dialog=code['CoreCheckDialog'](app,s);progress=code['WorkRequiredDialog'](app,s)
            progress.filter.set('전체');progress.show_rows();app.update()
            assert len(dialog.rows)==1 and dialog.rows[0][0]=='코어절체' and dialog.rows[0][2]=='SYNTH-WORK'
            assert len(progress.visible)==1 and progress.visible[0]['method']=='코어절체'
            dialog.copy_actions.copy(all_rows=True);assert 'GIS-ONLY' not in dialog.clipboard_get()
            dest=Path(temp)/'work.csv'
            with patch.object(code['filedialog'],'asksaveasfilename',return_value=str(dest)):dialog.csv_save()
            with dest.open(encoding='utf-8-sig') as f:exported=list(csv.reader(f))
            assert len(exported)==2 and exported[1][0]=='코어절체' and exported[1][2]=='SYNTH-WORK'
            with patch.object(code['webbrowser'],'open'):dialog.print_view()
            printed=next((Path(temp)/'print').glob('*.html')).read_text(encoding='utf-8')
            assert 'GIS-ONLY' not in printed and '시설철거절체' not in printed
            assert not errors and not error.called,(errors,error.call_args)
            progress.destroy();dialog.destroy()
        finally:app.on_close()
    print('PASS Windows GIS-independent work list, progress, counters, clipboard, CSV and print')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WorkBasisTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
