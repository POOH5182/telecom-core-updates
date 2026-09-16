"""Synthetic stale-reference repair and explicit local 1-4-3 to 1-2-3 rewiring."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_after_plan import LocalApp,code,wf,update


def pair(s,n,a,b):
    row=s.splice_for(n,*a)
    return bool(row and {(row['cable1_id'],row['core1_index']),(row['cable2_id'],row['core2_index'])}=={a,b})


def fixture(home,kind='after'):
    app=LocalApp(home);s=app.store
    n=[s.add_node('합성 함체 '+str(i),i*200,0) for i in range(5)]
    c=[s.add_cable(n[i],n[i+1],'CABLE-'+str(i),'12C','기설') for i in range(4)]
    s.conn.execute("UPDATE meta SET value=? WHERE key='active_scenario'",(kind,))
    if kind=='before':s.conn.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('field_identity_policy',wf.FIELD_SLOT_POLICY))
    s.conn.commit()
    return s,n,c


def old_path(s,n,c):
    for owner,index in ((c[0],1),(c[1],4),(c[2],3)):
        update(s,owner,index,dict(core_id='SYNTH-CORE',detail='보존 내역',signal='on'))
    s.connect(n[1],(c[0],1),(c[1],4));s.connect(n[2],(c[1],4),(c[2],3))


class RepairTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.stores=[]
    def tearDown(self):
        for s in self.stores:s.close()
        self.temp.cleanup()
    def make(self,kind='after'):
        home=Path(self.temp.name)/str(len(self.stores));home.mkdir()
        s,n,c=fixture(home,kind);self.stores.append(s);return s,n,c

    def test_each_local_change_removes_old_peer_preserves_far_side_metadata_and_history(self):
        for kind in ('after','before','gis'):
            s,n,c=self.make(kind);old_path(s,n,c)
            if kind=='after':wf.after_auto_activate(s)
            before=wf.plan_snapshot(s.conn);count=len(s.history_rows());old=dict(s.core(c[1],4))
            msg=wf.reconnect_selected(s,n[1],(c[0],1),(c[1],2))
            self.assertIn('이전 접속 해제',msg)
            self.assertTrue(pair(s,n[1],(c[0],1),(c[1],2)))
            self.assertFalse(s.splice_for(n[1],c[1],4))
            self.assertTrue(pair(s,n[2],(c[1],4),(c[2],3)))
            self.assertEqual(dict(s.core(c[1],4)),old)
            self.assertEqual(len(s.history_rows()),count+1)
            self.assertTrue(list((s.path.parent/'backup').glob('before_reconnect_*.sqlite3')))
            first=wf.plan_snapshot(s.conn);s.undo();self.assertEqual(wf.plan_snapshot(s.conn),before)
            s.redo();self.assertEqual(wf.plan_snapshot(s.conn),first)
            wf.reconnect_selected(s,n[2],(c[1],2),(c[2],3))
            self.assertTrue(pair(s,n[2],(c[1],2),(c[2],3)))
            self.assertFalse(s.splice_for(n[2],c[1],4))
            self.assertEqual(dict(s.core(c[1],4)),old)
            s.undo();self.assertEqual(wf.plan_snapshot(s.conn),first)

    def test_ordinary_connect_still_refuses_occupied_and_explicit_failure_rolls_back(self):
        s,n,c=self.make();old_path(s,n,c);before=wf.plan_snapshot(s.conn)
        with self.assertRaises(ValueError):s.connect(n[1],(c[0],1),(c[1],2))
        self.assertEqual(wf.plan_snapshot(s.conn),before)
        update(s,c[1],2,dict(core_id='DIFFERENT'))
        before=wf.plan_snapshot(s.conn);history=s.history_rows()
        with self.assertRaises(ValueError):wf.reconnect_selected(s,n[1],(c[0],1),(c[1],2))
        self.assertEqual((wf.plan_snapshot(s.conn),s.history_rows()),(before,history))
        with self.assertRaises(ValueError):wf.reconnect_selected(s,n[1],(c[0],1),(c[2],2))
        self.assertEqual(wf.plan_snapshot(s.conn),before)

    def test_locked_opposite_cable_blocks_replacement(self):
        s,n,c=self.make();old_path(s,n,c);s.set_node_locked(n[2],True)
        before=wf.plan_snapshot(s.conn);history=s.history_rows()
        with self.assertRaises(ValueError):wf.reconnect_selected(s,n[1],(c[0],1),(c[1],2))
        self.assertEqual((wf.plan_snapshot(s.conn),s.history_rows()),(before,history))

    def broken_route(self,kind='after'):
        s,n,c=self.make(kind);indices=(11,11,7,3)
        for owner,index in zip(c,indices):update(s,owner,index,dict(core_id='SYNTH-ROUTE',detail='보존',signal='unknown'))
        update(s,c[0],11,dict(signal='on'))
        s.connect(n[3],(c[2],7),(c[3],3))
        with s.action('합성 구버전 접속'):
            s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(n[1],c[0],11,'DELETED-CABLE',9))
            s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(n[2],c[2],7,c[3],12))
        s.conn.execute("INSERT INTO meta VALUES('after_same_id_v98','1')");s.conn.commit()
        return s,n,c

    def test_stale_three_components_repair_once_complete_and_undo_reopen(self):
        s,n,c=self.broken_route();before=wf.plan_snapshot(s.conn)
        self.assertEqual(len(wf.Network(s.conn).invalid_splices),2)
        text=wf.core_completion_locations(s,(c[0],11))
        self.assertIn('합성 함체 1',text);self.assertIn('11번',text);self.assertIn('삭제',text)
        count=len(s.history_rows());self.assertEqual(wf.after_auto_activate(s),2)
        self.assertEqual(len(s.history_rows()),count+1)
        self.assertFalse(wf.Network(s.conn).invalid_splices)
        self.assertTrue(wf.completion_report(s)['by_id']['SYNTH-ROUTE']['complete'])
        self.assertEqual(len(s.trace_core_paths('SYNTH-ROUTE')['groups']),1)
        self.assertEqual(s.error_core_summary()['core_count'],0)
        self.assertFalse(s.waiting_connection_groups(n[1]));self.assertFalse(s.node_assignment_needs(n[2]))
        after=wf.plan_snapshot(s.conn)
        for table in before:
            if table!='splices':self.assertEqual(before[table],after[table],table)
        s.undo();self.assertEqual(wf.plan_snapshot(s.conn),before)
        path=s.path;s.close();self.stores.remove(s);s=code['Store'](path);self.stores.append(s)
        self.assertEqual(wf.after_auto_activate(s),0);self.assertEqual(wf.plan_snapshot(s.conn),before)
        s.redo();self.assertEqual(wf.plan_snapshot(s.conn),after)

    def test_invalid_diagnostics_are_specific_read_only_and_locked_references_stay(self):
        s,n,c=self.broken_route();s.set_node_locked(n[1],True)
        before=wf.plan_snapshot(s.conn);history=s.history_rows()
        self.assertIn('SYNTH-ROUTE',{e['core_id'] for e in s.error_core_summary()['entries']})
        notes='\n'.join(s.error_core_groups()[0]['reason_items'])
        self.assertIn('CABLE-0',notes);self.assertIn('11번',notes);self.assertIn('삭제',notes)
        h=wf.core_connection_highlight(s,[(c[0],11)])
        self.assertTrue(any('삭제' in b['text'] for b in h['boundaries']))
        self.assertEqual((wf.plan_snapshot(s.conn),s.history_rows()),(before,history))
        wf.after_auto_activate(s)
        self.assertTrue(s.splice_for(n[1],c[0],11))
        self.assertFalse(wf.completion_report(s)['by_id']['SYNTH-ROUTE']['complete'])

    def test_existing_blank_and_conflicting_real_splices_are_not_deleted(self):
        for peer_id in ('','OTHER'):
            s,n,c=self.make()
            for owner,index in ((c[0],1),(c[1],2)):update(s,owner,index,dict(core_id='SYNTH'))
            with s.action('합성 기존 점유'):
                s.conn.execute("UPDATE cores SET core_id=?,detail='',status1='unknown',status2='',signal='unknown' WHERE cable_id=? AND core_index=4",(peer_id,c[1]))
                s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(n[1],c[0],1,c[1],4))
            self.assertFalse(wf.Network(s.conn).invalid_splices)
            before=wf.plan_snapshot(s.conn);wf.after_auto_activate(s)
            self.assertEqual(wf.plan_snapshot(s.conn),before)
            self.assertTrue(pair(s,n[1],(c[0],1),(c[1],4)))
            text=wf.core_completion_locations(s,(c[0],1))
            self.assertIn('기존 접속',text);self.assertIn('4번',text)

    def test_gis_field_and_manual_disconnect_are_not_auto_repaired(self):
        for kind in ('before','gis'):
            s,n,c=self.broken_route(kind);before=wf.plan_snapshot(s.conn)
            self.assertEqual(wf.after_auto_activate(s),0);self.assertEqual(wf.plan_snapshot(s.conn),before)
        s,n,c=self.make()
        for owner,index in ((c[0],1),(c[1],2)):update(s,owner,index,dict(core_id='SYNTH'))
        s.connect(n[1],(c[0],1),(c[1],2));s.disconnect(n[1],c[0],1)
        wf.after_auto_activate(s);self.assertFalse(s.splice_for(n[1],c[0],1))
        self.assertIn('연결 해제 기록',wf.core_completion_locations(s,(c[0],1)))


def windows_ui():
    if sys.platform!='win32':return
    for kind in ('before','after'):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=str(Path(temp)/'ui')), \
             patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showerror') as error, \
             patch.object(code['messagebox'],'askyesno',return_value=True):
            Path(temp,'ui').mkdir();s,n,c=fixture(temp,kind);old_path(s,n,c);s.close()
            app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
            try:
                app.replace_current_from(Path(temp)/'drawing.sqlite3');app.deiconify();app.update();s=app.store
                node=code['NodeDialog'](app,s,n[1])
                node.left_var.set(next(k for k,v in node.by_label.items() if v==c[0]))
                node.right_var.set(next(k for k,v in node.by_label.items() if v==c[1]))
                node.reload_all();app.update();node.left_tree.selection_set('1');node.right_tree.selection_set('2');app.update()
                before=wf.plan_snapshot(s.conn);node.connect_auto();app.update()
                assert pair(s,n[1],(c[0],1),(c[1],2)) and not s.splice_for(n[1],c[1],4)
                assert pair(s,n[2],(c[1],4),(c[2],3))
                assert node.left_tree.item('1','values')[5]=='2번'
                assert node.right_tree.item('2','values')[5]=='1번'
                assert node.right_tree.item('4','values')[5]==''
                assert '이전 접속 해제' in node.msg.get(),node.msg.get()
                assert node.left_tree.selection()==('1',) and node.right_tree.selection()==('2',)
                after=wf.plan_snapshot(s.conn);s.undo();app.refresh();app.update();assert wf.plan_snapshot(s.conn)==before
                assert node.left_tree.item('1','values')[5]=='4번'
                s.redo();app.refresh();app.update();assert wf.plan_snapshot(s.conn)==after
                assert node.left_tree.item('1','values')[5]=='2번'
                node.destroy();assert not errors and not error.called,(errors,error.call_args_list)
            finally:app.on_close()
    print('PASS Windows selected peer replacement, far enclosure preservation, row selection and undo/redo repaint')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RepairTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS stale references, exact diagnostics, same-ID route recovery and local peer replacement')
