"""Explicit temporary joins unify physical routes and preserve real identities."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_field_survey import code,wf


def fixture(path,kind='before'):
    s=code['Store'](path)
    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario',?)",(kind,))
    if kind=='before':s.conn.execute("INSERT OR REPLACE INTO meta VALUES('field_identity_policy',?)",(wf.FIELD_SLOT_POLICY,))
    s.conn.commit()
    nodes=[s.add_node('합성 함체 '+str(i),i*180,0) for i in range(5)]
    cables=[s.add_cable(nodes[i],nodes[i+1],chr(65+i),'6C','기설') for i in range(4)]
    # Reproduce a saved drawing: REAL--temp3 and temp4--temp4, with one gap.
    with s.action('합성 저장 경로'):
        for i,cid in enumerate(('REAL-CORE','임시-3','임시-4','임시-4')):
            s.conn.execute("UPDATE cores SET core_id=?,detail=?,status1='normal',signal=? WHERE cable_id=? AND core_index=1",
                           (cid,'보존 내역 '+str(i),('on','unknown','off','unknown')[i],cables[i]))
        for n,l,r in ((1,0,1),(3,2,3)):
            a,b=sorted(((cables[l],1),(cables[r],1)))
            s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(nodes[n],*a,*b))
        s.conn.execute("UPDATE cores SET core_id='임시-4',detail='분리된 다른 코어',signal='error' WHERE cable_id=? AND core_index=6",(cables[0],))
    return s,nodes,cables


class TemporaryMergeTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);self.stores=[]
    def tearDown(self):
        for s in self.stores:s.close()
        self.temp.cleanup()
    def make(self,kind='before'):
        s,n,c=fixture(self.home/(kind+str(len(self.stores))+'.sqlite3'),kind);self.stores.append(s);return s,n,c
    def snapshot(self,s):return wf.plan_snapshot(s.conn),wf.state(s)
    def ids(self,s,c):return [s.core(cid,1)['core_id'] for cid in c]
    def metadata(self,s,c):return [tuple(s.core(cid,1)[k] for k in ('detail','status1','status2','signal')) for cid in c]

    def test_user_route_real_identity_metadata_isolated_slot_and_single_undo(self):
        for kind in ('before','after','gis'):
            with self.subTest(kind=kind):
                s,n,c=self.make(kind);before=self.snapshot(s);meta=self.metadata(s,c);history=len(s.history_rows())
                # Warm the signal and component caches before the mutation.
                wf.core_id_signal_summary(s,(c[1],1));s.component((c[1],1))
                result=s.connect(n[2],(c[1],1),(c[2],1))
                self.assertIn('임시코어3으로 통합',result)
                self.assertEqual(self.ids(s,c),['REAL-CORE','임시-3','임시-3','임시-3'])
                self.assertEqual(self.metadata(s,c),meta)
                self.assertEqual(s.core(c[0],6)['core_id'],'임시-4')
                self.assertEqual(wf.core_id_signal_summary(s,(c[1],1))['signal'],'off')
                self.assertEqual(len(s.history_rows()),history+1)
                after=self.snapshot(s);self.assertNotEqual(before,after)
                s.undo();self.assertEqual(self.snapshot(s),before)
                s.redo();self.assertEqual(self.snapshot(s),after)
                path=s.path;s.close();self.stores.remove(s)
                reopened=code['Store'](path);self.stores.append(reopened)
                self.assertEqual(self.snapshot(reopened),after)

    def test_left_source_wins_independent_of_cable_id_sort(self):
        for kind in ('before','after'):
            s,n,c=self.make(kind);s.connect(n[2],(c[2],1),(c[1],1))
            self.assertEqual(self.ids(s,c),['REAL-CORE','임시-4','임시-4','임시-4'])

    def test_reconnecting_existing_pair_repairs_temps_but_opening_does_not(self):
        for kind in ('before','after'):
            s,n,c=self.make(kind)
            with s.action('구버전 혼합 임시 경로'):
                a,b=sorted(((c[1],1),(c[2],1)));s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(n[2],*a,*b))
            before=self.snapshot(s);path=s.path;s.close();self.stores.remove(s)
            s=code['Store'](path);self.stores.append(s);self.assertEqual(self.snapshot(s),before)
            s.connect(n[2],(c[1],1),(c[2],1));self.assertEqual(self.ids(s,c),['REAL-CORE','임시-3','임시-3','임시-3'])
            self.assertEqual(s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0],3)
            s.undo();self.assertEqual(self.snapshot(s),before)

    def test_annotations_memos_phases_follow_merge_and_undo(self):
        s,n,c=self.make()
        wf.save_annotations(s,(c[1],1),['왼쪽 표식'],'왼쪽 메모')
        wf.save_annotations(s,(c[2],1),['오른쪽 표식'],'오른쪽 메모')
        value=wf.state(s);value['phases']=[dict(id='merge',name='합성 차수',cores=['임시-4'],excluded_cores=['임시-4'],cables=[],note='보존')]
        wf.write_state(s,value,'합성 차수')
        before=self.snapshot(s);s.connect(n[2],(c[1],1),(c[2],1))
        merged=s.core(c[1],1);isolated=s.core(c[0],6)
        self.assertEqual(set(merged['annotation_labels']),{'왼쪽 표식','오른쪽 표식'})
        self.assertEqual(set(merged['annotation_memo'].splitlines()),{'왼쪽 메모','오른쪽 메모'})
        self.assertEqual(isolated['annotation_memo'],'오른쪽 메모')
        phase=wf.state(s)['phases'][0]
        self.assertEqual(set(phase['cores']),{'임시-3','임시-4'})
        self.assertEqual(set(phase['excluded_cores']),{'임시-3','임시-4'})
        s.undo();self.assertEqual(self.snapshot(s),before)

    def test_remote_lock_rolls_back_new_splice_and_all_identity_changes(self):
        for kind in ('before','after'):
            s,n,c=self.make(kind);s.set_node_locked(n[4],True);before=self.snapshot(s);history=s.history_rows()
            with self.assertRaises(ValueError):s.connect(n[2],(c[1],1),(c[2],1))
            self.assertEqual(self.snapshot(s),before);self.assertEqual(s.history_rows(),history)

    def test_rn_port_in_actual_route_is_merged_and_real_port_is_preserved(self):
        for kind in ('before','after'):
            s,n,c=self.make(kind)
            with s.action('합성 RN 포트'):
                s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(n[4],))
                s.conn.execute("INSERT INTO ports VALUES(?,1,'P1','임시-4','포트 내역','normal','','unknown')",(n[4],))
                a,b=sorted(((c[3],1),('PORT:'+n[4],1)));s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(n[4],*a,*b))
            before=self.snapshot(s);s.connect(n[2],(c[1],1),(c[2],1))
            port=s.core('PORT:'+n[4],1);self.assertEqual((port['core_id'],port['detail'],port['signal']),('임시-3','포트 내역','unknown'))
            s.undo();self.assertEqual(self.snapshot(s),before)
            with s.action('실제 RN 포트'):
                s.conn.execute("UPDATE ports SET core_id='REAL-CORE' WHERE node_id=?",(n[4],))
            s.connect(n[2],(c[1],1),(c[2],1));self.assertEqual(s.core('PORT:'+n[4],1)['core_id'],'REAL-CORE')

    def test_blank_field_slot_inherits_selected_temp_without_changing_real(self):
        s,n,c=self.make();s.connect(n[2],(c[1],1),(c[2],2))
        self.assertEqual(s.core(c[2],2)['core_id'],'임시-3')
        self.assertEqual(self.ids(s,c),['REAL-CORE','임시-3','임시-4','임시-4'])


def windows_ui():
    if sys.platform!='win32':return
    for kind in ('before','after'):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=str(Path(temp)/'ui')), \
             patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showerror') as error, \
             patch.object(code['messagebox'],'askyesno',return_value=True):
            Path(temp,'ui').mkdir();s,n,c=fixture(Path(temp)/'drawing.sqlite3',kind);s.close()
            app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
            try:
                app.replace_current_from(Path(temp)/'drawing.sqlite3');app.deiconify();app.update();s=app.store
                node=code['NodeDialog'](app,s,n[2])
                node.left_var.set(next(k for k,v in node.by_label.items() if v==c[1]))
                node.right_var.set(next(k for k,v in node.by_label.items() if v==c[2]))
                node.reload_all();app.update();node.left_tree.selection_set('1');node.right_tree.selection_set('1');app.update()
                before=wf.plan_snapshot(s.conn);node.connect_auto();app.update()
                assert [s.core(cid,1)['core_id'] for cid in c]==['REAL-CORE','임시-3','임시-3','임시-3']
                assert '임시코어3으로 통합' in node.msg.get(),node.msg.get()
                assert node.left_tree.selection()==('1',) and node.right_tree.selection()==('1',)
                after=wf.plan_snapshot(s.conn);s.undo();app.refresh();app.update();assert wf.plan_snapshot(s.conn)==before
                s.redo();app.refresh();app.update();assert wf.plan_snapshot(s.conn)==after
                node.destroy();assert not errors and not error.called,(errors,error.call_args_list)
            finally:app.on_close()
    print('PASS Windows field/after temporary join button, physical-route ID merge, real ID preservation and undo/redo repaint')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(TemporaryMergeTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS temporary component merge, real identities, isolated capacity, metadata, annotations, phases, RN ports, locks and atomic history')
