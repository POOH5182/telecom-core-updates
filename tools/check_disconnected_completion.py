"""V87: OFF and non-ON broken exclusion, physical topology and live repaint."""
import os
import sys
import unittest
from unittest.mock import patch
from check_field_slots import SlotFieldTests,code,wf
from check_completion import CompletionTests


class DisconnectedFieldTests(unittest.TestCase):
    setUp=SlotFieldTests.setUp
    tearDown=SlotFieldTests.tearDown
    slot=SlotFieldTests.slot
    snapshot=SlotFieldTests.snapshot
    connect_all=SlotFieldTests.connect_all
    apply=SlotFieldTests.apply

    def mark(self,signal='unknown',status='broken',identity='CORE-A'):
        with self.s.action('끊김 신호 시험'):
            for i in range(3):
                self.s.update_core(*self.slot(i),(identity,'내역',status,'',signal))

    def assert_excluded(self,expected=0):
        report=wf.completion_report(self.s)
        self.assertEqual((report['total'],report['done']),(expected,expected))
        self.assertEqual(self.s.incomplete_core_entries(),[])
        self.assertTrue(all(not self.s.node_assignment_needs(n) for n in self.nodes))
        self.assertTrue(all(v['incomplete_total']==v['unassigned']==v['error']==0 for v in self.s.cable_core_warning_summary().values()))
        self.assertIn('[집계 제외]',wf.core_status_text(self.s,self.s.core(*self.slot(0))))
        self.assertEqual(wf.core_completion_brief(self.s,self.slot(0))[0],'집계 제외')
        self.assertTrue(all(not r['complete'] and not r['incomplete'] and not r['need'] for r in self.s.core_analysis()))

    def test_non_on_broken_and_off_excluded_without_rewiring(self):
        for signal,status in [('unknown','broken'),('','broken'),('exception','broken'),('off','normal'),('off','broken')]:
            with self.subTest(signal=signal,status=status):
                self.mark(signal,status);before=self.snapshot();history=self.s.history_rows()
                self.assert_excluded()
                self.assertFalse(any(c['complete'] for c in wf.field_slot_audit(self.s)['components']))
                self.assertEqual(wf.completed_temporary_slots(self.s),frozenset())
                self.assertEqual(self.snapshot(),before);self.assertEqual(self.s.history_rows(),history)
                self.assertEqual(self.gis.read_bytes(),self.gis_bytes)
                self.assertFalse([r for r in self.s.before_drawing_check_rows() if r['level']=='오류'])

    def test_on_break_removal_undo_reopen_recomputes(self):
        self.mark();self.assert_excluded()
        self.s.update_core(*self.slot(1),('CORE-A','내역','broken','','on'))
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertEqual(wf.core_completion_brief(self.s,self.slot(1))[0],'미완료')
        self.assertEqual(wf.core_status_text(self.s,self.s.core(*self.slot(1))),'[끊김]')
        self.assertIn(1,self.s.node_assignment_needs(self.nodes[1])[self.cables[1]])
        entries=self.s.incomplete_core_entries();self.assertTrue(entries)
        self.assertEqual({m['slot'] for e in entries for m in e.get('members',[e])},{self.slot(1)})
        self.s.undo();self.assert_excluded();self.s.redo();self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.s.undo();self.s.close();self.s=code['Store'](self.path);self.assert_excluded()
        self.mark('unknown','normal');self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.s.undo();self.assert_excluded()

    def test_blank_and_temporary_off_excluded_without_completed_temporary_path(self):
        for identity in ('','임시-87'):
            self.mark('off','normal',identity);self.assert_excluded()
            self.assertEqual(wf.completed_temporary_slots(self.s),frozenset())
            self.assertTrue(all(v['temporary_complete']==0 for v in self.s.cable_core_warning_summary().values()))
        self.mark('on','broken','임시-87')
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertTrue(self.s.incomplete_core_entries())

    def test_rn_non_on_excluded_but_on_still_requires_port(self):
        self.s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.nodes[-1],));self.s.conn.commit()
        self.mark('off','normal');self.assert_excluded()
        self.assertFalse(any(c['complete'] for c in wf.field_slot_audit(self.s)['components']))
        self.mark('on','broken');self.connect_all()
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertTrue(self.s.node_assignment_needs(self.nodes[-1]))

    def test_actual_identity_signal_marked_faults_not_erased(self):
        self.mark('off','normal');self.connect_all()
        self.s.update_core(*self.slot(1),('OTHER','다른 ID','normal','','off'))
        self.assertEqual(wf.completion_report(self.s)['total'],0)
        self.assertIn('코어ID 다름',wf.core_completion_brief(self.s,self.slot(1))[1])
        self.mark('off','normal');self.s.update_core(*self.slot(1),('CORE-A','내역','normal','','on'))
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertIn('신호 불일치',wf.core_completion_brief(self.s,self.slot(0))[1])
        self.mark('unknown','broken');wf.save_annotations(self.s,self.slot(0),['끊김','오류코어'],'확인 필요')
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertTrue(any(v['error'] for v in self.s.cable_core_warning_summary().values()))

    def test_saved_unconnected_observation_is_excluded_but_explicit_hold_remains(self):
        self.mark('off','normal')
        wf.FieldSurvey(self.s,self.nodes[1]).save('A\tB\n1\t1')
        self.assert_excluded()
        rows=wf.FieldSurvey(self.s,self.nodes[1]).report(compare=False)
        self.assertTrue(rows);self.assertTrue(all('현장 선번' in r['local_reason'] for r in rows))
        self.assertEqual(list(self.s.conn.execute('SELECT * FROM splices')),[])
        row=rows[0]
        wf.field_local_mark(self.s,self.nodes[1],{row['key']},'NOT OK',self.s.data_revision(),self.s._view_generation,'별도 확인')
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertIn('함체 NOT OK',wf.core_completion_brief(self.s,self.slot(0))[1])


class DisconnectedLegacyTests(unittest.TestCase):
    setUp=CompletionTests.setUp
    tearDown=CompletionTests.tearDown
    stage=CompletionTests.stage
    core=CompletionTests.core
    report=CompletionTests.report

    def test_excluded_spliced_path_does_not_create_split_on_live_path(self):
        s=self.store;self.core(1,'SHARED','on');s.connect(self.h,(self.left,1),(self.right,1))
        self.core(3,'SPARE','off');s.connect(self.h,(self.left,3),(self.right,3))
        # Imported slot identities/signals can differ even on a shared ID.
        with s.action('미사용 경로 내역 시험'):
            s.conn.execute("UPDATE cores SET core_id='SHARED',signal='off' WHERE core_index=3")
        self.assertEqual((self.report()['total'],self.report()['done']),(1,1))
        self.assertFalse(s.incomplete_core_entries())
        self.assertTrue(all(v['error']==0 for v in s.cable_core_warning_summary().values()))

    def test_all_stages_exclude_broken_non_on_and_off_but_on_is_incomplete(self):
        self.core(1,'BROKEN','unknown','broken');self.core(2,'OFF','off');self.core(3,'LIVE','on','broken')
        for stage in ('gis','before','after'):
            with self.subTest(stage=stage):
                self.stage(stage);report=self.report()
                self.assertEqual((report['total'],report['done']),(1,0))
                self.assertEqual({r['core_id'] for r in self.store.incomplete_core_groups()},{'LIVE'})
                self.assertEqual(self.store.node_assignment_needs(self.h),{self.left:{3}})
                self.assertEqual(wf.core_status_text(self.store,self.store.core(self.left,1)),'[집계 제외] [끊김]')
                self.assertNotEqual(wf.core_status_text(self.store,self.store.core(self.left,3)),'[완료]')
                self.assertTrue(all('BROKEN'!=r['core_id'] for r in self.store.before_drawing_check_rows() if r['level']=='오류'))
        self.core(1,'BROKEN','on','broken');self.assertEqual((self.report()['total'],self.report()['done']),(2,0))
        self.store.undo();self.assertEqual((self.report()['total'],self.report()['done']),(1,0))


def windows_ui():
    if sys.platform!='win32':return
    case=DisconnectedFieldTests();case.setUp()
    try:
        (case.home/'ui').mkdir()
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error:
            app=code['App']();app.store.close();app.store=case.s;errors=[];app.report_callback_exception=lambda *a:errors.append(str(a))
            try:
                app.refresh();cable=code['open_detail_dialog'](app,case.s,'cable',case.cables[0]);cable.focus_core(1)
                node=code['open_detail_dialog'](app,case.s,'node',case.nodes[1])
                summary=code['NodeSummaryDialog'](node,case.s,case.nodes[1]);checks=code['CoreCheckDialog'](app,case.s)
                cable.identity_tree.item('1',values=(1,'CORE-A','저장 전 초안'))
                def check_excluded(reason):
                    app.refresh();app.update()
                    assert '[집계 제외]' in cable.tree.item('1','values')[0]
                    assert reason in cable.completion_reason.get(),cable.completion_reason.get()
                    assert '대상 없음' in app.work_progress_rate.cget('text')
                    assert all('배정필요' not in str(summary.tree.item(i,'values')) for i in summary.tree.get_children())
                    checks.kind.set('미완료코어');checks.reload();assert not checks.rows
                    checks.kind.set('완료코어');checks.reload();assert not checks.rows
                    assert '배정필요' not in app.drawing_svg()
                    assert cable.identity_tree.item('1','values')[2]=='저장 전 초안'
                case.mark();check_excluded('끊김')
                case.mark('on');app.refresh();app.update()
                assert '[미완료코어]' in str(cable.tree.item('1','values'))
                assert '코어연결 미완료' in cable.completion_reason.get()
                assert '0.0%' in app.work_progress_rate.cget('text')
                assert node.assignment_needs()
                case.s.undo();check_excluded('끊김')
                case.mark('off','normal');check_excluded('OFF')
                case.s.undo();check_excluded('끊김')
                assert not errors,errors;assert not error.called,error.call_args
            finally:app.on_close()
        print('PASS Windows disconnected exclusion: OFF/non-ON broken, ON still incomplete, counts/summary/filters/SVG/drafts and undo repaint')
    finally:case.tearDown()


if __name__=='__main__':
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in (DisconnectedFieldTests,DisconnectedLegacyTests))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
