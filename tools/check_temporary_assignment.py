"""V86: temporary cores leave enclosure allocation views without changing routes."""
import os
import sys
import unittest
from unittest.mock import patch
from check_field_slots import SlotFieldTests,code,wf
from check_completion import CompletionTests


class TemporaryFieldTests(unittest.TestCase):
    setUp=SlotFieldTests.setUp
    tearDown=SlotFieldTests.tearDown
    set=SlotFieldTests.set
    slot=SlotFieldTests.slot
    apply=SlotFieldTests.apply
    connect_all=SlotFieldTests.connect_all
    snapshot=SlotFieldTests.snapshot

    def temporary(self,signal='on'):
        for i in range(3):self.set(i,1,'임시-86','임시 내역',signal)

    def assert_no_enclosure_allocation(self):
        for nid in self.nodes:
            if self.s.node(nid)['type']!='hamche':continue
            self.assertEqual(self.s.node_assignment_needs(nid),{})
            self.assertEqual(self.s.waiting_connection_groups(nid),[])
            warning=self.s.node_warning_summary().get(nid,{})
            self.assertEqual(warning.get('count',0),0);self.assertEqual(warning.get('waiting_count',0),0)
        rows=code['node_summary_rows'](self.s,self.nodes[1],self.s.node_cable_choices(self.nodes[1]))
        self.assertTrue(rows);self.assertTrue(all('배정필요' not in r['connection'] for r in rows))

    def test_signals_do_not_restore_temporary_allocation_and_reads_preserve_graph(self):
        for signal in ('on','unknown','off','exception'):
            with self.subTest(signal=signal):
                self.temporary(signal);before=self.snapshot();history=self.s.history_rows()
                self.assert_no_enclosure_allocation()
                report=wf.completion_report(self.s);self.assertEqual(report['done'],0)
                self.assertEqual(report['total'],0 if signal=='off' else 3)
                self.assertEqual(wf.completed_temporary_slots(self.s),frozenset())
                if signal!='off':self.assertGreater(self.s.cable_core_warning_summary()[self.cables[0]]['unassigned'],0)
                self.assertEqual(self.snapshot(),before);self.assertEqual(self.s.history_rows(),history)
                self.assertEqual(self.gis.read_bytes(),self.gis_bytes)

    def test_real_identity_restores_allocation_with_undo_redo_and_reopen(self):
        self.temporary();self.assert_no_enclosure_allocation()
        self.set(0,1,'REAL-86','실제 내역','on')
        self.assertEqual(self.s.node_assignment_needs(self.nodes[1]),{self.cables[0]:{1}})
        self.assertEqual(self.s.node_warning_summary()[self.nodes[1]]['count'],1)
        self.s.undo();self.assert_no_enclosure_allocation();self.s.redo()
        self.assertIn(1,self.s.node_assignment_needs(self.nodes[1])[self.cables[0]])
        self.s.undo();self.s.close();self.s=code['Store'](self.path);self.assert_no_enclosure_allocation()

    def test_rn_still_requires_internal_port_and_temporary_completion_requires_actual_route(self):
        self.temporary()
        with self.s.action('RN 시험 끝단'):
            self.s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.nodes[3],))
            self.s.ensure_ports(self.nodes[3])
        self.assert_no_enclosure_allocation()
        self.assertIn(1,self.s.node_assignment_needs(self.nodes[3])[self.cables[2]])
        self.connect_all();self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertNotIn(self.slot(0),wf.completed_temporary_slots(self.s))
        self.s.connect(self.nodes[3],self.slot(2),('PORT:'+self.nodes[3],1))
        self.assertEqual(wf.completion_report(self.s)['done'],1)
        self.assertIn(self.slot(0),wf.completed_temporary_slots(self.s))


class TemporaryLegacyTests(unittest.TestCase):
    setUp=CompletionTests.setUp
    tearDown=CompletionTests.tearDown
    stage=CompletionTests.stage
    core=CompletionTests.core
    report=CompletionTests.report

    def test_all_stages_hide_temporary_allocation_but_retain_incomplete_path(self):
        self.core(1,'임시-86','on');self.store.update_core(self.right,1,('임시-86','내역 1','normal','','on'))
        for kind in ('gis','before','after'):
            self.stage(kind)
            self.assertEqual(self.store.node_assignment_needs(self.h),{})
            self.assertEqual(self.store.waiting_connection_groups(self.h),[])
            self.assertEqual(self.store.node_warning_summary().get(self.h,{}).get('count',0),0)
            self.assertFalse(self.store.core_analysis()[0]['need'])
            self.assertEqual((self.report()['total'],self.report()['done']),(1,0))
            self.assertTrue(self.store.incomplete_core_entries())
        self.core(1,'REAL-86','on');self.assertIn(1,self.store.node_assignment_needs(self.h)[self.left])


def windows_ui():
    if sys.platform!='win32':return
    case=TemporaryFieldTests();case.setUp()
    try:
        case.temporary();(case.home/'ui').mkdir()
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error:
            app=code['App']();app.store.close();app.store=case.s;errors=[];app.report_callback_exception=lambda *a:errors.append(str(a))
            try:
                app.refresh();node=code['open_detail_dialog'](app,case.s,'node',case.nodes[1])
                summary=code['NodeSummaryDialog'](node,case.s,case.nodes[1]);app.update()
                def check():
                    assert node.assignment_needs()=={}
                    for combo in (node.left_combo,node.right_combo):
                        menu=combo.choice_menu
                        assert not any('배정필요' in menu.entrycget(i,'label') for i in range(menu.index('end')+1) if menu.type(i)=='command')
                    assert all('배정필요' not in str(summary.tree.item(i,'values')) for i in summary.tree.get_children())
                    texts=[app.canvas.itemcget(i,'text') for i in app.canvas.find_all() if app.canvas.type(i)=='text']
                    assert not any('배정필요' in t for t in texts),texts
                    assert '배정필요' not in app.drawing_svg()
                check()
                case.set(0,1,'REAL-86','실제 내역','on');app.refresh();app.update()
                assert node.assignment_needs()=={case.cables[0]:{1}}
                assert any('배정필요' in str(summary.tree.item(i,'values')) for i in summary.tree.get_children())
                case.s.undo();app.refresh();app.update();check()
                assert not errors,errors;assert not error.called,error.call_args
            finally:app.on_close()
        print('PASS Windows temporary enclosure badge/menu/summary/SVG exclusion, real-ID allocation and undo repaint')
    finally:case.tearDown()


if __name__=='__main__':
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (TemporaryFieldTests,TemporaryLegacyTests))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
