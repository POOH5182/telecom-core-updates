"""Same-ID work-list signals and atomic whole-drawing name editing."""
import csv
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_after_plan import code,wf


def fixture(s):
    nodes=[s.add_node('합성 시설 '+str(i),i*250,200) for i in range(4)]
    cables=[s.add_cable(nodes[i],nodes[i+1],'SYNTH-'+str(i),'12C','기설') for i in range(3)]
    rn=s.add_node('합성 RN',800,500,node_type='rn');s.ensure_ports(rn,{'mp':1,'sp':0,'p':1})
    with s.action('합성 목록 자료'):
        for owner,index,name,signal in ((cables[0],1,'이전 이름','unknown'),(cables[1],4,'다른 이름','on'),(cables[2],3,'','unknown')):
            s.conn.execute("UPDATE cores SET core_id='SYNTH-A',detail=?,signal=? WHERE cable_id=? AND core_index=?",(name,signal,owner,index))
        s.conn.execute("UPDATE ports SET core_id='SYNTH-A',detail='RN 이름',signal='unknown' WHERE node_id=? AND port_index=1",(rn,))
        s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(cables[1],))
        for index,cid,signal in ((2,'SYNTH-A-OTHER','off'),(5,'임시-999','on'),(6,'','on'),(7,'','unknown')):
            s.conn.execute('UPDATE cores SET core_id=?,detail=?,signal=? WHERE cable_id=? AND core_index=?',(cid,'별도 이름',signal,cables[0],index))
    s.conn.execute("INSERT INTO meta VALUES('active_scenario','after') ON CONFLICT(key) DO UPDATE SET value=excluded.value");s.conn.commit()
    wf.after_auto_activate(s)
    return nodes,cables,rn


class WorklistTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);self.path=self.home/'drawing.sqlite3'
        self.s=code['Store'](self.path);self.nodes,self.cables,self.rn=fixture(self.s)
        self.baseline=self.home/'before.sqlite3';self.s.backup_to(self.baseline);self.baseline_bytes=self.baseline.read_bytes()
    def tearDown(self):self.s.close();self.temp.cleanup()
    def snapshot(self):return wf.plan_snapshot(self.s.conn),wf.state(self.s)
    def rename(self,name):return self.s.commit_core_name(self.s.preview_core_name('SYNTH-A'),name)

    def test_signal_whole_id_matrix_ports_markers_anonymous_and_no_writes(self):
        s=self.s;before=self.snapshot();history=s.history_rows()
        info=wf.core_check_info(s,'SYNTH-A');self.assertEqual((info['label'],info['counts']),('ON',{'unknown':3,'on':1}))
        self.assertEqual(wf.core_check_info(s,'SYNTH-A-OTHER')['label'],'OFF')
        self.assertEqual(wf.core_check_info(s,'',(self.cables[0],7))['label'],'확인필요')
        self.assertEqual(wf.core_check_info(s,'',(self.cables[0],6))['label'],'ON')
        self.assertEqual(wf.core_check_info(s,'MISSING',fallback_signal='on')['label'],'ON')
        self.assertEqual(self.snapshot(),before);self.assertEqual(s.history_rows(),history)
        for signal,label in (('off','OFF'),('unknown','확인필요'),('on','ON')):
            with s.action('합성 신호 수정'):s.conn.execute('UPDATE cores SET signal=? WHERE cable_id=? AND core_index=4',(signal,self.cables[1]))
            self.assertEqual(wf.core_check_info(s,'SYNTH-A')['label'],label)
        with s.action('합성 RN OFF'):s.conn.execute("UPDATE ports SET signal='off' WHERE node_id=? AND port_index=1",(self.rn,))
        self.assertEqual(wf.core_check_info(s,'SYNTH-A')['label'],'ON');self.assertIn('신호 불일치',wf.core_check_info(s,'SYNTH-A')['warning'])
        s.undo();self.assertFalse(wf.core_check_info(s,'SYNTH-A')['warning']);s.redo();self.assertTrue(wf.core_check_info(s,'SYNTH-A')['warning'])
        s.close();self.s=code['Store'](self.path);self.assertEqual(wf.core_check_info(self.s,'SYNTH-A')['label'],'ON')

    def test_name_every_position_only_detail_one_undo_reopen_and_baseline(self):
        s=self.s;before=self.snapshot();history=len(s.history_rows());preview=s.preview_core_name('SYNTH-A')
        self.assertEqual(len(preview['positions']),4);self.assertEqual(self.snapshot(),before)
        self.assertEqual(s.commit_core_name(preview,'새 코어명'),4)
        after=self.snapshot();self.assertEqual(len(s.history_rows()),history+1)
        self.assertEqual(wf.core_id_overview(s)['SYNTH-A']['names'],['새 코어명'])
        self.assertEqual(self.baseline.read_bytes(),self.baseline_bytes);self.assertTrue(list((self.home/'backup').glob('*core_name*')))
        for table,rows in before[0].items():
            if table not in ('cores','ports'):self.assertEqual(after[0][table],rows,table);continue
            expected=[dict(row,detail='새 코어명') if row['core_id']=='SYNTH-A' else row for row in rows]
            self.assertEqual(after[0][table],expected,table)
        self.assertEqual(after[1],before[1]);s.undo();self.assertEqual(self.snapshot(),before);s.redo();self.assertEqual(self.snapshot(),after)
        s.close();self.s=code['Store'](self.path);self.assertEqual(self.snapshot(),after)
        n=len(self.s.history_rows());self.assertEqual(self.rename('새 코어명'),0);self.assertEqual(len(self.s.history_rows()),n)
        self.assertEqual(self.rename(''),4);self.assertEqual(wf.core_id_overview(self.s)['SYNTH-A']['names'],[''])
        self.assertEqual(wf.core_check_info(self.s,'SYNTH-A')['label'],'ON')

    def test_name_only_never_creates_same_id_automatic_splices(self):
        s=self.s
        s.conn.execute('DELETE FROM splices');s.conn.commit();before=self.snapshot()
        self.rename('이름만 수정');self.assertEqual(wf.plan_snapshot(s.conn)['splices'],before[0]['splices'])

    def test_stale_lock_tampered_and_port_failure_are_atomic(self):
        s=self.s;preview=s.preview_core_name('SYNTH-A')
        with s.action('합성 다른 위치 수정'):s.conn.execute("UPDATE cores SET detail='바뀜' WHERE cable_id=? AND core_index=2",(self.cables[0],))
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'새로고침'):s.commit_core_name(preview,'금지')
        self.assertEqual(self.snapshot(),before)
        for cid in ('','MISSING'):
            with self.assertRaises(ValueError):s.preview_core_name(cid)
        s.set_node_locked(self.nodes[2],True)
        with self.assertRaises(ValueError):s.preview_core_name('SYNTH-A')
        s.set_node_locked(self.nodes[2],False);preview=s.preview_core_name('SYNTH-A');preview['positions']=[]
        with self.assertRaises(ValueError):s.commit_core_name(preview,'금지')
        preview=s.preview_core_name('SYNTH-A');before=self.snapshot();history=s.history_rows()
        s.conn.execute("CREATE TEMP TRIGGER fail_name BEFORE UPDATE OF detail ON ports BEGIN SELECT RAISE(ABORT,'synthetic port write'); END")
        with self.assertRaises(Exception):s.commit_core_name(preview,'전부 취소')
        self.assertEqual(self.snapshot(),before);self.assertEqual(s.history_rows(),history)


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showwarning'), \
         patch.object(code['messagebox'],'showerror') as error,patch.object(code['messagebox'],'askyesno',return_value=True):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;nodes,cables,rn=fixture(s);s.backup_to(app.scenario_path('before'));app.refresh();app.update()
            # Source evidence remains frozen; current names/signals must override its display.
            source=dict(core_id='SYNTH-A',detail='전도면 이름',signal='unknown',result='미완료',method='작업',source_routes=['합성 경로'],source_slots=[(cables[0],1)])
            with patch.object(app,'work_report',return_value={'rows':[source]}):
                dialog=code['CoreCheckDialog'](app,s);app.update()
                assert dialog.rows[0][1]=='ON' and dialog.rows[0][3]!='전도면 이름',dialog.rows
                def choose(cid):
                    iid=next(i for i,key in dialog.row_meta.items() if key[0]==cid)
                    dialog.tree.selection_set(iid);dialog.tree.focus(iid);dialog.pick_name();app.update();return iid
                choose('SYNTH-A');assert '4개 위치' in dialog.name_scope.get()
                first=code['CableDialog'](app,s,cables[0]);other=code['CableDialog'](app,s,cables[1]);allcores=code['AllCoreDialog'](app,s);app.update()
                other.identity_tree.item('4',values=(4,'SYNTH-A','저장 전 내역'));other.identity_undo_stack.append({4:('SYNTH-A','다른 이름')})
                allcores.vars[1].set('전체표 저장 전 이름')
                for kind in ('전체코어','미완료코어','신호있음','끊어진 중복경로'):
                    dialog.kind.set(kind);dialog.reload();app.update()
                    rows=[r for i,r in enumerate(dialog.rows) if dialog._row_keys[i][0]=='SYNTH-A'];assert rows and all(r[1]=='ON' for r in rows),(kind,rows)
                dialog.kind.set('신호확인필요');dialog.reload();assert all(k[0]!='SYNTH-A' for k in dialog._row_keys)
                dialog.kind.set('코어연결필요');dialog.reload();choose('SYNTH-A')
                dialog.name_var.set('목록에서 새 이름');dialog.name_button.invoke();app.update();assert not error.called,error.call_args
                assert all(r['detail']=='목록에서 새 이름' for r in s.all_core_rows('SYNTH-A'))
                assert first.identity_tree.item('1','values')[2]=='목록에서 새 이름'
                assert other.identity_tree.item('4','values')[2]=='저장 전 내역' and len(other.identity_undo_stack)==1
                assert allcores.tree.item('SYNTH-A','values')[1]=='목록에서 새 이름'
                assert allcores.vars[1].get()=='전체표 저장 전 이름'
                assert dialog.rows[0][3]=='목록에서 새 이름' and dialog.name_var.get()=='목록에서 새 이름'
                s.undo();app.refresh();app.update();assert dialog.name_var.get()!='목록에서 새 이름'
                s.redo();app.refresh();app.update();assert dialog.name_var.get()=='목록에서 새 이름'
                # Background refresh retains the draft but does not silently approve a changed scope.
                dialog.name_var.set('보존할 초안')
                with s.action('합성 다른 코어 변경'):s.conn.execute("UPDATE cores SET detail='다른 변경' WHERE cable_id=? AND core_index=2",(cables[0],))
                app.refresh();app.update();assert dialog.name_var.get()=='보존할 초안'
                before=wf.plan_snapshot(s.conn);dialog.apply_name();assert error.called and '새로고침' in str(error.call_args)
                assert wf.plan_snapshot(s.conn)==before;error.reset_mock()
                dialog.refresh_list();assert dialog.name_var.get()=='보존할 초안';dialog.name_button.invoke();app.update();assert not error.called,error.call_args
                assert all(r['detail']=='보존할 초안' for r in s.all_core_rows('SYNTH-A'))
                # Sorted selection and temporary display IDs map back to the exact stored ID.
                dialog.kind.set('신호있음');dialog.reload();dialog.tree.cycle_sort('id');app.update();choose('임시-999')
                dialog.name_var.set('임시 이름 변경');dialog.name_button.invoke();app.update()
                assert s.core(cables[0],5)['detail']=='임시 이름 변경';assert s.core(cables[0],1)['detail']=='보존할 초안'
                dialog.kind.set('코어연결필요');dialog.reload();choose('SYNTH-A')
                with s.action('합성 신호 충돌'):s.conn.execute("UPDATE ports SET signal='off' WHERE node_id=? AND port_index=1",(rn,))
                app.refresh();app.update();assert dialog.rows[0][1]=='ON' and '신호 불일치' in dialog.rows[0][5]
                dest=Path(temp)/'list.csv'
                with patch.object(code['filedialog'],'asksaveasfilename',return_value=str(dest)):dialog.csv_save()
                exported=list(csv.reader(dest.open(encoding='utf-8-sig')));assert exported[1][1:4]==['ON','SYNTH-A','보존할 초안']
                with patch.object(code['webbrowser'],'open'):dialog.print_view()
                printed=next((Path(temp)/'print').glob('*.html')).read_text(encoding='utf-8');assert '보존할 초안' in printed and '<td>ON</td>' in printed
                dialog.geometry('950x650');app.update();assert dialog.name_button.winfo_rootx()+dialog.name_button.winfo_width()<=dialog.winfo_rootx()+dialog.winfo_width()
                s.set_node_locked(nodes[2],True);app.refresh();app.update();assert 'disabled' in dialog.name_button.state()
                s.set_node_locked(nodes[2],False);app.refresh();app.update();assert 'disabled' not in dialog.name_button.state()
                s._view_generation+=1;dialog.apply_name();assert not errors,errors
                first.destroy();other.destroy();allcores.destroy();dialog.destroy()
        finally:app.on_close()
    print('PASS Windows work-list whole-ID ON, source override, filters, sorted/temp ID name editing, RN/global repaint, drafts/stale/locks, undo/redo, CSV/print and narrow layout')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WorklistTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS work-list whole-ID signals and atomic name-only propagation, backups, baseline/topology protection and persistence')
