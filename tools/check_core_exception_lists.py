"""V167: 미완료+오류 counts once (as 오류), 예외로 빼기 keeps signal/splices, yellow cable rows."""
import os
import sys
import unittest
from unittest.mock import patch
from check_field_slots import SlotFieldTests,code,wf


class CoreExceptionListTests(unittest.TestCase):
    setUp=SlotFieldTests.setUp
    tearDown=SlotFieldTests.tearDown
    slot=SlotFieldTests.slot
    set=SlotFieldTests.set
    apply=SlotFieldTests.apply
    splices=SlotFieldTests.splices

    def lists(self):
        inc={tuple(e['slot']) for e in self.s.incomplete_core_entries()}
        err={tuple(e['slot']) for e in self.s.error_core_summary()['entries']}
        return inc,err

    def test_incomplete_and_error_never_overlap(self):
        self.set(1,1,'OTHER','다른 내역','on');self.apply(1,'A\tB\n1\t1')
        inc,err=self.lists();self.assertTrue(err);self.assertFalse(inc&err)
        self.assertEqual(err,set(self.s.error_core_slots()))
        for value in self.s.cable_core_warning_summary().values():
            self.assertFalse(value['incomplete_total'] and value['error'],value)
        self.assertFalse(any(m['slot'] in err for e in wf.field_incomplete_entries(self.s) for m in e['members']))

    def test_mark_exception_keeps_signal_and_splices_and_undo(self):
        inc,err=self.lists();self.assertEqual(len(inc),3);self.assertFalse(err)
        before_splices=self.splices();before_signals=[self.s.core(*self.slot(i))['signal'] for i in range(3)]
        self.assertEqual(self.s.set_cores_exception([self.slot(0)],True),['CORE-A'])
        self.assertEqual(self.lists(),(set(),set()))
        self.assertEqual([self.s.core(*self.slot(i))['signal'] for i in range(3)],before_signals)
        self.assertEqual(before_signals,['on']*3);self.assertEqual(self.splices(),before_splices)
        self.assertTrue(any(r['exception'] for r in self.s.core_analysis() if r['core_id']=='CORE-A'))
        self.assertEqual(self.s.set_cores_exception([self.slot(1)],True),[])
        self.s.undo();self.assertEqual(len(self.lists()[0]),3)
        self.s.redo();self.assertEqual(self.lists(),(set(),set()))
        self.assertEqual(self.s.set_cores_exception(self.s.core_id_slots(['CORE-A']),False),['CORE-A'])
        self.assertEqual(len(self.lists()[0]),3)

    def test_exception_keeps_other_labels_and_memo(self):
        wf.save_annotations(self.s,self.slot(0),['내역없음'],'메모')
        self.s.set_cores_exception([self.slot(0)],True)
        row=self.s.core(*self.slot(0));self.assertEqual(row['annotation_labels'][:2],['예외코어','내역없음']);self.assertEqual(row['annotation_memo'],'메모')
        self.s.set_cores_exception([self.slot(0)],False)
        row=self.s.core(*self.slot(0));self.assertEqual(row['annotation_labels'],['내역없음']);self.assertEqual(row['annotation_memo'],'메모')


def windows_ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    case=CoreExceptionListTests();case.setUp()
    try:
        (case.home/'ui').mkdir()
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error,\
             patch.object(code['messagebox'],'askyesno',return_value=True),patch.object(code['messagebox'],'showinfo'):
            app=code['App']();app.store.close();app.store=case.s;errors=[];app.report_callback_exception=lambda *a:errors.append(str(a))
            try:
                app.refresh();cable=code['open_detail_dialog'](app,case.s,'cable',case.cables[0]);app.update()
                assert 'core_issue' in cable.tree.item('1','tags'),cable.tree.item('1','tags')
                assert 'core_issue' in cable.identity_tree.item('1','tags')
                assert 'core_issue' not in cable.tree.item('2','tags')
                listing=code['IncompleteCoresDialog'](app,case.s);app.update()
                assert listing.entries;listing.tree.selection_set('0');listing.mark_exception();app.update()
                assert not listing.entries,listing.entries
                cable.reload();app.update()
                assert 'core_issue' not in cable.tree.item('1','tags'),cable.tree.item('1','tags')
                assert case.s.core(*case.slot(0))['signal']=='on'
                checks=code['CoreCheckDialog'](app,case.s);checks.kind.set('예외코어');checks.reload();app.update()
                assert len(checks.rows)==1,checks.rows
                checks.tree.selection_set(checks.tree.get_children()[0]);checks.set_exception(False);app.update()
                checks.kind.set('미완료코어');checks.reload();assert checks.rows
                cable.reload();app.update();assert 'core_issue' in cable.tree.item('1','tags')
                assert not errors,errors;assert not error.called,error.call_args
            finally:app.on_close()
        print('PASS Windows yellow cable rows, list 예외로 빼기 and 예외 해제')
    finally:case.tearDown()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CoreExceptionListTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS core exception lists')
