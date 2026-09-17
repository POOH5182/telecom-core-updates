"""Work lists require real IDs or ON on their physical field end cable."""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_work_classification import WorkApp,code,wf,fixture,phase


def eligible_fixture(s):
    nodes,cables=fixture(s)
    rn=s.add_node('합성 신호 RN',900,400,node_type='rn');s.ensure_ports(rn,{'mp':1,'sp':0,'p':1})
    with s.action('합성 작업대상 분류'):
        s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(cables[1],))
        for index,cid,signal in ((4,'임시-104','unknown'),(5,'임시-105','off'),(6,'임시-106','on'),
                                (7,'','unknown'),(8,'','on'),(9,'','off'),
                                (10,'REAL-OFF','off'),(11,'임시-111','unknown'),(12,'REAL-UNKNOWN','unknown')):
            s.conn.execute('UPDATE cores SET core_id=?,signal=?,detail=? WHERE cable_id=? AND core_index=?',
                           (cid,signal,'합성 내역',cables[1],index))
        s.conn.execute("UPDATE cores SET core_id='임시-104',signal='on' WHERE cable_id=? AND core_index=4",(cables[0],))
        s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(nodes[1],cables[0],4,cables[1],4))
        s.conn.execute("UPDATE ports SET core_id='임시-111',signal='on' WHERE node_id=? AND port_index=1",(rn,))
    return nodes,cables,rn


EXPECTED={'SYNTH-WORK','REAL-OFF','REAL-UNKNOWN','임시-104'}


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=WorkApp(self.temp.name);self.s=self.app.store
        self.nodes,self.cables,self.rn=eligible_fixture(self.s)
    def tearDown(self):self.s.close();self.temp.cleanup()
    def ids(self):return {r['core_id'] for r in self.app.work_report()['rows']}
    def baseline(self):
        self.s.backup_to(self.app.scenario_path('before'))
        self.before=self.app.scenario_path('before').read_bytes();phase(self.s,'after')

    def test_field_real_ids_all_signals_temporary_endpoint_on_and_anonymous_exclusion(self):
        snapshot=wf.plan_snapshot(self.s.conn);history=self.s.history_rows();state=wf.state(self.s)
        completion=self.s.drawing_connection_progress()
        self.assertEqual(self.ids(),EXPECTED)
        report=self.app.work_report();self.assertEqual(report['total'],len(EXPECTED))
        self.assertTrue(all(r['signal']=='on' for r in report['rows'] if r['core_id'].startswith('임시-')))
        self.assertTrue(all(r['method']=='절단절체' for r in report['rows']))
        self.assertEqual(wf.plan_snapshot(self.s.conn),snapshot);self.assertEqual(self.s.history_rows(),history)
        self.assertEqual(wf.state(self.s),state);self.assertEqual(self.s.drawing_connection_progress(),completion)

    def test_signal_change_undo_redo_and_reopen(self):
        with self.s.action('합성 전체 신호 OFF'):
            self.s.conn.execute("UPDATE cores SET signal='off' WHERE core_id='임시-104'")
        self.assertEqual(self.ids(),EXPECTED-{'임시-104'})
        self.s.undo();self.assertEqual(self.ids(),EXPECTED)
        self.s.redo();self.assertEqual(self.ids(),EXPECTED-{'임시-104'})
        self.s.close();self.s=code['Store'](self.app.home/'working.sqlite3');self.app.store=self.s
        self.assertEqual(self.ids(),EXPECTED-{'임시-104'})

    def test_after_legacy_accepted_rows_are_filtered_without_rewriting_evidence(self):
        wf.Workflow(self.app).accept();self.baseline()
        saved=wf.state(self.s);self.assertGreater(len(saved['accepted']['items']),len(EXPECTED))
        self.assertEqual(self.ids(),EXPECTED)
        with self.s.action('합성 임시 신호 변경'):
            self.s.conn.execute("UPDATE cores SET signal='off' WHERE core_id='임시-106'")
            self.s.conn.execute("UPDATE cores SET signal='on' WHERE core_id='임시-105'")
        self.assertEqual(self.ids(),EXPECTED)
        self.assertEqual(wf.state(self.s),saved);self.assertEqual(self.app.scenario_path('before').read_bytes(),self.before)

    def test_missing_allocations_keep_field_endpoint_on_and_real_id_targets(self):
        self.baseline()
        with self.s.action('합성 재배정 전 제거'):
            self.s.conn.execute('DELETE FROM splices')
            self.s.conn.execute("UPDATE cores SET core_id='',detail='',signal='' ")
            self.s.conn.execute("UPDATE ports SET core_id='',detail='',signal='' ")
        self.assertEqual(self.ids(),EXPECTED)
        self.assertTrue(all(r['missing'] for r in self.app.work_report()['rows']))
        self.assertEqual(self.app.scenario_path('before').read_bytes(),self.before)

    def test_pending_counts_exclude_hidden_work_and_preserve_real_decisions(self):
        self.baseline();report=self.app.work_report()
        self.assertEqual(report['pending'],len(EXPECTED));self.assertEqual(report['total'],len(EXPECTED))
        row=next(r for r in report['rows'] if r['core_id']=='REAL-OFF')
        wf.Workflow(self.app).disposition([row],'이번 작업 제외','합성 검토')
        report=self.app.work_report();self.assertEqual(report['excluded'],1);self.assertEqual(report['total'],len(EXPECTED)-1)
        self.assertEqual(self.ids(),EXPECTED)


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showwarning'), \
         patch.object(code['messagebox'],'showerror') as error:
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;nodes,cables,rn=eligible_fixture(s)
            s.backup_to(app.scenario_path('before'));baseline=app.scenario_path('before').read_bytes()
            for kind in ('before','after'):
                phase(s,kind);app.refresh()
                dialog=code['CoreCheckDialog'](app,s);progress=code['WorkRequiredDialog'](app,s)
                progress.filter.set('전체');progress.show_rows();app.update()
                assert {r[2] for r in dialog.rows}==EXPECTED,dialog.rows
                assert {r['core_id'] for r in progress.visible}==EXPECTED,progress.visible
                assert app.work_progress()['total']==len(EXPECTED)
                assert next(r[1] for r in dialog.rows if r[2]=='임시-104')=='ON'
                dest=Path(temp)/(kind+'.csv')
                with patch.object(code['filedialog'],'asksaveasfilename',return_value=str(dest)):dialog.csv_save()
                exported=list(csv.reader(dest.open(encoding='utf-8-sig')));assert {r[2] for r in exported[1:]}==EXPECTED
                with s.action('합성 목록 신호 OFF'):s.conn.execute("UPDATE cores SET signal='off' WHERE core_id='임시-104'")
                app.refresh();progress.reload();app.update()
                expected=EXPECTED-{'임시-104'} if kind=='before' else EXPECTED
                assert {r[2] for r in dialog.rows}==expected
                assert {r['core_id'] for r in progress.visible}==expected
                if kind=='after':assert next(r[1] for r in dialog.rows if r[2]=='임시-104')=='ON'
                s.undo();app.refresh();progress.reload();app.update()
                assert {r[2] for r in dialog.rows}==EXPECTED
                progress.destroy();dialog.destroy()
            assert app.scenario_path('before').read_bytes()==baseline
            assert not errors and not error.called,(errors,error.call_args)
        finally:app.on_close()
    print('PASS Windows field-end ON eligibility, interior/isolated RN negatives, stable after targets, undo, CSV, counts and baseline preservation')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EligibilityTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
