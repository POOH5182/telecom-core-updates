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

    def test_signal_rules_allow_one_known_kind_with_unknown_but_not_mixed_or_all_unknown(self):
        self.connect_all()
        for signal in ('on','off','exception'):
            for i in range(3):self.set(i,1,'CORE-A','같은 ID 이름 다름 '+str(i),signal if i!=1 else 'unknown')
            self.assertTrue(self.audit()['auto_ok']);self.assertTrue(self.audit()['complete'])
        self.set(0,1,'CORE-A','','on');self.set(2,1,'CORE-A','','off')
        self.assertFalse(self.audit()['auto_ok']);self.assertIn('signal',self.audit()['causes'])
        for i in range(3):self.set(i,1,'CORE-A','','unknown')
        self.assertFalse(self.audit()['auto_ok']);self.assertIn('signal_pending',self.audit()['causes'])

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
                node.left_tree.selection_set('1');app.update();assert app.highlight_cables=={case.cables[0]}
                assert not s.conn.execute('SELECT 1 FROM splices').fetchone()
                trace=code['TraceDialog'](app,s);trace.q.set('CORE-A');trace.run();app.update()
                assert '경로 3개' in trace.summary.get();assert '미완료' in trace.summary.get()
                trace.close()
                wf.field_overlay_commit(s,wf.field_overlay_preview(s,case.nodes[1],'A\tB\n1\t1'));app.refresh();node.show_core_paths();app.update()
                assert app.highlight_cables==set(case.cables[:2])
                node.change_core_signal(case.slot(0),'CORE-A','off');app.update()
                assert [s.core(*case.slot(i))['signal'] for i in range(3)]==['off','off','on']
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
                s.update_core(*case.slot(1),('WRONG-ID','긴 코어내역 '*30,'normal','','off'));app.refresh()
                trace=code['TraceDialog'](app,s);trace.q.set('CORE-A');trace.run();app.update()
                wrong=[iid for iid in trace.tree.get_children() if trace.tree.item(iid,'values')[0]=='WRONG-ID']
                assert len(wrong)==1 and 'mismatch' in trace.tree.item(wrong[0],'tags')
                assert '코어ID 불일치' in trace.summary.get();assert trace.diagram.find_all()
                trace.close();node.destroy();assert not errors,errors
            finally:app.on_close()
        print('PASS Windows V75 partial actual highlights, ID mismatch trace rows, local paired signals, compact incomplete ledger, full names and auto completion')
    finally:case.tearDown()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CoreTraceTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
