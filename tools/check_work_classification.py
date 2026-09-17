"""Field work types survive after edits; physical core transfers stay visible."""
import csv
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_after_plan import code,wf


class WorkApp:
    def __init__(self,home):
        self.home=Path(home);self.store=code['Store'](self.home/'working.sqlite3')
    def scenario_kind(self):return wf.completion_kind(self.store)
    def scenario_path(self,kind):return self.home/(kind+'.sqlite3')
    def work_report(self):return wf.Workflow(self).report()


def phase(s,kind):
    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario',?)",(kind,));s.conn.commit()


def fixture(s):
    phase(s,'before')
    nodes=[s.add_node('합성 함체 '+str(i),i*220,100) for i in range(4)]
    cables=[s.add_cable(nodes[i],nodes[i+1],'SYNTH-'+str(i),'12C','기설') for i in range(3)]
    with s.action('합성 1-2-3 연결'):
        for owner,index in zip(cables,(1,2,3)):
            s.conn.execute("UPDATE cores SET core_id='SYNTH-WORK',detail='합성 작업',signal='unknown' WHERE cable_id=? AND core_index=?",(owner,index))
        s.conn.execute("UPDATE cores SET signal='on' WHERE cable_id=? AND core_index=1",(cables[0],))
        s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(nodes[1],cables[0],1,cables[1],2))
        s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(nodes[2],cables[1],2,cables[2],3))
    return nodes,cables


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=WorkApp(self.temp.name)
        self.s=self.app.store;self.nodes,self.cables=fixture(self.s);self.baseline()
    def tearDown(self):self.s.close();self.temp.cleanup()
    def baseline(self):
        phase(self.s,'before');self.s.backup_to(self.app.scenario_path('before'))
        self.before_bytes=self.app.scenario_path('before').read_bytes();phase(self.s,'after');wf.after_auto_activate(self.s)
    def rows(self):return self.app.work_report()['rows']
    def row(self):return next(r for r in self.rows() if r['core_id']=='SYNTH-WORK')
    def move(self):return self.s.commit_core_move(self.s.preview_core_move(self.cables[1],2,4))
    def mark(self,*states):
        with self.s.action('합성 케이블 작업표시'):
            for c,status in zip(self.cables,states):self.s.conn.execute('UPDATE cables SET status=? WHERE id=?',(status,c))

    def test_field_cut_wins_over_removal_and_move_after_markers_deleted(self):
        self.mark('절단','철거','기설');phase(self.s,'before')
        self.assertEqual(self.row()['method'],'절단절체');self.baseline()
        self.mark('신설','기설','기설');self.move()
        row=self.row();self.assertEqual(row['method'],'절단절체');self.assertTrue(row['complete'])
        with self.s.action('합성 철거 구간 삭제'):
            self.s.conn.execute('DELETE FROM splices');self.s.conn.execute('DELETE FROM cables WHERE id=?',(self.cables[0],))
        self.assertEqual(self.row()['method'],'절단절체');self.assertFalse(self.row()['complete'])
        self.assertEqual(self.app.scenario_path('before').read_bytes(),self.before_bytes)

    def test_field_core_transfer_survives_after_new_status_completion_and_reopen(self):
        self.mark('기설','철거','기설');phase(self.s,'before')
        self.assertEqual(self.row()['method'],'코어절체');self.baseline();self.mark('기설','신설','기설')
        self.assertEqual((self.row()['method'],self.row()['result']),('코어절체','완료'))
        self.s.close();self.s=code['Store'](self.app.home/'working.sqlite3');self.app.store=self.s
        self.assertEqual((self.row()['method'],self.row()['result']),('코어절체','완료'))

    def test_existing_cable_move_read_only_undo_redo_baseline_and_disposition(self):
        self.assertEqual(self.rows(),[]);self.move()
        snapshot=wf.plan_snapshot(self.s.conn);history=self.s.history_rows();value=wf.state(self.s)
        row=self.row();self.assertEqual((row['method'],row['result']),('코어절체','완료'))
        self.assertIn('코어번호 변경',row['note']);self.assertTrue(row['derived_transfer'])
        self.assertEqual(wf.plan_snapshot(self.s.conn),snapshot);self.assertEqual(self.s.history_rows(),history);self.assertEqual(wf.state(self.s),value)
        self.assertEqual(self.app.scenario_path('before').read_bytes(),self.before_bytes)
        self.s.undo();self.assertEqual(self.rows(),[]);self.s.redo();self.assertEqual(self.row()['method'],'코어절체')
        wf.Workflow(self.app).disposition([self.row()],'이번 작업 제외','검토 완료')
        self.assertTrue(self.row()['excluded']);self.s.undo();self.assertFalse(self.row()['excluded'])
        self.s.close();self.s=code['Store'](self.app.home/'working.sqlite3');self.app.store=self.s
        self.assertEqual(self.row()['method'],'코어절체')

    def test_peer_change_with_unchanged_allocations_is_transfer(self):
        with self.s.action('합성 기존 배정'):
            self.s.conn.execute("UPDATE cores SET core_id='SYNTH-WORK',detail='합성 작업' WHERE cable_id=? AND core_index=4",(self.cables[1],))
        self.baseline();self.assertEqual(self.rows(),[])
        wf.reconnect_selected(self.s,self.nodes[1],(self.cables[0],1),(self.cables[1],4))
        self.assertEqual(self.row()['method'],'코어절체');self.assertIn('접속 상대 변경',self.row()['note'])
        self.assertNotIn('코어번호 변경',self.row()['note']);self.assertFalse(self.row()['complete'])

    def test_different_cable_route_and_facility_removal(self):
        s=self.s;new=s.add_cable(self.nodes[1],self.nodes[2],'SYNTH-NEW','12C','기설')
        with s.action('합성 다른 케이블로 절체'):
            s.conn.execute("UPDATE cores SET core_id='',detail='',signal='' WHERE cable_id=? AND core_index=2",(self.cables[1],))
            s.conn.execute("UPDATE cores SET core_id='SYNTH-WORK',detail='합성 작업',signal='unknown' WHERE cable_id=? AND core_index=2",(new,))
            s.conn.execute('UPDATE splices SET cable1_id=? WHERE cable1_id=?',(new,self.cables[1]))
            s.conn.execute('UPDATE splices SET cable2_id=? WHERE cable2_id=?',(new,self.cables[1]))
        self.assertEqual((self.row()['method'],self.row()['result']),('코어절체','완료'))
        self.assertIn('경로 변경',self.row()['note'])
        with s.action('합성 시설철거'):s.conn.execute("UPDATE nodes SET status='철거' WHERE id=?",(self.nodes[1],))
        self.baseline();self.assertEqual(self.row()['method'],'코어절체')

    def test_metadata_geometry_cable_label_and_reversed_splice_are_not_transfer(self):
        s=self.s
        with s.action('합성 표시 정보 변경'):
            s.conn.execute("UPDATE cores SET detail='새 이름',signal='on' WHERE core_id='SYNTH-WORK'")
            s.conn.execute("UPDATE cables SET cable_id='새 표시명',extra_json=?",(json.dumps({'lotNo':'NEW'}),))
            s.conn.execute("UPDATE nodes SET x=x+50,name=name||' 수정'")
            s.conn.execute('UPDATE splices SET cable1_id=cable2_id,core1_index=core2_index,cable2_id=cable1_id,core2_index=core1_index')
        self.assertEqual(self.rows(),[])
        new=s.add_cable(self.nodes[1],self.nodes[2],'NEW-SERVICE','12C','신설')
        with s.action('합성 신규 서비스'):s.conn.execute("UPDATE cores SET core_id='NEW-ID',signal='on' WHERE cable_id=? AND core_index=1",(new,))
        self.assertEqual(self.rows(),[])

    def test_neutral_handoff_is_not_transfer_but_rn_port_move_is(self):
        s=self.s;rn=self.nodes[3]
        with s.action('합성 RN'):
            s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(rn,));s.ensure_ports(rn,{'mp':2,'sp':0,'p':0})
            s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(rn,self.cables[2],3,'PORT:'+rn,1))
            s.conn.execute("UPDATE cores SET core_id='임시-998' WHERE cable_id=? AND core_index=2",(self.cables[1],))
        self.baseline()
        with s.action('합성 현장 ID 반영'):
            s.conn.execute("UPDATE cores SET core_id='SYNTH-WORK' WHERE cable_id=? AND core_index=2",(self.cables[1],))
            s.conn.execute("UPDATE ports SET core_id='SYNTH-WORK',detail='합성 작업' WHERE node_id=? AND port_index=1",(rn,))
        self.assertEqual(self.rows(),[])
        with s.action('합성 RN 포트 이동'):
            s.conn.execute("UPDATE ports SET core_id='',detail='' WHERE node_id=? AND port_index=1",(rn,))
            s.conn.execute("UPDATE ports SET core_id='SYNTH-WORK',detail='합성 작업' WHERE node_id=? AND port_index=2",(rn,))
            s.conn.execute('UPDATE splices SET core2_index=2 WHERE cable2_id=?',('PORT:'+rn,))
        self.assertEqual(self.row()['method'],'코어절체');self.assertIn('RN 내부포트 변경',self.row()['note'])

    def test_missing_basis_never_guesses_and_saved_basis_refreshes(self):
        self.move();self.assertEqual(self.row()['method'],'코어절체')
        self.baseline();self.assertEqual(self.rows(),[])
        self.app.scenario_path('before').unlink();r=self.app.work_report()
        self.assertTrue(r['missing_before']);self.assertEqual(r['rows'],[])

    def test_removed_last_allocation_remains_a_missing_work_target(self):
        with self.s.action('합성 재배정 전 삭제'):
            self.s.conn.execute('DELETE FROM splices')
            self.s.conn.execute("UPDATE cores SET core_id='',detail='',signal='' WHERE core_id='SYNTH-WORK'")
        self.assertEqual((self.row()['method'],self.row()['result']),('코어절체','누락'))
        self.s.undo();self.assertEqual(self.rows(),[])


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showwarning'), \
         patch.object(code['messagebox'],'showerror') as error:
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;nodes,cables=fixture(s)
            with s.action('합성 현장 철거'):s.conn.execute("UPDATE cables SET status='철거' WHERE id=?",(cables[1],))
            s.backup_to(app.scenario_path('before'));baseline=app.scenario_path('before').read_bytes()
            field=code['CoreCheckDialog'](app,s);app.update()
            assert field.rows[0][0]=='코어절체',field.rows;field.destroy()
            phase(s,'after');wf.after_auto_activate(s)
            with s.action('합성 후도면 신설'):s.conn.execute("UPDATE cables SET status='신설' WHERE id=?",(cables[1],))
            app.refresh();dialog=code['CoreCheckDialog'](app,s);app.update()
            assert dialog.kind.get()=='작업필요코어(전체)'
            assert len(dialog.rows)==1 and dialog.rows[0][0]=='코어절체' and dialog.rows[0][4]=='완료',dialog.rows
            dialog.kind.set('코어연결필요');dialog.reload();assert not dialog.rows
            dialog.kind.set('전체코어');dialog.reload();assert dialog.rows[0][0]=='코어절체'
            dialog.kind.set('작업필요코어(전체)');dialog.reload();iid=dialog.tree.get_children()[0]
            dialog.tree.selection_set(iid);dialog.pick_name();dialog.name_var.set('보존할 이름 초안')
            s.commit_core_move(s.preview_core_move(cables[1],2,4));app.refresh();app.update()
            assert dialog.rows[0][0]=='코어절체' and '코어번호 변경' in dialog.rows[0][5]
            assert dialog.name_var.get()=='보존할 이름 초안'
            s.undo();app.refresh();app.update();assert '코어번호 변경' not in dialog.rows[0][5]
            s.redo();app.refresh();app.update();assert '코어번호 변경' in dialog.rows[0][5]
            dialog.tree.cycle_sort('id');app.update();dialog.trace_selected();app.update()
            for widget in list(app.winfo_children()):
                if isinstance(widget,code['TraceDialog']):widget.destroy()
            dest=Path(temp)/'work.csv'
            with patch.object(code['filedialog'],'asksaveasfilename',return_value=str(dest)):dialog.csv_save()
            exported=list(csv.reader(dest.open(encoding='utf-8-sig')));assert exported[1][0]=='코어절체'
            with patch.object(code['webbrowser'],'open'):dialog.print_view()
            printed=next((Path(temp)/'print').glob('*.html')).read_text(encoding='utf-8');assert '<td>코어절체</td>' in printed
            progress=code['WorkRequiredDialog'](app,s);progress.filter.set('전체');progress.show_rows();app.update()
            assert progress.visible[0]['method']=='코어절체' and progress.visible[0]['result']=='완료'
            dialog.geometry('950x650');app.update();assert dialog.work_basis.get() and dialog.tree.winfo_ismapped()
            assert app.scenario_path('before').read_bytes()==baseline
            assert not errors and not error.called,(errors,error.call_args)
            progress.destroy();dialog.destroy()
        finally:app.on_close()
    print('PASS Windows field-to-after core transfer retention, completed default list, pending filter, methods across lists, move/undo/redo, drafts, CSV/print and original preservation')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ClassificationTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS field cut priority, removed cable/core number/peer/route/RN transfers, neutral metadata negatives, history, reopen and read-only evidence')
