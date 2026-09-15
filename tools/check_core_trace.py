"""V75: physical field traces, slot-owned signals and OK versus completion."""
import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from check_field_slots import SlotFieldTests,code,wf


class CoreTraceTests(unittest.TestCase):
    setUp=SlotFieldTests.setUp
    tearDown=SlotFieldTests.tearDown
    slot=SlotFieldTests.slot
    set=SlotFieldTests.set
    apply=SlotFieldTests.apply
    audit=SlotFieldTests.audit
    snapshot=SlotFieldTests.snapshot
    connect_all=SlotFieldTests.connect_all

    def test_completed_temporary_badges_only_at_actual_ends_and_never_mixed_real_ids(self):
        # Different neutral temporary tokens are one actual path; unused and
        # partly connected temporary slots must not contribute to the badge.
        for i in range(3):self.set(i,2,'임시-'+str(80+i))
        self.s.connect(self.nodes[1],self.slot(0,2),self.slot(1,2))
        self.assertTrue(all(w['temporary_complete']==0 for w in self.s.cable_core_warning_summary().values()))
        self.s.connect(self.nodes[2],self.slot(1,2),self.slot(2,2))
        self.set(0,3,'임시-90');self.set(1,3,'임시-91');self.s.connect(self.nodes[1],self.slot(0,3),self.slot(1,3))
        self.set(2,4,'임시-80')  # Equal token elsewhere must not merge physical paths.
        before=self.snapshot();revision=self.s.data_revision();history=self.s.history_rows();report=wf.completion_report(self.s)
        warnings=self.s.cable_core_warning_summary()
        self.assertEqual([warnings[c]['temporary_complete'] for c in self.cables],[1,0,1])
        self.assertGreater(warnings[self.cables[1]]['temporary_total'],0)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.s.data_revision(),revision);self.assertEqual(self.s.history_rows(),history)
        self.assertEqual(wf.completion_report(self.s),report)
        self.set(1,2,'REAL-IN-MIDDLE')
        self.assertTrue(all(w['temporary_complete']==0 for w in self.s.cable_core_warning_summary().values()))
        self.s.undo();self.assertEqual([self.s.cable_core_warning_summary()[c]['temporary_complete'] for c in self.cables],[1,0,1])
        self.s.close();self.s=code['Store'](self.path)
        self.assertEqual([self.s.cable_core_warning_summary()[c]['temporary_complete'] for c in self.cables],[1,0,1])

    def test_temporary_endpoints_rn_port_and_signal_conflict(self):
        for i in range(3):self.set(i,2,'임시-'+str(80+i))
        for i in (1,2):self.s.connect(self.nodes[i],self.slot(i-1,2),self.slot(i,2))
        with self.s.action('RN 끝단'):self.s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.nodes[3],))
        self.s.ensure_ports(self.nodes[3],{'mp':1,'sp':1,'p':8})
        self.assertTrue(all(w['temporary_complete']==0 for w in self.s.cable_core_warning_summary().values()))
        self.s.connect(self.nodes[3],self.slot(2,2),('PORT:'+self.nodes[3],1))
        self.assertEqual([self.s.cable_core_warning_summary()[c]['temporary_complete'] for c in self.cables],[1,0,1])
        self.set(0,2,'임시-80','','on');self.set(2,2,'임시-82','','off')
        self.assertTrue(all(w['temporary_complete']==0 for w in self.s.cable_core_warning_summary().values()))
        # One cable between two different true terminals counts once, not twice.
        a=self.s.add_node('단독 끝 A',0,300);b=self.s.add_node('단독 끝 B',240,300)
        one=self.s.add_cable(a,b,'ONE','6C','기설');self.s.update_core(one,1,('임시-99','','normal','','unknown'))
        self.assertEqual(self.s.cable_core_warning_summary()[one]['temporary_complete'],1)

    def test_selected_core_brief_reasons_follow_physical_saved_state(self):
        self.apply(1,'A\tB\n1\t1')
        self.assertEqual(wf.core_completion_brief(self.s,self.slot(0)),('미완료','코어연결 미완료'))
        self.set(1,1,'OTHER','','off')
        status,reason=wf.core_completion_brief(self.s,self.slot(0));self.assertEqual(status,'미완료')
        self.assertEqual(set(reason.split(' · ')),{'코어연결 미완료','코어ID 다름','신호 불일치'})
        for i in range(3):self.set(i,1,'CORE-A','','unknown')
        self.apply(2,'B\tC\n1\t1');before=self.snapshot()
        self.assertEqual(wf.core_completion_brief(self.s,self.slot(1)),('연결완료',''))
        self.assertEqual(wf.core_completion_brief(self.s,self.slot(1,6)),('미사용 코어',''))
        self.assertEqual(self.snapshot(),before)
        keys={r['key'] for r in wf.FieldSurvey(self.s,self.nodes[1]).report()}
        wf.field_local_mark(self.s,self.nodes[1],keys,'NOT OK',self.s.data_revision(),getattr(self.s,'_view_generation',0),'직접 확인')
        self.assertEqual(wf.core_completion_brief(self.s,self.slot(1)),('미완료','함체 NOT OK'))

    def test_ten_enclosures_partial_field_input_never_inherits_gis_splices(self):
        gis=code['Store'](self.home/'ten-gis.sqlite3')
        nodes=[gis.add_node(f'함체 {i+1}',i*240,0) for i in range(10)]
        cables=[gis.add_cable(nodes[i],nodes[i+1],f'C{i+1}','12C','기설') for i in range(9)]
        gis.update_core(cables[0],1,('TEN-ID','GIS 저장내역','normal','','on'))
        for i in range(1,9):gis.connect(nodes[i],(cables[i-1],1),(cables[i],1))
        gis.conn.execute("UPDATE cores SET signal='on' WHERE core_index=1");gis.conn.commit();gis.close()
        original=(self.home/'ten-gis.sqlite3').read_bytes()
        wf.field_slot_copy(self.home/'ten-gis.sqlite3',self.home/'ten-field.sqlite3');s=code['Store'](self.home/'ten-field.sqlite3')
        try:
            before=wf.plan_snapshot(s.conn);trace=s.trace_core_paths('TEN-ID')
            self.assertEqual(len(trace['groups']),9);self.assertFalse(trace['complete'])
            self.assertEqual(wf.plan_snapshot(s.conn),before)
            for i in (1,2):wf.field_overlay_commit(s,wf.field_overlay_preview(s,nodes[i],f'C{i}\tC{i+1}\n1\t1'))
            trace=s.trace_core_paths('TEN-ID');self.assertEqual(len(trace['groups']),7)
            self.assertFalse(trace['complete']);self.assertIn('미완료',trace['summary'])
            chosen=s.trace_core_paths('TEN-ID',slot=(cables[0],1))
            self.assertEqual(chosen['highlight'],set(cables[:3]));self.assertIn(nodes[3],{n for n,_ in chosen['free']})
            self.assertEqual(s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0],2)
            self.assertEqual((self.home/'ten-gis.sqlite3').read_bytes(),original)
        finally:s.close()

    def test_different_id_is_followed_and_located_inside_one_actual_path(self):
        self.set(1,1,'WRONG-ID','매우 긴 다른 코어명 '*20,'on');self.connect_all();before=self.snapshot()
        trace=self.s.trace_core_paths('CORE-A')
        self.assertEqual(len(trace['groups']),1);self.assertEqual(trace['highlight'],set(self.cables))
        self.assertEqual({r['core_id'] for r in trace['rows']},{'CORE-A','WRONG-ID'})
        self.assertEqual([m['slot'] for m in trace['mismatches']],[self.slot(1)])
        self.assertIn('/B/1번',trace['mismatches'][0]['location'])
        self.assertIn('코어ID 불일치',trace['summary']);self.assertFalse(trace['complete'])
        steps=[s for g in trace['groups'] for p in g['paths'] for s in p]
        self.assertEqual(len(steps),3);self.assertTrue(next(s for s in steps if s['cable_id']==self.cables[1])['identity_mismatch'])
        self.assertEqual(self.snapshot(),before)

    def test_temporary_neutral_and_name_differences_auto_ok_without_finalization(self):
        self.set(1,1,'임시-77','중간 이름이 달라도 됨','unknown');self.connect_all()
        trace=self.s.trace_core_paths('CORE-A')
        self.assertTrue(trace['complete']);self.assertEqual(trace['identity_status'],'코어ID 일치')
        self.assertEqual(trace['checks'][self.slot(1)]['identity'],'중립(임시)')
        self.assertFalse(wf.state(self.s).get('field_slot_confirmations'))
        self.assertEqual(wf.completion_report(self.s)['rate'],100)
        self.assertTrue(all(r['local_status']=='OK' for r in wf.FieldSurvey(self.s,self.nodes[1]).report()))

    def test_ok_but_unfinished_stays_in_separate_actual_route_list(self):
        self.apply(1,'A\tB\n1\t1')
        comp=self.audit();self.assertTrue(comp['auto_ok']);self.assertFalse(comp['complete'])
        trace=self.s.trace_core_paths('CORE-A',slot=self.slot(0));self.assertIn('OK · 미완료',trace['summary'])
        rows=wf.field_incomplete_entries(self.s);self.assertEqual(len(rows),2)
        entry=next(r for r in rows if any(m['slot']==self.slot(0) for m in r['members']))
        self.assertEqual(entry['state'],'OK · 미완료');self.assertEqual(entry['count'],2)
        self.assertIn('ok_incomplete',entry['causes']);self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.apply(2,'B\tC\n1\t1');self.assertEqual(wf.field_incomplete_entries(self.s),[])

    def test_signal_rules_allow_unknown_only_or_one_known_kind_but_not_conflicts(self):
        self.connect_all()
        for signal in ('on','off','exception'):
            for i in range(3):self.set(i,1,'CORE-A','같은 ID 이름 다름 '+str(i),signal if i!=1 else 'unknown')
            self.assertTrue(self.audit()['auto_ok']);self.assertTrue(self.audit()['complete'])
        self.set(0,1,'CORE-A','','on');self.set(2,1,'CORE-A','','off')
        self.assertFalse(self.audit()['auto_ok']);self.assertIn('signal',self.audit()['causes'])
        for i in range(3):self.set(i,1,'CORE-A','','unknown')
        self.assertTrue(self.audit()['auto_ok']);self.assertTrue(self.audit()['complete'])
        self.assertNotIn('signal_pending',self.audit()['causes'])
        self.set(1,1,'CORE-A','','error')
        self.assertFalse(self.audit()['auto_ok']);self.assertFalse(self.audit()['complete'])
        self.assertIn('signal',self.audit()['causes'])

    def test_all_unknown_completes_existing_route_without_changing_saved_values(self):
        for i,signal in enumerate(('unknown','','확인필요')):self.set(i,1,'CORE-A','GIS 내역',signal)
        self.connect_all();before=self.snapshot();revision=self.s.data_revision()
        history=self.s.history_rows();gis=self.gis.read_bytes()
        self.assertEqual(wf.completion_report(self.s)['rate'],100)
        self.assertEqual(wf.field_incomplete_entries(self.s),[])
        self.assertTrue(self.s.trace_core_paths('CORE-A')['complete'])
        for i in (1,2):self.assertTrue(all(r['local_status']=='OK' for r in wf.FieldSurvey(self.s,self.nodes[i]).report()))
        for value in self.s.cable_core_warning_summary().values():
            self.assertEqual(value['incomplete_total'],0);self.assertEqual(value['incomplete_badge'],0)
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.s.data_revision(),revision)
        self.assertEqual(self.s.history_rows(),history);self.assertEqual(self.gis.read_bytes(),gis)
        self.s.close();self.s=code['Store'](self.path)
        self.assertEqual(wf.completion_report(self.s)['rate'],100)
        self.assertEqual(self.snapshot(),before)

    def test_all_unknown_still_requires_real_connections_and_preserves_undo(self):
        for i in range(3):self.set(i,1,'CORE-A','GIS 내역','unknown')
        self.apply(1,'A\tB\n1\t1')
        self.assertTrue(self.audit()['auto_ok']);self.assertFalse(self.audit()['complete'])
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertIn('unconnected',self.audit()['causes'])
        self.assertEqual(self.s.trace_core_paths('CORE-A',slot=self.slot(0))['highlight'],set(self.cables[:2]))
        before=self.snapshot();self.apply(2,'B\tC\n1\t1')
        self.assertEqual(wf.completion_report(self.s)['rate'],100)
        self.s.undo();self.assertEqual(self.snapshot(),before)
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.s.redo();self.assertEqual(wf.completion_report(self.s)['rate'],100)
        self.set(1,1,'OTHER','GIS 내역','unknown')
        self.assertFalse(self.audit()['auto_ok']);self.assertIn('identity',self.audit()['causes'])
        self.assertEqual(wf.completion_report(self.s)['done'],0)

    def test_all_unknown_keeps_manual_review_holds_and_rn_endpoints(self):
        for i in range(3):self.set(i,1,'CORE-A','GIS 내역','unknown')
        self.connect_all();nid=self.nodes[1]
        keys={r['key'] for r in wf.FieldSurvey(self.s,nid).report()}
        wf.field_local_mark(self.s,nid,keys,'NOT OK',self.s.data_revision(),getattr(self.s,'_view_generation',0),'직접 확인 필요')
        self.assertFalse(self.audit()['auto_ok']);self.assertEqual(wf.completion_report(self.s)['done'],0)
        wf.field_local_mark(self.s,nid,keys,'OK',self.s.data_revision(),getattr(self.s,'_view_generation',0))
        self.assertEqual(wf.completion_report(self.s)['rate'],100)
        with self.s.action('RN 끝단'):self.s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.nodes[3],))
        self.s.ensure_ports(self.nodes[3],{'mp':1,'sp':1,'p':8})
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertIn(self.nodes[3],{n for n,_ in self.audit()['free']})
        self.s.connect(self.nodes[3],self.slot(2),('PORT:'+self.nodes[3],1))
        self.assertEqual(wf.completion_report(self.s)['rate'],100)

    def test_signal_edit_updates_only_slot_or_immediate_local_peer_and_undo_is_atomic(self):
        self.connect_all();s=self.s
        s.set_core_signal('CORE-A','off',slot=self.slot(0))
        self.assertEqual([s.core(*self.slot(i))['signal'] for i in range(3)],['off','on','on'])
        before=self.snapshot();count=len(s.history_rows())
        changed=s.set_core_signal('CORE-A','exception',slot=self.slot(0),node_id=self.nodes[1])
        self.assertEqual(set(changed),{self.slot(0),self.slot(1)})
        self.assertEqual([s.core(*self.slot(i))['signal'] for i in range(3)],['exception','exception','on'])
        self.assertEqual(len(s.history_rows()),count+1);self.assertFalse(self.audit()['auto_ok'])
        s.undo();self.assertEqual(self.snapshot(),before);s.redo()
        self.assertEqual([s.core(*self.slot(i))['signal'] for i in range(3)],['exception','exception','on'])
        with self.assertRaises(ValueError):s.set_core_signal('CORE-A','on')

    def test_local_signal_follows_actual_peer_even_with_different_id_and_protects_locks(self):
        self.set(1,1,'OTHER','다른 ID','unknown');self.connect_all()
        self.s.set_core_signal('CORE-A','off',slot=self.slot(0),node_id=self.nodes[1])
        self.assertEqual(self.s.core(*self.slot(1))['signal'],'off')
        self.assertEqual(self.s.core(*self.slot(1))['core_id'],'OTHER')
        self.assertEqual(self.s.core(*self.slot(2))['signal'],'on')
        self.s.set_node_locked(self.nodes[2],True);before=self.snapshot()
        with self.assertRaises((ValueError,sqlite3.Error)):self.s.set_core_signal('CORE-A','on',slot=self.slot(0),node_id=self.nodes[1])
        self.assertEqual(self.snapshot(),before)

    def test_identity_moves_and_group_name_edits_preserve_number_signals(self):
        self.set(0,3,'123','3번 내역','on');self.set(0,4,'456','4번 내역','off')
        wf.field_slot_transfer_commit(self.s,wf.field_slot_transfer_preview(self.s,self.slot(0,3),self.slot(0,4)))
        self.assertEqual((self.s.core(*self.slot(0,4))['core_id'],self.s.core(*self.slot(0,4))['signal']),('123','off'))
        self.assertEqual(self.s.core(*self.slot(0,3))['signal'],'on')
        self.set(1,3,'123','별도 구간','exception')
        self.s.rename_core_group('123','123','이름만 확정','normal','','on')
        self.assertEqual(self.s.core(*self.slot(0,4))['signal'],'off');self.assertEqual(self.s.core(*self.slot(1,3))['signal'],'exception')
        self.connect_all();splices=list(self.s.conn.execute('SELECT * FROM splices'))
        self.s.swap_cable_cores(self.cables[0],1,4)
        self.assertEqual(self.s.core(*self.slot(0,4))['signal'],'off');self.assertEqual(self.s.core(*self.slot(0))['signal'],'on')
        self.assertEqual(list(self.s.conn.execute('SELECT * FROM splices')),splices)

    def test_rn_endpoint_and_bad_graph_never_claim_complete(self):
        self.connect_all()
        with self.s.action('RN 끝단'):self.s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.nodes[3],))
        self.s.ensure_ports(self.nodes[3],{'mp':1,'sp':1,'p':8})
        trace=self.s.trace_core_paths('CORE-A');self.assertFalse(trace['complete']);self.assertIn(self.nodes[3],{n for n,_ in trace['free']})
        self.s.connect(self.nodes[3],self.slot(2),('PORT:'+self.nodes[3],1))
        self.assertTrue(self.s.trace_core_paths('CORE-A')['complete'])
        with self.s.action('잘못된 접속 주입'):
            self.s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(self.nodes[0],*self.slot(0),*self.slot(2)))
        self.assertFalse(self.s.trace_core_paths('CORE-A')['complete'])


def windows_ui():
    if sys.platform!='win32':return
    case=CoreTraceTests();case.setUp()
    try:
        (case.home/'ui').mkdir();os.environ['TELECOM_APP_HOME']=str(case.home/'ui');errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showinfo',return_value=None), \
             patch.object(code['messagebox'],'askyesno',return_value=True), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *a:errors.append(str(a))
            try:
                app.replace_current_from(case.path);app.deiconify();app.update();s=app.store
                node=code['NodeDialog'](app,s,case.nodes[1]);node.left_var.set(next(k for k,v in node.by_label.items() if v==case.cables[0]));node.reload_all();app.update()
                node.left_tree.selection_set('1');app.update();assert app.highlight_cables==set(case.cables);assert len(app.highlight_connection_model['groups'])==3
                assert not s.conn.execute('SELECT 1 FROM splices').fetchone()
                trace=code['TraceDialog'](app,s);trace.q.set('CORE-A');trace.run();app.update()
                assert '실제 접속 3구간' in trace.summary.get();assert '미완료' in trace.summary.get()
                trace.close()
                wf.field_overlay_commit(s,wf.field_overlay_preview(s,case.nodes[1],'A\tB\n1\t1'));app.refresh();node.show_core_paths();app.update()
                assert app.highlight_cables==set(case.cables);assert len(app.highlight_connection_model['groups'])==2;assert app.highlight_cable_colors[case.cables[0]]==app.highlight_cable_colors[case.cables[1]];assert app.highlight_cable_colors[case.cables[1]]!=app.highlight_cable_colors[case.cables[2]]
                node.change_core_signal(case.slot(0),'CORE-A','off');app.update()
                assert [s.core(*case.slot(i))['signal'] for i in range(3)]==['off','off','on']
                assert len(wf.field_incomplete_entries(s))==1 # Unallocated OFF component is excluded.
                node.change_core_signal(case.slot(0),'CORE-A','unknown');app.update()
                pending=code['IncompleteCoresDialog'](app,s);app.update();assert pending.field_incomplete
                assert len(pending.entries)==2 and all(r['state']=='OK · 미완료' for r in pending.entries)
                choice=next(str(i) for i,e in enumerate(pending.entries) if any(m['slot']==case.slot(0) for m in e['members']))
                pending.tree.selection_set(choice);app.update();assert len(pending.segment_tree.get_children())==2
                pending.segment_tree.selection_set(pending.segment_tree.get_children()[0]);app.update();assert 'GIS 내역' in pending.details_text.get('1.0','end')
                pending.cause_filter.set('OK·미완료');pending.reload();app.update();assert len(pending.entries)==2
                pending.destroy()
                wf.field_overlay_commit(s,wf.field_overlay_preview(s,case.nodes[2],'B\tC\n1\t1'))
                s.set_core_signal('CORE-A','off',slot=case.slot(1),node_id=case.nodes[2]);app.refresh();app.update()
                assert wf.completion_report(s)['rate']==100.0 and not wf.field_incomplete_entries(s)
                # V78: repaint existing drawings with unknown-only routes as complete.
                for i in range(3):s.set_core_signal('CORE-A','unknown',slot=case.slot(i))
                app.refresh();app.update();before=wf.plan_snapshot(s.conn)
                assert '100.0%' in app.work_progress_rate.cget('text')
                cable=code['CableDialog'](app,s,case.cables[1])
                cable.focus_core(1);app.update()
                assert cable.completion_title.get()=='1 · 연결완료'
                assert cable.completion_box.winfo_x()>cable.lot_entry.winfo_x()+cable.lot_entry.winfo_width()
                assert cable.completion_box.winfo_width()>200
                summary=code['NodeSummaryDialog'](node,s,case.nodes[1])
                survey=wf.FieldSurveyDialog(app,s,case.nodes[1]);app.update()
                pending=code['IncompleteCoresDialog'](app,s);app.update()
                assert not pending.entries
                assert '신호 확인 대기' not in pending.CAUSE_FILTERS
                assert all(r['local_status']=='OK' for r in survey.rows)
                assert '[미완료코어]' not in cable.tree.item('1','values')[0]
                assert cable.tree.item('1','values')[1]=='확인필요'
                summary_row=next(iid for iid,slots in summary.row_slots.items() if case.slot(0) in slots)
                assert summary.tree.set(summary_row,'signal')=='확인필요'
                assert all(w['incomplete_total']==0 for w in s.cable_core_warning_summary().values())
                assert wf.plan_snapshot(s.conn)==before
                s.disconnect(case.nodes[2],*case.slot(1));app.refresh();pending.reload();app.update()
                assert wf.completion_report(s)['done']==0 and pending.entries
                assert '[미완료코어]' in cable.tree.item('1','values')[0]
                assert cable.completion_title.get()=='1 · 미완료'
                # Disconnecting a saved observation leaves both a physical gap
                # and unapplied field evidence; neither reason may be hidden.
                assert cable.completion_reason.get()=='코어연결 미완료 · 현장 선번 확인 필요',cable.completion_reason.get()
                s.undo();app.refresh();pending.reload();app.update()
                assert '100.0%' in app.work_progress_rate.cget('text') and not pending.entries
                assert '[미완료코어]' not in cable.tree.item('1','values')[0]
                assert cable.completion_reason.get()=='연결완료'
                assert all(s.core(*case.slot(i))['signal']=='unknown' for i in range(3))
                assert wf.plan_snapshot(s.conn)==before
                pending.destroy();survey.destroy();summary.destroy()
                cable.notebook.select(cable.identity_tab);cable.identity_tree.selection_set('1');app.update()
                cable.open_identity_editor('1','#3');cable.identity_editor.delete(0,'end');cable.identity_editor.insert(0,'저장 전 입력')
                s.update_core(*case.slot(1),('WRONG-ID','긴 코어내역 '*30,'normal','','off'));app.refresh();app.update()
                assert cable.completion_reason.get()=='코어ID 다름'
                assert cable.identity_editor.get()=='저장 전 입력'
                cable.identity_tree.selection_set('6');app.update()
                assert cable.completion_reason.get()=='미사용 코어' and '코어ID 다름' not in cable.completion_reason.get()
                cable.destroy()
                trace=code['TraceDialog'](app,s);trace.q.set('CORE-A');trace.run();app.update()
                wrong=[iid for iid in trace.tree.get_children() if trace.tree.item(iid,'values')[0]=='WRONG-ID']
                assert len(wrong)==1 and 'mismatch' in trace.tree.item(wrong[0],'tags')
                assert '코어ID 불일치' in trace.summary.get();assert trace.diagram.find_all()
                trace.close();node.destroy()
                for i in (1,2):s.connect(case.nodes[i],case.slot(i-1,2),case.slot(i,2))
                s.connect(case.nodes[1],case.slot(0,3),case.slot(1,3))
                app.display_options['badges']=True;app.display_options['cable_temporary']=True;app.refresh();app.update()
                layout=app.cable_label_layout({r['id']:r for r in s.nodes()},s.cables(),s.cable_core_warning_summary())
                badges={item['id']:[p['text'] for p in item['parts'] if '임시코어' in p['text']] for item in layout}
                assert [badges[c] for c in case.cables]==[['연결완료임시코어 1'],[],['연결완료임시코어 1']]
                canvas_text=[app.canvas.itemcget(i,'text') for i in app.canvas.find_all() if app.canvas.type(i)=='text']
                assert canvas_text.count('연결완료임시코어 1')==2
                assert app.drawing_svg().count('연결완료임시코어 1')==2
                assert code['DISPLAY_LABELS']['cable_temporary']=='연결완료임시코어 표시'
                app.display_options['cable_temporary']=False;app.refresh();app.update()
                assert '연결완료임시코어' not in app.drawing_svg()
                assert not errors,errors
            finally:app.on_close()
        print('PASS Windows field traces, unknown-only completion, selected-core brief reasons/draft preservation, temporary endpoint badges on canvas/SVG and visibility')
    finally:case.tearDown()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CoreTraceTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
