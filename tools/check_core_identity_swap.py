"""V84 explicit two-slot ID/name exchange with topology, drafts and history preservation."""
import os
import sys
import unittest
from unittest.mock import patch
from check_field_slots import SlotFieldTests,code,wf

class SwapTests(unittest.TestCase):
    setUp=SlotFieldTests.setUp
    tearDown=SlotFieldTests.tearDown
    slot=SlotFieldTests.slot
    set=SlotFieldTests.set
    apply=SlotFieldTests.apply
    connect_all=SlotFieldTests.connect_all
    snapshot=SlotFieldTests.snapshot

    def prepare(self):
        self.s.resize_cable(self.cables[0],'36C')
        self.set(0,28,'123','사용 코어','on');self.set(0,29,'임시-900','임시 내역','unknown')
        self.s.connect(self.nodes[1],self.slot(0,28),self.slot(1,2))
        self.s.connect(self.nodes[1],self.slot(0,29),self.slot(1,3))

    def test_exact_28_29_swap_preserves_splices_signals_gis_and_atomic_undo(self):
        self.prepare();before=self.snapshot();history=len(self.s.history_rows())
        preview=self.s.preview_core_identity_swap(self.cables[0],28,29);self.assertEqual(self.snapshot(),before)
        backup=self.s.commit_core_identity_swap(preview);self.assertTrue(backup.exists())
        self.assertEqual([(self.s.core(*self.slot(0,i))['core_id'],self.s.core(*self.slot(0,i))['detail']) for i in (28,29)],[('임시-900','임시 내역'),('123','사용 코어')])
        after=self.snapshot();self.assertEqual(after[0]['splices'],before[0]['splices']);self.assertEqual(after[2],before[2]);self.assertEqual(self.gis.read_bytes(),self.gis_bytes)
        self.assertEqual([self.s.core(*self.slot(0,i))['signal'] for i in (28,29)],['on','unknown'])
        self.assertEqual(len(self.s.history_rows()),history+1)
        self.s.undo();self.assertEqual(self.snapshot(),before);self.s.redo();self.assertEqual(self.snapshot(),after)
        self.s.close();self.s=code['Store'](self.path);self.assertEqual(self.snapshot(),after)

    def test_locks_stale_same_invalid_and_mid_transaction_failure_no_partial_swap(self):
        self.prepare();preview=self.s.preview_core_identity_swap(self.cables[0],28,29)
        self.set(0,1,'CHANGED');before=self.snapshot()
        with self.assertRaises(ValueError):self.s.commit_core_identity_swap(preview)
        self.assertEqual(self.snapshot(),before)
        for first,second in ((28,28),(28,37)):
            with self.assertRaises(ValueError):self.s.preview_core_identity_swap(self.cables[0],first,second)
        self.s.set_node_locked(self.nodes[1],True)
        with self.assertRaises(ValueError):self.s.preview_core_identity_swap(self.cables[0],28,29)
        self.s.set_node_locked(self.nodes[1],False);preview=self.s.preview_core_identity_swap(self.cables[0],28,29);before=self.snapshot()
        self.s.conn.execute("CREATE TEMP TRIGGER fail_swap BEFORE UPDATE OF core_id ON cores WHEN NEW.core_index=29 BEGIN SELECT RAISE(ABORT,'synthetic second write'); END")
        with self.assertRaises(Exception):self.s.commit_core_identity_swap(preview)
        self.assertEqual(self.snapshot(),before)

    def test_legacy_swap_is_identity_only_and_preserves_annotations(self):
        self.prepare();self.s.conn.execute("DELETE FROM meta WHERE key='field_identity_policy'");self.s.conn.commit()
        self.assertFalse(wf.field_slot_mode(self.s));wf.save_annotations(self.s,self.slot(0,28),['정상'],'원래 메모')
        before=self.snapshot();self.s.commit_core_identity_swap(self.s.preview_core_identity_swap(self.cables[0],28,29));after=self.snapshot()
        for table in before[0]:
            if table not in ('cores','meta'):self.assertEqual(before[0][table],after[0][table],table)
        self.s.undo();self.assertEqual(self.snapshot(),before)


def windows_ui():
    if sys.platform!='win32':return
    case=SwapTests();case.setUp()
    try:
        case.prepare();(case.home/'ui').mkdir()
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error:
            app=code['App']();app.store.close();app.store=case.s;errors=[];app.report_callback_exception=lambda *a:errors.append(str(a))
            try:
                app.refresh();cable=code['open_detail_dialog'](app,case.s,'cable',case.cables[0]);cable.focus_core(28);app.update()
                cable.lot_var.set('unsaved LOT');before=case.snapshot()
                with patch.object(code['simpledialog'],'askinteger',return_value=29),patch.object(code['messagebox'],'askyesno',return_value=False):cable.swap_identity_button.invoke()
                assert case.snapshot()==before and cable.lot_var.get()=='unsaved LOT'
                values=list(cable.identity_tree.item('2','values'));values[2]='unsaved name';cable.identity_tree.item('2',values=values)
                with patch.object(code['messagebox'],'showinfo'),patch.object(code['simpledialog'],'askinteger') as number:cable.swap_identity_button.invoke();assert not number.called
                assert cable.identity_tree.item('2','values')[2]=='unsaved name' and case.snapshot()==before
                cable.reload_identity();cable.tree.cycle_sort('core_id')
                cable.focus_core(28)
                with patch.object(code['simpledialog'],'askinteger',return_value=29),patch.object(code['messagebox'],'askyesno',return_value=True) as confirm:cable.swap_identity_button.invoke();assert '123' in confirm.call_args.args[1]
                app.update();assert case.s.core(*case.slot(0,29))['core_id']=='123';assert cable.tree.set('29','core_id')=='123'
                assert cable.lot_var.get()=='unsaved LOT';assert cable.identity_tree.set('29','core_id')=='123'
                case.s.undo();app.refresh();app.update();assert cable.tree.set('28','core_id')=='123';assert cable.lot_var.get()=='unsaved LOT'
                assert not errors,errors;assert not error.called,error.call_args
            finally:app.on_close()
        print('PASS Windows direct 28/29 swap button, concrete preview/cancel, pending draft guard, header preservation, live rows and undo')
    finally:case.tearDown()

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SwapTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
