"""Physical field end-cable signal survives temporary ID changes in after."""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_work_classification import WorkApp,code,wf,phase


def fixture(s):
    phase(s,'before')
    nodes=[s.add_node('끝단 검증 '+str(i),i*200,100) for i in range(4)]
    cables=[s.add_cable(nodes[i],nodes[i+1],'END-'+str(i),'12C','기설') for i in range(3)]
    with s.action('합성 현장 임시 경로'):
        for cable,index,cid,signal in zip(cables,(3,4,5),('임시-3','임시-4','임시-5'),('on','unknown','unknown')):
            s.conn.execute("UPDATE cores SET core_id=?,detail='끝단 신호 검증',signal=? WHERE cable_id=? AND core_index=?",(cid,signal,cable,index))
        s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(cables[1],))
        for i in range(2):
            s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(nodes[i+1],cables[i],i+3,cables[i+1],i+4))
    return nodes,cables


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=WorkApp(self.temp.name);self.s=self.app.store
        self.nodes,self.cables=fixture(self.s)
    def tearDown(self):self.s.close();self.temp.cleanup()
    def rows(self):return self.app.work_report()['rows']
    def baseline(self):
        self.s.backup_to(self.app.scenario_path('before'));self.original=self.app.scenario_path('before').read_bytes();phase(self.s,'after')
    def rename(self,cid='임시-99'):
        with self.s.action('합성 임시ID 통합'):
            self.s.conn.execute('UPDATE cores SET core_id=? WHERE core_id LIKE ?', (cid,'임시-%'))
    def unchanged(self):self.assertEqual(self.app.scenario_path('before').read_bytes(),self.original)

    def test_field_physical_path_one_target_despite_three_temporary_ids(self):
        rows=self.rows();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['signal'],'on')
        self.assertEqual(rows[0]['result'],'작업필요');self.assertEqual(len(rows[0]['field_endpoints']),2)
        self.assertEqual(rows[0]['source_core_ids'],['임시-3','임시-4','임시-5'])

    def test_renamed_after_route_one_complete_target_and_no_old_planner_ghost(self):
        self.baseline();self.rename();snap=wf.plan_snapshot(self.s.conn);history=self.s.history_rows()
        rows=self.rows();self.assertEqual([(r['core_id'],r['result']) for r in rows],[('임시-99','완료')])
        entries=wf.AfterRoutePlanner(self.app).context()['entries']
        self.assertEqual({r['core_id'] for r in entries.values()},{'임시-99'})
        planned=wf.AfterPlanner(self.app).report()['rows'];self.assertEqual([r['core_id'] for r in planned],['임시-99'])
        self.assertNotIn('누락',planned[0]['change']);self.assertTrue(planned[0]['connection_required'])
        self.assertEqual(wf.plan_snapshot(self.s.conn),snap);self.assertEqual(self.s.history_rows(),history);self.unchanged()

    def test_after_signal_cannot_add_or_remove_field_obligation(self):
        self.baseline();self.rename()
        with self.s.action('후도면 신호 변경'):self.s.conn.execute("UPDATE cores SET signal='unknown' WHERE core_id='임시-99'")
        self.assertEqual(len(self.rows()),1);self.assertEqual(self.rows()[0]['signal'],'on');self.assertTrue(self.rows()[0]['complete'])
        self.assertEqual({r['core_id'] for r in wf.AfterRoutePlanner(self.app).context()['entries'].values()},{'임시-99'})
        self.unchanged()

    def test_interior_on_does_not_supply_terminal_signal(self):
        with self.s.action('중간 케이블에만 ON'):
            self.s.conn.execute("UPDATE cores SET signal='unknown'")
            self.s.conn.execute("UPDATE cores SET signal='on' WHERE cable_id=? AND core_index=4",(self.cables[1],))
        self.assertEqual(self.rows(),[]);self.baseline();self.rename()
        with self.s.action('후도면 끝단 ON'):self.s.conn.execute("UPDATE cores SET signal='on' WHERE cable_id=? AND core_index=3",(self.cables[0],))
        self.assertEqual(self.rows(),[])

    def test_renaming_only_does_not_invent_a_transfer_on_unmarked_route(self):
        with self.s.action('작업 표시 없는 현장'):self.s.conn.execute("UPDATE cables SET status='기설'")
        self.assertEqual(self.rows(),[]);self.baseline();self.assertEqual(self.rows(),[])
        self.rename();self.assertEqual(self.rows(),[])

    def test_same_id_on_another_disconnected_number_does_not_qualify(self):
        with self.s.action('다른 번호 ON'):
            self.s.conn.execute("UPDATE cores SET signal='unknown'")
            self.s.conn.execute("UPDATE cores SET core_id='임시-3',signal='on' WHERE cable_id=? AND core_index=9",(self.cables[0],))
        self.assertEqual(self.rows(),[])

    def test_number_move_and_rename_follow_source_endpoint_not_cable_only(self):
        self.baseline();self.rename('임시-3')
        self.s.commit_core_move(self.s.preview_core_move(self.cables[0],3,8))
        self.assertEqual(self.rows()[0]['result'],'완료');self.assertIn((self.cables[0],8),map(tuple,self.rows()[0]['current_slots']))
        self.s.undo();self.assertEqual(self.rows()[0]['result'],'완료');self.unchanged()

    def test_deleted_or_ambiguous_endpoint_remains_pending(self):
        self.baseline();self.rename()
        with self.s.action('끝단 배정 지움'):
            self.s.conn.execute('DELETE FROM splices WHERE node_id=?',(self.nodes[1],))
            self.s.conn.execute("UPDATE cores SET core_id='',detail='',signal='' WHERE cable_id=? AND core_index=3",(self.cables[0],))
        row=self.rows()[0];self.assertFalse(row['complete']);self.assertIn('대응 확인',row['note'])
        self.assertEqual(len(self.rows()),1);self.unchanged()

    def test_separate_field_halves_coalesce_only_after_real_join(self):
        with self.s.action('분리된 현장 양쪽 구간'):
            self.s.conn.execute('DELETE FROM splices WHERE node_id=?',(self.nodes[2],))
            self.s.conn.execute("UPDATE cores SET signal='on' WHERE cable_id=? AND core_index=5",(self.cables[2],))
            self.s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(self.cables[2],))
        self.assertEqual(len(self.rows()),2);self.baseline();self.rename()
        self.assertEqual(len(self.rows()),2);self.assertTrue(all(not r['complete'] for r in self.rows()))
        self.s.connect(self.nodes[2],(self.cables[1],4),(self.cables[2],5))
        self.assertEqual(len(self.rows()),1);self.assertTrue(self.rows()[0]['complete'])
        self.s.undo();self.assertEqual(len(self.rows()),2);self.unchanged()

    def test_remaining_old_id_on_unrelated_number_does_not_steal_endpoint(self):
        self.baseline();self.rename()
        with self.s.action('별개 위치에 옛 임시 ID 유지'):
            self.s.conn.execute("UPDATE cores SET core_id='임시-3',signal='on' WHERE cable_id=? AND core_index=10",(self.cables[0],))
        self.assertTrue(self.rows()[0]['complete']);self.assertNotIn((self.cables[0],10),map(tuple,self.rows()[0]['current_slots']))

    def test_independent_numbers_on_same_end_cables_stay_separate(self):
        with self.s.action('별개 현장 코어'):
            for cable in self.cables:
                self.s.conn.execute("UPDATE cores SET core_id='임시-3',signal='on' WHERE cable_id=? AND core_index=10",(cable,))
            for i in range(2):self.s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(self.nodes[i+1],self.cables[i],10,self.cables[i+1],10))
        self.assertEqual(len(self.rows()),2);self.baseline()
        with self.s.action('각 경로 ID 변경'):
            self.s.conn.execute("UPDATE cores SET core_id='임시-90' WHERE core_index=10 AND core_id<>''")
            self.s.conn.execute("UPDATE cores SET core_id='임시-91' WHERE core_index<>10 AND core_id<>''")
        self.assertEqual({r['core_id'] for r in self.rows()},{'임시-90','임시-91'})
        self.assertTrue(all(r['complete'] for r in self.rows()))

    def test_signal_and_real_identity_conflicts_still_block(self):
        self.baseline();self.rename()
        with self.s.action('신호 충돌'):self.s.conn.execute("UPDATE cores SET signal='off' WHERE cable_id=? AND core_index=5",(self.cables[2],))
        self.assertFalse(self.rows()[0]['complete']);self.assertIn('신호 불일치',self.rows()[0]['note'])
        self.s.undo()
        with self.s.action('실제 ID 충돌'):
            self.s.conn.execute("UPDATE cores SET core_id='REAL-A' WHERE cable_id=? AND core_index=3",(self.cables[0],))
            self.s.conn.execute("UPDATE cores SET core_id='REAL-B' WHERE cable_id=? AND core_index=5",(self.cables[2],))
        self.assertFalse(self.rows()[0]['complete']);self.assertIn('서로 다른 실제',self.rows()[0]['note'])

    def test_rn_requires_real_internal_connection_and_end_cable_on(self):
        with self.s.action('RN 끝단'):
            self.s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.nodes[3],))
            self.s.conn.execute("INSERT INTO ports VALUES(?,1,'MP1','임시-5','','','','unknown')",(self.nodes[3],))
            self.s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(self.nodes[3],self.cables[2],5,'PORT:'+self.nodes[3],1))
        self.baseline();self.rename()
        self.assertTrue(self.rows()[0]['complete'])
        with self.s.action('RN 포트 해제'):self.s.conn.execute('DELETE FROM splices WHERE node_id=?',(self.nodes[3],))
        self.assertFalse(self.rows()[0]['complete']);self.unchanged()

    def test_rn_end_cable_on_remains_required_before_port_is_connected(self):
        with self.s.action('RN 끝단 미접속'):
            self.s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.nodes[3],))
            self.s.conn.execute("UPDATE cores SET signal='unknown'")
            self.s.conn.execute("UPDATE cores SET signal='on' WHERE cable_id=? AND core_index=5",(self.cables[2],))
        self.assertEqual(len(self.rows()),1);self.baseline();self.rename();self.assertFalse(self.rows()[0]['complete'])
        with self.s.action('RN 실제 내부포트 연결'):
            self.s.conn.execute("INSERT INTO ports VALUES(?,1,'MP1','임시-99','','','','unknown')",(self.nodes[3],))
            self.s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(self.nodes[3],self.cables[2],5,'PORT:'+self.nodes[3],1))
        self.assertTrue(self.rows()[0]['complete']);self.unchanged()

    def test_disposition_undo_reopen_and_baseline_signal_invalidation(self):
        self.baseline();self.rename();row=self.rows()[0]
        wf.Workflow(self.app).disposition([row],'이번 작업 제외','합성 검토')
        self.assertTrue(self.rows()[0]['excluded']);self.s.undo();self.assertFalse(self.rows()[0]['excluded'])
        self.s.close();self.s=code['Store'](self.app.home/'working.sqlite3');self.app.store=self.s
        self.assertEqual(self.rows()[0]['result'],'완료');self.unchanged()
        phase(self.s,'before')
        with self.s.action('현장 끝단 ON 해제'):self.s.conn.execute("UPDATE cores SET signal='unknown'")
        self.s.backup_to(self.app.scenario_path('before'));phase(self.s,'after')
        self.assertEqual(self.rows(),[])


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showwarning'), \
         patch.object(code['messagebox'],'showerror') as error:
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;nodes,cables=fixture(s);s.backup_to(app.scenario_path('before'));original=app.scenario_path('before').read_bytes();phase(s,'after')
            with s.action('합성 임시 번호 변경'):
                s.conn.execute("UPDATE cores SET core_id='임시-99',signal='unknown' WHERE core_id LIKE '임시-%'")
            app.refresh();dialog=code['CoreCheckDialog'](app,s);progress=code['WorkRequiredDialog'](app,s)
            progress.filter.set('전체');progress.show_rows();app.update()
            assert len(dialog.rows)==1 and dialog.rows[0][1:3]==('ON','임시-99') and dialog.rows[0][4]=='완료',dialog.rows
            assert len(progress.visible)==1 and progress.visible[0]['complete'] and app.work_progress()['done']==1
            dialog.kind.set('코어연결필요');dialog.reload();assert not dialog.rows
            dialog.kind.set('작업필요코어(전체)');dialog.reload();dialog.copy_actions.copy(all_rows=True)
            assert '임시-99' in dialog.clipboard_get() and '현장 끝단' in dialog.clipboard_get()
            path=Path(temp)/'work.csv'
            with patch.object(code['filedialog'],'asksaveasfilename',return_value=str(path)):dialog.csv_save()
            with path.open(encoding='utf-8-sig') as f:exported=list(csv.reader(f))
            assert len(exported)==2 and exported[1][1:3]==['ON','임시-99']
            with patch.object(code['webbrowser'],'open'):dialog.print_view()
            assert '임시-99' in next((Path(temp)/'print').glob('*.html')).read_text(encoding='utf-8')
            with s.action('후도면 접속 해제'):s.conn.execute('DELETE FROM splices WHERE node_id=?',(nodes[1],))
            app.refresh();progress.reload();app.update();assert not progress.visible[0]['complete']
            s.undo();app.refresh();progress.reload();app.update();assert progress.visible[0]['complete']
            assert app.scenario_path('before').read_bytes()==original and not errors and not error.called,(errors,error.call_args)
            progress.destroy();dialog.destroy()
        finally:app.on_close()
    print('PASS Windows field-end signal, renamed temporary ID, one completed work row, filters, counts, copy, CSV, print and undo')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EndpointTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
