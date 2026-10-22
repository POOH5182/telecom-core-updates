"""V84 accepted exception status, live classification and physical graph preservation."""
import os
import sys
import unittest
from unittest.mock import patch
from check_field_slots import SlotFieldTests,code,wf


class ExceptionTests(unittest.TestCase):
    setUp=SlotFieldTests.setUp
    tearDown=SlotFieldTests.tearDown
    slot=SlotFieldTests.slot
    set=SlotFieldTests.set
    apply=SlotFieldTests.apply
    snapshot=SlotFieldTests.snapshot
    splices=SlotFieldTests.splices

    def mark(self,index=1,labels=None):
        wf.save_annotations(self.s,self.slot(0,index),['예외코어'] if labels is None else labels,'완료 확인 메모')

    def assert_accepted(self):
        report=wf.completion_report(self.s)
        self.assertEqual((report['total'],report['done'],report['excluded']),(1,1,0))
        self.assertEqual(self.s.incomplete_core_entries(),[])
        self.assertFalse(any(self.s.node_assignment_needs(n) for n in self.nodes))
        self.assertFalse(any(r['exception'] or r['incomplete'] or r['need'] for r in self.s.core_analysis()))
        self.assertTrue(all(r['complete'] for r in self.s.core_analysis()))
        self.assertTrue(all(v['incomplete_total']==v['unassigned']==v['error']==0 for v in self.s.cable_core_warning_summary().values()))
        self.assertEqual(wf.core_status_text(self.s,self.s.core(*self.slot(0))),'[완료]')
        self.assertEqual(wf.core_completion_brief(self.s,self.slot(0)),('완료','예외 처리'))

    def test_field_disconnected_exception_counts_complete_undo_reopen_no_rewire(self):
        before=self.snapshot();self.mark();self.assert_accepted()
        self.assertEqual(self.splices(),[]);self.assertEqual(self.snapshot()[2],before[2]);self.assertEqual(self.gis.read_bytes(),self.gis_bytes)
        self.assertFalse(any(c['complete'] for c in wf.field_slot_audit(self.s)['components']))
        read=self.snapshot();self.assert_accepted();self.assertEqual(self.snapshot(),read)
        self.s.undo();self.assertEqual(wf.completion_report(self.s)['done'],0);self.assertTrue(self.s.incomplete_core_entries())
        self.s.redo();self.assert_accepted();self.s.close();self.s=code['Store'](self.path);self.assert_accepted()
        self.mark(labels=[]);self.assertEqual(wf.completion_report(self.s)['done'],0)

    def test_legacy_before_after_exception_and_signal_exception_distinct(self):
        self.s.conn.execute("DELETE FROM meta WHERE key='field_identity_policy'");self.s.conn.commit()
        self.mark();self.assert_accepted()
        self.s.conn.execute("UPDATE meta SET value='after' WHERE key='active_scenario'");self.s.conn.commit();self.assert_accepted()
        self.mark(labels=[])
        for i in range(3):self.set(i,1,'CORE-A','GIS 내역','exception')
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertFalse(wf.core_exception_complete(self.s,self.slot(0)))

    def test_temporary_exception_is_completed_disposition_not_fake_completed_route(self):
        for i in range(3):self.set(i,1,'','','unknown')
        self.set(0,2,'임시-84');self.mark(2)
        report=wf.completion_report(self.s);self.assertEqual((report['total'],report['done']),(1,1))
        self.assertNotIn(self.slot(0,2),wf.completed_temporary_slots(self.s))
        self.assertEqual(wf.core_status_text(self.s,self.s.core(*self.slot(0,2))),'[완료]')
        self.assertEqual(self.s.cable_core_warning_summary()[self.cables[0]]['temporary_complete'],0)
        self.assertEqual(self.s.incomplete_core_entries(),[])

    def test_conflicting_unmarked_identity_still_requires_work(self):
        self.set(1,1,'OTHER','다른 내역','on');self.apply(1,'A\tB\n1\t1');self.mark()
        report=wf.completion_report(self.s);self.assertTrue(report['by_id']['CORE-A']['complete']);self.assertFalse(report['by_id']['OTHER']['complete'])
        comp=wf.field_slot_audit(self.s)['by_slot'][self.slot(0)];self.assertFalse(comp['complete']);self.assertIn('identity',comp['causes'])
        self.assertTrue(self.splices())
        entries=self.s.incomplete_core_entries();self.assertTrue(entries)
        self.assertTrue(all(m['core_id']!='CORE-A' for e in entries for m in e.get('members',[e])))
        self.assertEqual(self.s.cable_core_warning_summary()[self.cables[0]]['incomplete_total'],0)
        self.assertGreater(self.s.cable_core_warning_summary()[self.cables[1]]['incomplete_total'],0)


def windows_ui():
    if sys.platform!='win32':return
    case=ExceptionTests();case.setUp()
    try:
        (case.home/'ui').mkdir()
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error:
            app=code['App']();app.store.close();app.store=case.s;errors=[];app.report_callback_exception=lambda *a:errors.append(str(a))
            try:
                app.refresh();cable=code['open_detail_dialog'](app,case.s,'cable',case.cables[0]);cable.focus_core(1)
                summary=code['NodeSummaryDialog'](app,case.s,case.nodes[1]);checks=code['CoreCheckDialog'](app,case.s)
                case.mark();app.refresh();app.update()
                assert '[완료]' in str(cable.tree.item('1','values'))
                assert any('[완료]' in str(summary.tree.item(i,'values')) for i in summary.tree.get_children())
                for kind,expected in [('예외코어',0),('미완료코어',0),('완료코어',1)]:
                    checks.kind.set(kind);checks.reload();assert len(checks.rows)==expected,(kind,checks.rows)
                case.s.undo();app.refresh();app.update();assert '[완료]' not in str(cable.tree.item('1','values'))
                checks.kind.set('미완료코어');checks.reload();assert checks.rows
                assert not errors,errors;assert not error.called,error.call_args
            finally:app.on_close()
        print('PASS Windows accepted completion cable/enclosure/check filters and undo repaint')
    finally:case.tearDown()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ExceptionTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
