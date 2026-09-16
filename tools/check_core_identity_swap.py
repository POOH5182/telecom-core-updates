"""Identity-only exchange and after-only whole-core movement to empty capacity."""
import os
import json
from pathlib import Path
import sys
import tempfile
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


class AfterMoveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.s=code['Store'](self.home/'after.sqlite3');s=self.s
        s.conn.execute("INSERT INTO meta VALUES('active_scenario','after')");s.conn.commit()
        self.nodes=[s.add_node('합성 시설 '+str(i),i*220,0) for i in range(4)]
        self.cables=[s.add_cable(self.nodes[i],self.nodes[i+1],'CABLE-'+str(i),'6C','기설') for i in range(3)]
        with s.action('합성 1-2-3 경로'):
            for owner,index in zip(self.cables,(1,2,3)):
                s.conn.execute("UPDATE cores SET core_id='SYNTH-A',detail='경로 A',signal='unknown' WHERE cable_id=? AND core_index=?",(owner,index))
            s.conn.execute("UPDATE cores SET signal='on' WHERE cable_id=? AND core_index=1",(self.cables[0],))
            s.connect(self.nodes[1],(self.cables[0],1),(self.cables[1],2))
            s.connect(self.nodes[2],(self.cables[1],2),(self.cables[2],3))
        wf.after_auto_activate(s)
        self.original=self.home/'before.sqlite3';s.backup_to(self.original);self.original_bytes=self.original.read_bytes()
    def tearDown(self):self.s.close();self.temp.cleanup()
    def snapshot(self):return wf.plan_snapshot(self.s.conn),wf.state(self.s)
    def exchange(self):return self.s.commit_core_move(self.s.preview_core_move(self.cables[1],2,4))
    def assert_peer(self,node,a,b):
        row=self.s.splice_for(node,*a)
        self.assertIsNotNone(row)
        self.assertEqual({(row['cable1_id'],row['core1_index']),(row['cable2_id'],row['core2_index'])},{a,b})
    def assert_path(self,index=4):
        self.assert_peer(self.nodes[1],(self.cables[0],1),(self.cables[1],index))
        self.assert_peer(self.nodes[2],(self.cables[1],index),(self.cables[2],3))
        self.assertEqual(self.s.component((self.cables[0],1)),{(self.cables[0],1),(self.cables[1],index),(self.cables[2],3)})

    def test_after_123_to_143_moves_both_ends_and_completion_in_one_undo(self):
        s=self.s;c=self.cables;wf.save_annotations(s,(c[1],2),['정상'],'코어 메모 보존')
        with s.action('합성 번호별 신호'):
            s.conn.execute("UPDATE cores SET signal='on' WHERE cable_id=? AND core_index=2",(c[1],))
        before=self.snapshot();history=len(s.history_rows());p=s.preview_core_move(c[1],2,4)
        self.assertTrue(p['after']);self.assertEqual(len(p['splices']),2);self.assertEqual(self.snapshot(),before)
        self.assertTrue(s.commit_core_move(p).exists());self.assert_path()
        self.assertEqual(tuple(s.core(c[1],4)[k] for k in wf.PLAN_FIELDS),p['before'][0])
        self.assertEqual(tuple(s.core(c[1],2)[k] for k in wf.PLAN_FIELDS),p['before'][1])
        self.assertFalse(s.splice_for(self.nodes[1],c[1],2));self.assertFalse(s.splice_for(self.nodes[2],c[1],2))
        self.assertEqual(s.core(c[1],2)['core_id'],'');self.assertEqual(s.core(c[1],4)['core_id'],'SYNTH-A')
        self.assertEqual([s.core(c[1],i)['signal'] for i in (2,4)],['','on'])
        report=wf.completion_report(s);self.assertTrue(report['by_id']['SYNTH-A']['complete'])
        self.assertEqual((report['total'],report['done']),(1,1))
        self.assertEqual(len(s.trace_core_paths('SYNTH-A')['groups']),1)
        self.assertFalse(s.node_assignment_needs(self.nodes[1]).get(c[1]));self.assertFalse(s.node_assignment_needs(self.nodes[2]).get(c[1]))
        after=self.snapshot();self.assertEqual(len(s.history_rows()),history+1)
        self.assertEqual(before[0]['core_annotations'],after[0]['core_annotations'])
        self.assertEqual(before[0]['ports'],after[0]['ports']);self.assertEqual(before[1],after[1])
        self.assertEqual(self.original.read_bytes(),self.original_bytes)
        original_rows={(r['cable_id'],r['core_index']):r for r in before[0]['cores']}
        for row in after[0]['cores']:
            slot=(row['cable_id'],row['core_index'])
            if slot not in ((c[1],2),(c[1],4)):self.assertEqual(row,original_rows[slot])
        s.undo();self.assertEqual(self.snapshot(),before);s.redo();self.assertEqual(self.snapshot(),after)
        path=s.path;s.close();self.s=code['Store'](path);wf.after_auto_activate(self.s)
        self.assertEqual(self.snapshot(),after);self.assert_path()

    def test_occupied_target_reserved_or_wrong_stage_is_refused_without_mutation(self):
        s=self.s;c=self.cables
        for values in (("OTHER","", "unknown","", "unknown"),("","", "unknown","", "on"),("","note", "unknown","", "unknown")):
            with s.action('합성 점유'):s.conn.execute('UPDATE cores SET core_id=?,detail=?,status1=?,status2=?,signal=? WHERE cable_id=? AND core_index=4',(*values,c[1]))
            before=self.snapshot()
            with self.assertRaisesRegex(ValueError,'사용 중'):self.exchange()
            self.assertEqual(self.snapshot(),before)
            s.undo()
        with s.action('합성 빈 번호 접속 점유'):s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(self.nodes[1],c[0],4,c[1],4))
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'사용 중'):self.exchange()
        self.assertEqual(self.snapshot(),before);s.undo()
        data=wf.plan_settings(s);data['fixed_slots'][wf.plan_slot_key((c[1],4))]='예비';wf.plan_save(s,data,'합성 예약')
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'예약'):self.exchange()
        self.assertEqual(self.snapshot(),before);s.undo()
        for stage in ('before','gis'):
            s.conn.execute("UPDATE meta SET value=? WHERE key='active_scenario'",(stage,));s.conn.commit();before=self.snapshot()
            with self.assertRaisesRegex(ValueError,'후도면'):self.exchange()
            self.assertEqual(self.snapshot(),before)

    def test_identity_only_swap_stays_distinct_and_does_not_auto_add_splices(self):
        s=self.s;c=self.cables;before=self.snapshot()
        s.commit_core_identity_swap(s.preview_core_identity_swap(c[1],2,4))
        self.assertEqual(self.snapshot()[0]['splices'],before[0]['splices'])
        self.assertEqual(s.core(c[1],4)['core_id'],'SYNTH-A')
        s.undo();self.assertEqual(self.snapshot(),before)

    def test_partial_route_disconnect_exclusions_follow_core_without_extra_auto_join(self):
        s=self.s;c=self.cables;s.disconnect(self.nodes[2],c[1],2)
        s.toggle_assignment_exception(self.nodes[2],c[1],2)
        before=self.snapshot();self.exchange()
        self.assert_peer(self.nodes[1],(c[0],1),(c[1],4))
        self.assertFalse(s.splice_for(self.nodes[2],c[1],4));self.assertFalse(s.splice_for(self.nodes[2],c[1],2))
        extra=json.loads(s.node(self.nodes[2])['extra_json'])
        self.assertIn(c[1]+'::4',extra['autoSameNumberExcluded']);self.assertNotIn(c[1]+'::2',extra['autoSameNumberExcluded'])
        self.assertIn(c[1]+'::4',extra['assignmentExceptions'])
        self.assertFalse(wf.completion_report(s)['by_id']['SYNTH-A']['complete'])
        s.undo();self.assertEqual(self.snapshot(),before)

    def test_rn_port_reference_moves_but_port_values_and_unrelated_pairs_stay(self):
        s=self.s;c=self.cables
        with s.action('합성 RN 종단'):
            s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.nodes[1],))
            s.conn.execute('DELETE FROM splices WHERE node_id=?',(self.nodes[1],))
            s.conn.execute("INSERT INTO ports VALUES(?,1,'P1','SYNTH-A','RN 내역','normal','','unknown')",(self.nodes[1],))
            s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(self.nodes[1],'PORT:'+self.nodes[1],1,c[1],2))
        before=self.snapshot();self.exchange()
        self.assert_peer(self.nodes[1],('PORT:'+self.nodes[1],1),(c[1],4))
        self.assert_peer(self.nodes[2],(c[1],4),(c[2],3))
        self.assertEqual(before[0]['ports'],self.snapshot()[0]['ports'])
        s.undo();self.assertEqual(self.snapshot(),before)

    def test_stale_tampered_locked_or_insert_failure_never_leaves_half_moved_route(self):
        s=self.s;c=self.cables
        p=s.preview_core_move(c[1],2,4);bad=dict(p,moved_splices=p['moved_splices'][:1]);before=self.snapshot()
        with self.assertRaises(ValueError):s.commit_core_move(bad)
        self.assertEqual(self.snapshot(),before)
        s.disconnect(self.nodes[2],c[1],2);before=self.snapshot()
        with self.assertRaises(ValueError):s.commit_core_move(p)
        self.assertEqual(self.snapshot(),before);s.undo()
        s.set_node_locked(self.nodes[2],True);before=self.snapshot()
        with self.assertRaises(ValueError):self.exchange()
        self.assertEqual(self.snapshot(),before);s.set_node_locked(self.nodes[2],False)
        p=s.preview_core_move(c[1],2,4);before=self.snapshot();history=s.history_rows()
        # Fail at the second endpoint, after the first endpoint has been inserted.
        second=p['moved_splices'][1][0]
        s.conn.execute("CREATE TEMP TRIGGER fail_swap_insert BEFORE INSERT ON splices WHEN NEW.node_id='"+second+"' BEGIN SELECT RAISE(ABORT,'synthetic second endpoint'); END")
        with self.assertRaises(Exception):s.commit_core_move(p)
        self.assertEqual((self.snapshot(),s.history_rows()),(before,history));self.assert_path(2)


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


def windows_move_ui():
    if sys.platform!='win32':return
    for tab in ('status','identity'):
        case=AfterMoveTests();case.setUp()
        try:
            (case.home/'ui').mkdir()
            with patch.dict(os.environ,TELECOM_APP_HOME=str(case.home/'ui')),patch.object(code['messagebox'],'showerror') as error:
                app=code['App']();app.store.close();app.store=case.s;errors=[];app.report_callback_exception=lambda *a:errors.append(str(a))
                try:
                    app.refresh();s=case.s;n=case.nodes;c=case.cables
                    node=code['NodeDialog'](app,s,n[1])
                    node.left_var.set(next(k for k,v in node.by_label.items() if v==c[0]))
                    node.right_var.set(next(k for k,v in node.by_label.items() if v==c[1]));node.reload_all()
                    cable=code['open_detail_dialog'](app,s,'cable',c[1]);cable.focus_core(2);app.update()
                    if tab=='identity':cable.notebook.select(cable.identity_tab);cable.identity_tree.selection_set('2')
                    button=cable.move_core_button if tab=='status' else cable.move_identity_button
                    cable.lot_var.set('unsaved LOT');before=case.snapshot()
                    with patch.object(code['simpledialog'],'askinteger',return_value=4),patch.object(code['messagebox'],'askyesno',return_value=False):button.invoke()
                    assert case.snapshot()==before and cable.lot_var.get()=='unsaved LOT'
                    values=list(cable.identity_tree.item('1','values'));values[2]='unsaved name';cable.identity_tree.item('1',values=values)
                    with patch.object(code['messagebox'],'showinfo'),patch.object(code['simpledialog'],'askinteger') as ask:button.invoke();assert not ask.called
                    assert case.snapshot()==before and cable.identity_tree.item('1','values')[2]=='unsaved name'
                    cable.reload_identity(2);cable.edit_vars[2].set('pending signal')
                    with patch.object(code['messagebox'],'showinfo'),patch.object(code['simpledialog'],'askinteger') as ask:button.invoke();assert not ask.called
                    assert case.snapshot()==before;cable.load_selected()
                    cable.tree.cycle_sort('core_id');cable.identity_tree.cycle_sort('core_id')
                    with patch.object(code['simpledialog'],'askinteger',return_value=4),patch.object(code['messagebox'],'askyesno',return_value=True) as confirm:button.invoke()
                    app.update();case.assert_path();text=confirm.call_args.args[1]
                    assert '양쪽 함체' in text and '합성 시설 1' in text and '합성 시설 2' in text,text
                    assert cable.tree.set('4','core_id')=='SYNTH-A' and cable.tree.set('2','core_id')==''
                    assert cable.identity_tree.set('4','core_id')=='SYNTH-A' and cable.identity_tree.selection()==('4',)
                    assert node.left_tree.item('1','values')[5]=='4번' and node.right_tree.item('2','values')[5]==''
                    assert '이동 완료' in cable.info.get() and cable.lot_var.get()=='unsaved LOT'
                    assert len(app.highlight_connection_model['groups'])==1,app.highlight_connection_model
                    after=case.snapshot();s.undo();app.refresh();app.update();assert case.snapshot()==before
                    assert node.left_tree.item('1','values')[5]=='2번'
                    s.redo();app.refresh();app.update();assert case.snapshot()==after
                    assert node.left_tree.item('1','values')[5]=='4번'
                    node.destroy();node=code['NodeDialog'](app,s,n[2])
                    node.left_var.set(next(k for k,v in node.by_label.items() if v==c[1]))
                    node.right_var.set(next(k for k,v in node.by_label.items() if v==c[2]));node.reload_all();app.update()
                    assert node.left_tree.item('4','values')[5]=='3번' and node.left_tree.item('2','values')[5]==''
                    assert not errors and not error.called,(errors,error.call_args_list)
                    node.destroy()
                finally:app.on_close()
        finally:case.tearDown()
    print('PASS Windows after core move in both tabs, both enclosure peers, one highlighted route, drafts, cancel and undo/redo')


if __name__=='__main__':
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case) for case in (SwapTests,AfterMoveTests))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    windows_move_ui()
