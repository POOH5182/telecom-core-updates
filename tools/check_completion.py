"""Mandatory-core matrix, 100% transitions and cross-window status repaint gates."""
import os
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

from check_field_survey import code,wf


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'drawing.sqlite3';self.store=code['Store'](self.path)
        s=self.store;self.a=s.add_node('왼쪽 말단',0,0);self.h=s.add_node('연결 함체',300,0);self.b=s.add_node('오른쪽 말단',600,0)
        self.left=s.add_cable(self.a,self.h,'LEFT','12C','기설');self.right=s.add_cable(self.h,self.b,'RIGHT','12C','기설')
        self.stage('before')
    def tearDown(self):self.store.close();self.temp.cleanup()
    def stage(self,kind):
        self.store.conn.execute("INSERT INTO meta VALUES('active_scenario',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(kind,));self.store.conn.commit();self.store._warning_cache=None;self.store._cable_warning_cache=None
    def core(self,index,cid,signal='',status=''):
        self.store.update_core(self.left,index,(cid,'내역 '+str(index),status,'',signal))
    def connect(self,index):self.store.connect(self.h,(self.left,index),(self.right,index),temporary=True)
    def report(self):return self.store.drawing_connection_progress()
    def snapshot(self):return wf.plan_snapshot(self.store.conn),self.store.data_revision(),self.store.history_rows()

    def test_explicit_before_after_policy_matrix_and_exclusion_precedence(self):
        cases=[('REAL','',[],True,True),('REAL','on',[],True,True),('임시-1','',[],False,False),
               ('임시-1','on',[],True,True),('REAL','on',['예외'],False,True),('REAL','on',['끊김'],False,True),
               ('REAL','on',['끊킴'],False,True),('REAL','on',['해지'],True,False),('REAL','',['해지예상'],True,True),
               ('','on',[],True,True),('','',['해지예상'],False,True),('','off',[],False,False),
               ('임시-2','',['해지예상'],False,False),('임시-2','on',['해지'],True,False),
               ('REAL','',['예외코어','해지'],False,False)]
        for cid,signal,labels,before,after in cases:
            row={'core_id':cid,'signal':signal,'annotation_labels':labels}
            for kind,expected in (('before',before),('gis',before),('after',after)):
                with self.subTest(cid=cid,signal=signal,labels=labels,kind=kind):self.assertEqual(wf.completion_policy([row],kind)['required'],expected)
        self.assertTrue(wf.completion_policy([{'core_id':'R','annotation_labels':['해지 검토 메모']}],'after')['required'])

    def test_same_id_signal_union_required_once_then_connection_reaches_100(self):
        s=self.store;self.core(1,'임시-100');self.connect(1)
        self.assertEqual(self.report()['total'],0);self.assertIsNone(self.report()['rate'])
        # An imported drawing can have signal marked only on one cable.
        s.conn.execute('UPDATE cores SET signal=? WHERE cable_id=? AND core_index=1',('on',self.right));s.conn.commit()
        report=self.report();self.assertEqual((report['total'],report['done'],report['rate']),(1,1,100))
        self.assertEqual(len(report['rows'][0]['slots']),2)
        s.disconnect(self.h,self.left,1);report=self.report()
        self.assertEqual((report['total'],report['done']),(1,0));self.assertEqual(len(s.incomplete_core_groups()),1)
        self.assertIn(1,s.node_assignment_needs(self.h)[self.left])
        self.connect(1);self.assertEqual(self.report()['rate'],100)

    def test_stage_denominators_and_excluded_incomplete_lists(self):
        self.core(1,'NORMAL');self.connect(1)
        self.core(2,'임시-200');self.core(3,'EX',status='exception');self.core(4,'BROKEN',status='broken')
        self.core(5,'CANCEL',status='cancel');self.connect(5)
        self.core(6,'EXPECTED',status='cancel_expected');self.connect(6)
        self.core(7,'임시-700','on');self.connect(7)
        self.assertEqual((self.report()['total'],self.report()['done'],self.report()['excluded']),(4,4,3))
        self.assertEqual(self.store.incomplete_core_groups(),[])
        self.stage('after');report=self.report()
        self.assertEqual((report['total'],report['done'],report['excluded']),(5,3,2))
        self.assertEqual({r['core_id'] for r in self.store.incomplete_core_groups()},{'EX','BROKEN'})
        self.store.update_core(self.right,3,('EX','내역 3','exception','',''))
        self.assertIn('EX',{r['core_id'] for r in self.store.waiting_connection_groups(self.h)})
        self.connect(3);self.connect(4);self.assertEqual(self.report()['rate'],100)
        self.assertEqual(self.store.incomplete_core_groups(),[])

    def test_signal_without_id_is_counted_per_slot_and_never_false_complete(self):
        self.core(1,'','on');self.core(2,'','on');report=self.report()
        self.assertEqual((report['total'],report['done']),(2,0));self.assertEqual(len(self.store.incomplete_core_groups()),2)
        self.assertTrue(all('코어ID 없음' in row['reason'] for row in report['rows']))
        self.assertEqual(self.store.node_warning_summary()[self.h]['count'],2)

    def test_after_expected_without_id_requires_input_and_cancel_is_exact(self):
        self.stage('after');self.core(1,'',status='cancel_expected');self.assertEqual(self.report()['total'],1)
        self.core(2,'EXPECTED',status='cancel_expected');self.core(3,'CANCELED',status='cancel')
        self.assertEqual({r['core_id'] for r in self.report()['rows']},{'','EXPECTED'})
        self.assertEqual(self.report()['excluded'],1);self.assertIn('cancel_expected',wf.STATUS_NAMES)
        self.assertNotEqual(code['core_row_tag'](self.store.core(self.left,2)),'cancel')

    def test_annotation_aliases_undo_reopen_and_read_only_calculation(self):
        s=self.store;self.core(1,'ONE');self.connect(1);old=self.snapshot()
        self.report();s.incomplete_core_entries();s.node_warning_summary();self.assertEqual(self.snapshot(),old)
        wf.save_annotations(s,(self.left,1),['예외'],'연결율 제외');self.assertEqual(self.report()['total'],0)
        s.undo();self.assertEqual(self.report()['total'],1);s.redo();self.assertEqual(self.report()['total'],0)
        s.close();self.store=code['Store'](self.path);self.assertEqual(self.report()['total'],0)
        self.stage('after');self.assertEqual((self.report()['total'],self.report()['done']),(1,1))

    def test_after_uses_active_routes_and_does_not_complete_retired_only_core(self):
        self.core(1,'LIVE');self.connect(1);self.stage('after');self.assertEqual(self.report()['rate'],100)
        self.store.conn.execute("UPDATE cables SET status='철거' WHERE id=?",(self.right,));self.store.conn.commit()
        report=self.report();self.assertEqual(report['total'],1);self.assertEqual(report['done'],0)
        # A new valid route of the same ID replaces the retired section.
        cable=self.store.add_cable(self.h,self.b,'NEW','12C','신설');self.store.disconnect(self.h,self.left,1)
        self.store.connect(self.h,(self.left,1),(cable,1));self.assertEqual(self.report()['rate'],100)

    def test_excluded_temporary_does_not_block_before_handoff_but_bad_input_does(self):
        self.core(1,'임시-1');self.core(2,'EX',status='exception');self.core(3,'BROKEN',status='broken')
        rows=self.store.before_drawing_check_rows();self.assertFalse([r for r in rows if r['level']=='오류'],rows)
        self.core(4,'SIGNAL','on');self.assertTrue([r for r in self.store.before_drawing_check_rows() if r['level']=='오류'])
        self.connect(4);wf.FieldSurvey(self.store,self.h).save('LEFT\tRIGHT\n4\t4')
        self.assertFalse([r for r in self.store.before_drawing_check_rows() if r['level']=='오류'])


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showwarning',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showinfo',return_value=None), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True), \
             patch.object(code['messagebox'],'askyesno',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *args:errors.append(str(args))
            try:
                s=app.store;a=s.add_node('왼쪽',200,400);h=s.add_node('중간',500,400);b=s.add_node('오른쪽',800,400)
                left=s.add_cable(a,h,'LEFT','12C','기설');right=s.add_cable(h,b,'RIGHT','12C','기설')
                s.update_core(left,1,('SHARED','공통 코어','','','on'));s.connect(h,(left,1),(right,1))
                s.update_core(left,2,('임시-22','임시','','',''))
                s.update_core(left,3,('EXPECTED','해지예상','cancel_expected','',''));s.connect(h,(left,3),(right,3))
                app.refresh();app.update();assert '100.0%' in app.work_progress_text.cget('text')
                first=code['CableDialog'](app,s,left);second=code['CableDialog'](app,s,right);node=code['NodeDialog'](app,s,h)
                summary=code['NodeSummaryDialog'](node,s,h);allcores=code['AllCoreDialog'](app,s)
                summary_row=next(iid for iid,slots in summary.row_slots.items() if (left,1) in slots)
                app.update();second.identity_tree.item('1',values=(1,'SHARED','저장 전 입력 보존'));second.identity_undo_stack.append({1:('SHARED','원래 내용')})
                allcores.tree.selection_set('SHARED');summary.tree.selection_set(summary_row);app.update()
                allcores.vars[1].set('전체표 입력 보존');summary.vars[1].set('내역표 입력 보존')
                node.name_var.set('저장 전 함체명');first.tree.selection_set('1');first.edit_annotations();app.update()
                dialog=next(w for w in first.winfo_children() if isinstance(w,wf.AnnotationDialog))
                dialog.choice.set('해지');dialog.add();dialog.save();app.update()
                for cable in (first,second):
                    assert 'cancel' in cable.tree.item('1','tags');assert 'cancel' in cable.identity_tree.item('1','tags')
                    assert '해지' in cable.tree.item('1','values')[0]
                assert second.identity_tree.item('1','values')[2]=='저장 전 입력 보존';assert len(second.identity_undo_stack)==1
                assert node.name_var.get()=='저장 전 함체명'
                for tree in (node.left_tree,node.right_tree):assert 'cancel' in tree.item('1','tags')
                assert 'cancel' in summary.tree.item(summary_row,'tags');assert '해지' in summary.tree.item(summary_row,'values')[-2]
                assert 'cancel' in allcores.tree.item('SHARED','tags');assert '해지' in allcores.tree.item('SHARED','values')[2]
                assert allcores.vars[1].get()=='전체표 입력 보존';assert summary.vars[1].get()=='내역표 입력 보존'
                # Undo and redo repaint all windows through the same shared refresh.
                s.undo();app.refresh();app.update();assert 'cancel' not in second.tree.item('1','tags')
                s.redo();app.refresh();app.update();assert 'cancel' in second.tree.item('1','tags')
                s.conn.execute("INSERT INTO meta VALUES('active_scenario','after') ON CONFLICT(key) DO UPDATE SET value=excluded.value");s.conn.commit()
                app.refresh();app.update();report=s.drawing_connection_progress()
                assert report['total']==1 and report['done']==1 and report['excluded']==2
                assert '후도면' in app.work_progress_text.cget('text');assert '100.0%' in app.work_progress_text.cget('text')
                targets=wf.CompletionTargetsDialog(app,s);app.update();assert len(targets.table.get_children())==3;targets.destroy()
                incomplete=code['IncompleteCoresDialog'](app,s);app.update();assert len(incomplete.entries)==0;incomplete.destroy()
                value=wf.state(s);value['phases']=[dict(id='test',name='완료율 검증',cores=[],cables=[dict(id=left,scope='after',label='LEFT')],excluded_cores=[],note='')]
                wf.write_state(s,value,'차수 시험');phase=wf.PhaseDialog(app);app.update()
                assert '100.0%' in phase.summary.get(),phase.summary.get()
                assert {r['core'] for r in phase.rows if not r['excluded']}=={'EXPECTED'}
                phase.only_unfinished.set(True);phase.reload();assert not phase.tree.get_children();phase.destroy()
                first.destroy();second.destroy();allcores.destroy();summary.destroy();node.destroy();assert not errors,errors
            finally:app.on_close()
    print('PASS Windows stage denominators and 100%, shared cancellation repaint in both cable tabs/enclosure, draft preservation, undo/redo and excluded list')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CompletionTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS before/after mandatory-core matrix, exact exclusions, temporary signals, missing-ID slots, topology and persistence')
