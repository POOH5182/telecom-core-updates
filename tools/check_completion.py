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

    def test_legacy_temporary_completed_badge_requires_complete_path(self):
        s=self.store;self.core(1,'임시-100');self.connect(1)
        tail=s.add_node('마지막 말단',900,0);last=s.add_cable(self.b,tail,'LAST','12C','기설')
        self.assertTrue(all(w['temporary_complete']==0 for w in s.cable_core_warning_summary().values()))
        s.connect(self.b,(self.right,1),(last,1))
        before=self.snapshot();warnings=s.cable_core_warning_summary()
        self.assertEqual([warnings[c]['temporary_complete'] for c in (self.left,self.right,last)],[1,0,1])
        self.assertEqual(self.report()['total'],0);self.assertEqual(self.snapshot(),before)
        s.disconnect(self.h,self.left,1)
        self.assertTrue(all(w['temporary_complete']==0 for w in s.cable_core_warning_summary().values()))

    def test_legacy_selected_core_brief_matches_completion(self):
        self.core(1,'ONE');status,reason=wf.core_completion_brief(self.store,(self.left,1))
        self.assertEqual(status,'미완료');self.assertIn('코어연결 미완료',reason)
        self.connect(1);self.assertEqual(wf.core_completion_brief(self.store,(self.left,1)),('연결완료',''))

    def test_selected_unknown_shows_same_id_on_across_disconnected_marked_positions(self):
        self.core(1,'SHARED','unknown');s=self.store
        with s.action('독립 위치 신호'):
            s.conn.execute("UPDATE cores SET core_id='SHARED',signal='on' WHERE cable_id=? AND core_index=7",(self.right,))
            s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(self.right,))
        for kind in ('gis','before','after'):
            self.stage(kind);before=self.snapshot();summary=wf.core_id_signal_summary(s,(self.left,1))
            self.assertEqual((summary['signal'],summary['local_signal'],summary['total']),('on','unknown',2))
            self.assertEqual(summary['counts'],{'on':1,'unknown':1})
            self.assertIn('선택 번호 신호: 확인필요',summary['detail'])
            self.assertFalse(wf.completion_report(s)['by_id']['SHARED']['complete'])
            self.assertEqual(self.snapshot(),before)
        self.assertEqual(s.core(self.left,1)['signal'],'unknown')
        self.assertFalse(list(s.conn.execute('SELECT * FROM splices')))

    def test_whole_id_signal_matrix_preserves_conflicts_errors_and_local_values(self):
        s=self.store;self.core(1,'ONE','unknown')
        cases=[('','unknown','확인필요'),('ON','on','ON'),('off','off','OFF'),('예외','exception','예외'),('error','error','오류')]
        for remote,expected,label in cases:
            with self.subTest(remote=remote):
                with s.action('다른 선번 신호'):
                    s.conn.execute("UPDATE cores SET core_id='ONE',signal=? WHERE cable_id=? AND core_index=1",(remote,self.right))
                summary=wf.core_id_signal_summary(s,(self.left,1))
                self.assertEqual((summary['signal'],summary['label']),(expected,label))
                self.assertEqual(s.core(self.left,1)['signal'],'unknown')
        with s.action('ON OFF 혼재'):
            s.conn.execute("UPDATE cores SET signal='on' WHERE cable_id=? AND core_index=1",(self.left,))
            s.conn.execute("UPDATE cores SET signal='off' WHERE cable_id=? AND core_index=1",(self.right,))
        summary=wf.core_id_signal_summary(s,(self.left,1))
        self.assertEqual(summary['signal'],'mixed');self.assertEqual(summary['label'],'불일치 (ON / OFF)')

    def test_signal_summary_includes_exact_id_ports_but_never_merges_blank_or_similar_ids(self):
        s=self.store;self.core(1,'ONE','unknown');self.core(2,'ONE-OTHER','on')
        self.core(3,'','on');self.core(4,'','off')
        self.assertEqual(wf.core_id_signal_summary(s,(self.left,1))['signal'],'unknown')
        self.assertEqual(wf.core_id_signal_summary(s,(self.left,4))['counts'],{'off':1})
        rn=s.add_node('RN 신호',900,0,node_type='rn');s.ensure_ports(rn,{'mp':1,'sp':0,'p':1})
        with s.action('동일 ID 포트 신호'):
            s.conn.execute("UPDATE ports SET core_id='ONE',signal='on' WHERE node_id=? AND port_index=1",(rn,))
        summary=wf.core_id_signal_summary(s,(self.left,1));self.assertEqual(summary['counts'],{'unknown':1,'on':1})
        self.assertEqual(wf.core_id_signal_summary(s,('PORT:'+rn,1))['local_signal'],'on')

    def test_signal_summary_recalculates_on_edit_undo_redo_identity_change_and_reopen(self):
        s=self.store;self.core(1,'ONE','unknown')
        self.assertEqual(wf.core_id_signal_summary(s,(self.left,1))['signal'],'unknown')
        with s.action('같은 ID 신호 변경'):
            s.conn.execute("UPDATE cores SET core_id='ONE',signal='on' WHERE cable_id=? AND core_index=1",(self.right,))
        self.assertEqual(wf.core_id_signal_summary(s,(self.left,1))['signal'],'on')
        s.undo();self.assertEqual(wf.core_id_signal_summary(s,(self.left,1))['signal'],'unknown')
        s.redo();self.assertEqual(wf.core_id_signal_summary(s,(self.left,1))['signal'],'on')
        with s.action('다른 ID로 변경'):
            s.conn.execute("UPDATE cores SET core_id='OTHER' WHERE cable_id=? AND core_index=1",(self.right,))
        self.assertEqual(wf.core_id_signal_summary(s,(self.left,1))['signal'],'unknown')
        s.undo();s.close();self.store=code['Store'](self.path)
        self.assertEqual(wf.core_id_signal_summary(self.store,(self.left,1))['signal'],'on')

    def test_explicit_before_after_policy_matrix_and_exclusion_precedence(self):
        cases=[('REAL','',[],True,True),('REAL','on',[],True,True),('임시-1','',[],False,False),
               ('임시-1','on',[],True,True),('REAL','on',['예외'],True,True),('REAL','on',['끊김'],True,True),
               ('REAL','on',['끊킴'],True,True),('REAL','on',['해지'],True,False),('REAL','',['해지예상'],True,True),
               ('','on',[],True,True),('','',['해지예상'],False,True),('','off',[],False,False),
               ('임시-2','',['해지예상'],False,False),('임시-2','on',['해지'],True,False),
               ('REAL','',['예외코어','해지'],True,True)]
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
        self.assertEqual(s.node_assignment_needs(self.h),{}) # Temporary ON still requires a route, but not an enclosure allocation badge.
        self.connect(1);self.assertEqual(self.report()['rate'],100)

    def test_stage_denominators_and_excluded_incomplete_lists(self):
        self.core(1,'NORMAL');self.connect(1)
        self.core(2,'임시-200');self.core(3,'EX',status='exception');self.core(4,'BROKEN',status='broken')
        self.core(5,'CANCEL',status='cancel');self.connect(5)
        self.core(6,'EXPECTED',status='cancel_expected');self.connect(6)
        self.core(7,'임시-700','on');self.connect(7)
        self.assertEqual((self.report()['total'],self.report()['done'],self.report()['excluded']),(5,5,2))
        self.assertEqual(self.store.incomplete_core_groups(),[])
        self.stage('after');report=self.report()
        self.assertEqual((report['total'],report['done'],report['excluded']),(4,4,3))
        self.assertEqual({r['core_id'] for r in self.store.incomplete_core_groups()},set())
        self.store.update_core(self.right,3,('EX','내역 3','exception','',''))
        self.assertNotIn('EX',{r['core_id'] for r in self.store.waiting_connection_groups(self.h)})
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
        wf.save_annotations(s,(self.left,1),['예외'],'완료 처리');self.assertEqual((self.report()['total'],self.report()['done']),(1,1))
        s.undo();self.assertEqual(self.report()['total'],1);s.redo();self.assertEqual((self.report()['total'],self.report()['done']),(1,1))
        s.close();self.store=code['Store'](self.path);self.assertEqual((self.report()['total'],self.report()['done']),(1,1))
        self.stage('after');self.assertEqual((self.report()['total'],self.report()['done']),(1,1))

    def test_after_work_markers_preserve_connections_and_new_route_can_replace_old(self):
        self.core(1,'LIVE');self.connect(1);self.stage('after');self.assertEqual(self.report()['rate'],100)
        self.store.conn.execute("UPDATE cables SET status='철거' WHERE id=?",(self.right,));self.store.conn.commit()
        report=self.report();self.assertEqual(report['total'],1);self.assertEqual(report['done'],1)
        # A new valid route of the same ID replaces the retired section.
        cable=self.store.add_cable(self.h,self.b,'NEW','12C','신설');self.store.disconnect(self.h,self.left,1)
        self.assertEqual(self.report()['done'],0)
        self.store.connect(self.h,(self.left,1),(cable,1));self.assertEqual(self.report()['rate'],100)

    def test_excluded_temporary_does_not_block_before_handoff_but_bad_input_does(self):
        self.core(1,'임시-1');self.core(2,'EX',status='exception');self.core(3,'BROKEN',status='broken')
        rows=self.store.before_drawing_check_rows();self.assertFalse([r for r in rows if r['level']=='오류'],rows)
        self.core(4,'SIGNAL','on');self.assertTrue([r for r in self.store.before_drawing_check_rows() if r['level']=='오류'])
        self.connect(4);wf.FieldSurvey(self.store,self.h).save('LEFT\tRIGHT\n4\t4')
        self.assertFalse([r for r in self.store.before_drawing_check_rows() if r['level']=='오류'])

    def test_check_list_groups_core_ids_without_losing_diagnostics_or_changing_progress(self):
        s=self.store
        for cable in (self.left,self.right):s.update_core(cable,1,('SHARED','','normal','','on'))
        self.core(2,'OTHER','on')
        before=self.snapshot();progress=self.report()
        raw=s.before_drawing_check_rows();original=[dict(r) for r in raw]
        grouped=wf.completion_check_groups(raw)
        ids=[r['core_id'] for r in grouped if r['core_id']]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(set(ids),{r['core_id'] for r in raw if r['core_id']})
        members=[r for r in raw if r['core_id']=='SHARED']
        self.assertGreater(len(members),2)
        self.assertTrue(any(r['level']=='오류' for r in members))
        self.assertTrue(any(r['level']=='경고' for r in members))
        row=next(r for r in grouped if r['core_id']=='SHARED')
        self.assertEqual(row['level'],'오류');self.assertEqual(list(row['_check_items']),members)
        for issue in members:
            self.assertIn(issue['message'],row['message']);self.assertIn(issue['location'],row['location'])
        self.assertEqual(len([r for r in grouped if not r['core_id']]),len([r for r in raw if not r['core_id']]))
        self.assertEqual(raw,original);self.assertEqual(self.snapshot(),before)
        self.assertEqual((self.report()['total'],self.report()['done']),(progress['total'],progress['done']))

    def test_grouping_keeps_anonymous_issues_and_similar_ids_separate(self):
        def item(cid,location,level='경고',**kwargs):
            return dict(core_id=cid,location=location,level=level,category='코어 입력',message=location+' 확인',**kwargs)
        rows=[item('ID-1','A',cable_id='a'),item('ID-01','B',cable_id='b'),
              item('ID-1','RN','오류',cable_id='PORT:rn',node_id='rn',core_index=1),
              item('','ID 없는 번호 1',core_index=1),item('','ID 없는 번호 2',core_index=2),item('','시설 자체 오류')]
        grouped=wf.completion_check_groups(rows)
        self.assertEqual(len(grouped),5)
        same=next(r for r in grouped if r['core_id']=='ID-1')
        self.assertEqual(same['level'],'오류');self.assertEqual(same['_check_items'][1]['cable_id'],'PORT:rn')
        self.assertEqual([r['location'] for r in grouped if not r['core_id']],['ID 없는 번호 1','ID 없는 번호 2','시설 자체 오류'])


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
                app.refresh();app.update();assert '100.0%' in app.work_progress_rate.cget('text')
                first=code['CableDialog'](app,s,left);second=code['CableDialog'](app,s,right);node=code['NodeDialog'](app,s,h)
                # Both routes are already assigned: choose them with the default
                # "unassigned cables only" filter disabled, as a user would.
                for value in node.assignment_filters.values():value.set(False)
                node.left_var.set(next(label for label,cid in node.by_label.items() if cid==left))
                node.right_var.set(next(label for label,cid in node.by_label.items() if cid==right));node.reload_all()
                assert node.left_tree.exists('1') and node.right_tree.exists('1')
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
                assert '후도면' in app.work_progress_text.cget('text');assert '100.0%' in app.work_progress_rate.cget('text')
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


def windows_signal_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showerror') as error, \
         patch.object(code['messagebox'],'askyesno',return_value=True):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;a=s.add_node('시작',0,0);h=s.add_node('중간',300,0);b=s.add_node('끝',600,0)
            left=s.add_cable(a,h,'LEFT','12C','기설');right=s.add_cable(h,b,'RIGHT','12C','기설')
            with s.action('합성 신호'):
                s.conn.execute("UPDATE cores SET core_id='SHARED',signal='unknown' WHERE cable_id=? AND core_index=1",(left,))
                s.conn.execute("UPDATE cores SET core_id='SHARED',signal='on' WHERE cable_id=? AND core_index=7",(right,))
                s.conn.execute("UPDATE cores SET core_id='OTHER',signal='off' WHERE cable_id=? AND core_index=2",(left,))
                s.conn.execute("UPDATE cores SET signal='on' WHERE cable_id=? AND core_index=3",(left,))
            app.refresh();app.update();snapshot=wf.plan_snapshot(s.conn);history=s.history_rows()
            dialog=code['CableDialog'](app,s,left);dialog.tree.selection_set('1');app.update()
            assert dialog.completion_signal.get()=='전체 신호: ON'
            assert '선택 번호 신호: 확인필요' in dialog.completion_signal_detail.get()
            assert dialog.edit_vars[2].get()=='확인필요' and dialog.tree.item('1','values')[1]=='확인필요'
            assert (wf.plan_snapshot(s.conn),s.history_rows())==(snapshot,history)
            dialog.notebook.select(dialog.identity_tab);dialog.identity_tree.selection_set('1');app.update()
            dialog.identity_tree.item('1',values=(1,'UNSAVED-ID','입력 내용 보존'));dialog.identity_undo_stack.append({1:('SHARED','')})
            with s.action('다른 케이블 신호 수정'):
                s.conn.execute("UPDATE cores SET signal='off' WHERE cable_id=? AND core_index=7",(right,))
            app.refresh();app.update();assert dialog.completion_signal.get()=='전체 신호: OFF'
            assert dialog.identity_tree.item('1','values')[1:] == ('UNSAVED-ID','입력 내용 보존')
            assert len(dialog.identity_undo_stack)==1
            s.undo();app.refresh();app.update();assert dialog.completion_signal.get()=='전체 신호: ON'
            s.redo();app.refresh();app.update();assert dialog.completion_signal.get()=='전체 신호: OFF'
            with s.action('신호 충돌'):
                s.conn.execute("UPDATE cores SET signal='on' WHERE cable_id=? AND core_index=1",(left,))
            app.refresh();app.update();assert dialog.completion_signal.get()=='전체 신호: 불일치 (ON / OFF)'
            for width in (1240,1000):
                dialog.geometry(f'{width}x740');app.update()
                assert dialog.completion_signal_label.winfo_viewable() and dialog.identity_tree.winfo_height()>90
                for widget in (dialog.completion_signal_label,dialog.completion_signal_detail_label,dialog.map_allocation_button):
                    assert widget.winfo_rootx()+widget.winfo_width()<=dialog.winfo_rootx()+dialog.winfo_width(),(width,widget.winfo_geometry())
                    assert widget.winfo_rooty()+widget.winfo_height()<=dialog.winfo_rooty()+dialog.winfo_height()
            dialog.identity_tree.selection_set('2');dialog.identity_tree.cycle_sort('number');app.update()
            assert dialog.completion_signal.get()=='전체 신호: OFF'
            dialog.identity_tree.selection_set('3');app.update();assert dialog.completion_signal.get()=='선택 번호 신호: ON'
            dialog.identity_tree.selection_remove(*dialog.identity_tree.selection());app.update()
            assert not dialog.completion_signal.get() and not dialog.completion_signal_detail.get()
            dialog.destroy();assert not errors and not error.called,(errors,error.call_args_list)
        finally:app.on_close()
    print('PASS Windows same-ID whole signal/local signal, both tabs, draft preservation, edit/undo/redo, conflict, sorting and narrow layout')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CompletionTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    windows_signal_ui()
    print('PASS before/after mandatory-core matrix, exact exclusions, temporary signals, missing-ID slots, topology and persistence')
