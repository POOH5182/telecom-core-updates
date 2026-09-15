"""OFF allocation exemption, actual-conflict negatives and saved-state repaint."""
import os
import sys
import unittest
from unittest.mock import patch

from check_field_slots import SlotFieldTests,code,wf
from check_completion import CompletionTests


class OffFieldTests(unittest.TestCase):
    setUp=SlotFieldTests.setUp
    tearDown=SlotFieldTests.tearDown
    set=SlotFieldTests.set
    slot=SlotFieldTests.slot
    connect_all=SlotFieldTests.connect_all
    apply=SlotFieldTests.apply
    snapshot=SlotFieldTests.snapshot

    def all_off(self):
        with self.s.action('전체 신호 OFF'):
            for i in range(3):self.set(i,1,'CORE-A','GIS 내역','off')

    def test_off_unused_real_named_and_blank_slots_no_assignment_or_errors(self):
        self.all_off();self.set(0,2,'','이름만 있음','off');self.set(1,3,'','','off')
        before=self.snapshot();revision=self.s.data_revision();history=self.s.history_rows()
        for node in self.nodes:
            self.assertEqual(self.s.node_assignment_needs(node),{})
            self.assertEqual(self.s.waiting_connection_groups(node),[])
        self.assertTrue(all(v['unassigned']==v['incomplete']==v['error']==0 for v in self.s.cable_core_warning_summary().values()))
        report=wf.completion_report(self.s);self.assertEqual((report['total'],report['done']),(0,0))
        self.assertFalse([r for r in self.s.before_drawing_check_rows() if r['level']=='오류'])
        self.assertEqual(wf.FieldSurvey(self.s,self.nodes[1]).report(),[])
        for slot in (self.slot(0),self.slot(0,2),self.slot(1,3)):
            self.assertEqual(wf.core_completion_brief(self.s,slot),('집계 제외','신호 OFF'))
            self.assertFalse(wf.field_slot_audit(self.s)['by_slot'][slot]['complete'])
        rows=code['node_summary_rows'](self.s,self.nodes[1],self.s.node_cable_choices(self.nodes[1]))
        self.assertTrue(rows);self.assertTrue(all('배정필요' not in r['connection'] and '집계 제외' in r['connection'] for r in rows))
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.s.data_revision(),revision);self.assertEqual(self.s.history_rows(),history)
        self.assertEqual(self.gis.read_bytes(),self.gis_bytes)

    def test_off_to_on_unknown_undo_redo_reopen_restores_obligation(self):
        self.all_off();self.set(1,1,'CORE-A','GIS 내역','on')
        self.assertEqual(self.s.node_assignment_needs(self.nodes[1]),{self.cables[1]:{1}})
        self.assertEqual(wf.completion_report(self.s)['total'],1)
        self.s.undo();self.assertEqual(wf.completion_report(self.s)['total'],0)
        self.s.redo();self.assertEqual(wf.completion_report(self.s)['total'],1)
        self.set(1,1,'CORE-A','GIS 내역','unknown');self.assertEqual(wf.completion_report(self.s)['total'],1)
        self.all_off();self.s.close();self.s=code['Store'](self.path)
        self.assertEqual(wf.completion_report(self.s)['total'],0);self.assertEqual(self.s.node_assignment_needs(self.nodes[1]),{})

    def test_off_waiting_same_id_does_not_block_live_path_but_unknown_does(self):
        self.connect_all();self.set(1,3,'CORE-A','미접속 참고값','off')
        self.assertEqual((wf.completion_report(self.s)['total'],wf.completion_report(self.s)['done']),(1,1))
        self.assertEqual(self.s.node_assignment_needs(self.nodes[1]),{})
        self.set(1,3,'CORE-A','미접속 참고값','unknown')
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertIn(3,self.s.node_assignment_needs(self.nodes[1])[self.cables[1]])

    def test_off_free_end_of_required_component_has_no_enclosure_assignment_badge(self):
        self.all_off();self.set(0,1,'CORE-A','GIS 내역','unknown');self.apply(1,'A\tB\n1\t1')
        self.assertEqual(self.s.node_assignment_needs(self.nodes[2]),{})
        self.assertEqual(self.s.node_warning_summary().get(self.nodes[2],{}).get('count',0),0)
        self.assertEqual(self.s.cable_core_warning_summary()[self.cables[1]]['unassigned'],0)
        self.assertFalse(wf.field_slot_audit(self.s)['by_slot'][self.slot(0)]['complete'])

    def test_connected_off_keeps_identity_signal_faults_and_trace_labels(self):
        self.all_off();self.set(1,1,'DIFFERENT','다른 ID','off');self.connect_all()
        audit=wf.field_slot_audit(self.s)['by_slot'][self.slot(0)]
        self.assertTrue(audit['error']);self.assertIn('identity',audit['causes'])
        self.assertFalse(audit['complete']);self.assertTrue(self.s.before_drawing_check_rows())
        self.assertTrue(all(w['error'] for w in self.s.cable_core_warning_summary().values()))
        self.assertIn('코어ID 다름',wf.core_completion_brief(self.s,self.slot(1))[1])
        self.assertTrue(wf.core_conflict_markers(self.s,{self.slot(0)}))
        self.set(1,1,'CORE-A','GIS 내역','on')
        audit=wf.field_slot_audit(self.s)['by_slot'][self.slot(0)]
        self.assertIn('signal',audit['causes']);self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertTrue(all(w['unassigned']==0 for w in self.s.cable_core_warning_summary().values()))
        self.set(1,1,'CORE-A','GIS 내역','off')
        row=wf.FieldSurvey(self.s,self.nodes[1]).report()[0]
        wf.field_local_mark(self.s,self.nodes[1],{row['key']},'NOT OK',self.s.data_revision(),self.s._view_generation,'검토 보류')
        self.assertIn('함체 NOT OK',wf.core_completion_brief(self.s,self.slot(0))[1])
        self.assertTrue([r for r in self.s.before_drawing_check_rows() if r['level']=='오류'])

    def test_off_rn_and_temporary_still_need_actual_ends_for_completed_status(self):
        self.all_off()
        self.s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.nodes[3],));self.s.conn.commit()
        self.assertEqual(self.s.node_assignment_needs(self.nodes[3]),{})
        self.assertFalse([r for r in self.s.before_drawing_check_rows() if r['level']=='오류'])
        for i in range(3):self.set(i,2,'임시-81','','off')
        self.connect_all()
        for i in (1,2):self.s.connect(self.nodes[i],self.slot(i-1,2),self.slot(i,2))
        self.assertNotIn(self.slot(0,2),wf.completed_temporary_slots(self.s))
        self.s.ensure_ports(self.nodes[3]);port=('PORT:'+self.nodes[3],1)
        self.s.update_core(*port,('임시-81','','normal','','off'))
        self.s.connect(self.nodes[3],self.slot(2,2),port)
        self.assertIn(self.slot(0,2),wf.completed_temporary_slots(self.s))
        self.assertEqual(wf.completion_report(self.s)['total'],0)


class OffLegacyTests(unittest.TestCase):
    setUp=CompletionTests.setUp
    tearDown=CompletionTests.tearDown
    stage=CompletionTests.stage
    core=CompletionTests.core
    connect=CompletionTests.connect
    report=CompletionTests.report

    def test_before_after_off_named_temporary_and_no_id_are_excluded(self):
        self.core(1,'REAL','off');self.core(2,'임시-81','off');self.core(3,'','off')
        for stage in ('gis','before','after'):
            self.stage(stage);self.assertEqual(self.report()['total'],0)
            self.assertEqual(self.store.node_assignment_needs(self.h),{})
            self.assertEqual(self.store.waiting_connection_groups(self.h),[])
            self.assertTrue(all(v['unassigned']==v['error']==0 for v in self.store.cable_core_warning_summary().values()))
            self.assertFalse([r for r in self.store.before_drawing_check_rows() if r['level']=='오류'])
        self.core(1,'REAL','on');self.assertEqual(self.report()['total'],1)
        self.assertIn(1,self.store.node_assignment_needs(self.h)[self.left])

    def test_off_connected_identity_error_is_preserved(self):
        self.core(1,'REAL','off');self.connect(1)
        self.store.conn.execute("UPDATE cores SET core_id='OTHER',signal='off' WHERE cable_id=? AND core_index=1",(self.right,));self.store.conn.commit()
        self.assertTrue(self.store.cable_core_warning_summary()[self.left]['error'])
        self.assertTrue([r for r in self.store.before_drawing_check_rows() if r['level']=='오류' and r['category']=='연결·입력 점검'])
        self.assertIn('코어ID 다름',wf.core_completion_brief(self.store,(self.left,1))[1])

    def test_legacy_isolated_off_same_id_does_not_create_split_error(self):
        self.core(1,'REAL','on');self.connect(1)
        # Independent slot signals can be imported from a newer field drawing.
        self.store.conn.execute("UPDATE cores SET core_id='REAL',detail='참고',signal='off' WHERE cable_id=? AND core_index=3",(self.right,));self.store.conn.commit()
        self.assertEqual((self.report()['total'],self.report()['done']),(1,1))
        self.assertTrue(all(v['unassigned']==v['error']==0 for v in self.store.cable_core_warning_summary().values()))


def windows_ui():
    if sys.platform!='win32':return
    case=OffFieldTests();case.setUp()
    try:
        (case.home/'ui').mkdir()
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error:
            app=code['App']();app.store.close();app.store=case.s;s=case.s;errors=[]
            app.report_callback_exception=lambda *args:errors.append(str(args[1]))
            try:
                app.refresh();cable=code['open_detail_dialog'](app,s,'cable',case.cables[0]);cable.focus_core(1)
                node=code['open_detail_dialog'](app,s,'node',case.nodes[1])
                summary=code['NodeSummaryDialog'](node,s,case.nodes[1]);app.update()
                assert cable.completion_reason.get()=='코어연결 미완료'
                case.all_off();app.refresh();app.update()
                assert cable.completion_reason.get()=='신호 OFF'
                assert '[미완료코어]' not in cable.tree.item('1','values')[0]
                assert all(v['unassigned']==0 for v in s.cable_core_warning_summary().values())
                row=next(i for i,slots in summary.row_slots.items() if case.slot(0) in slots)
                assert '집계 제외' in str(summary.tree.item(row,'values'))
                texts=[app.canvas.itemcget(i,'text') for i in app.canvas.find_all() if app.canvas.type(i)=='text']
                assert not any('배정필요' in t or '미배정코어' in t for t in texts),texts
                s.undo();app.refresh();app.update();assert cable.completion_reason.get()=='코어연결 미완료'
                s.redo();app.refresh();app.update();assert cable.completion_reason.get()=='신호 OFF'
                assert not errors,errors;assert not error.called,error.call_args
                summary.destroy()
            finally:app.on_close()
        print('PASS Windows OFF reason, cable status, enclosure summary, drawing badges and undo/redo repaint')
    finally:case.tearDown()


if __name__=='__main__':
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (OffFieldTests,OffLegacyTests))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
