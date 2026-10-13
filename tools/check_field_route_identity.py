"""V127 physical field route edits: scoped preview, atomic apply and real UI."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code,wf


def fixture(path):
    s=code['Store'](path)
    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')")
    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('field_identity_policy',?)",(wf.FIELD_SLOT_POLICY,));s.conn.commit()
    nodes=[s.add_node('합성 시설 '+str(i),i*180,0) for i in range(4)]
    cables=[s.add_cable(nodes[i],nodes[i+1],chr(65+i),'6C','기설') for i in range(3)]
    with s.action('합성 연결 구간'):
        for i,c in enumerate(cables):
            s.conn.execute("UPDATE cores SET core_id='임시-1',detail=?,status1='normal',signal=? WHERE cable_id=? AND core_index=1",('원래 내역 '+str(i),('on','unknown','off')[i],c))
        for i in (1,2):
            a,b=sorted(((cables[i-1],1),(cables[i],1)));s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(nodes[i],*a,*b))
        s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(nodes[-1],))
        s.conn.execute("INSERT INTO ports VALUES(?,1,'P1','임시-1','포트 내역','normal','','unknown')",(nodes[-1],))
        a,b=sorted(((cables[-1],1),('PORT:'+nodes[-1],1)));s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(nodes[-1],*a,*b))
        s.conn.execute("UPDATE cores SET core_id='임시-1',detail='분리 내역',signal='error' WHERE cable_id=? AND core_index=6",(cables[0],))
    return s,nodes,cables


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.s,self.n,self.c=fixture(self.home/'working.sqlite3')
        self.s.backup_to(self.home/'gis.sqlite3');self.gis=(self.home/'gis.sqlite3').read_bytes()
    def tearDown(self):self.s.close();self.temp.cleanup()
    def snap(self):return wf.plan_snapshot(self.s.conn),wf.state(self.s)
    def preview(self,cid='REAL-NEW',detail='새 내역'):return wf.field_route_identity_preview(self.s,self.c[0],[(1,cid,detail)])
    def test_route_ports_metadata_annotations_backup_history_and_reopen(self):
        wf.save_annotations(self.s,(self.c[0],1),['정상'],'보존 메모')
        before=self.snap();p=self.preview();self.assertEqual(len(p['rows']),4);self.assertEqual(self.snap(),before)
        result=wf.field_route_identity_commit(self.s,p);self.assertTrue(result['backup'].exists());self.assertEqual(result['changed'],4)
        for row in p['rows']:
            saved=self.s.core(*row['slot']);self.assertEqual((saved['core_id'],saved['detail']),('REAL-NEW','새 내역'))
            self.assertEqual(tuple(saved[k] for k in wf.FIELD_SLOT_FIELDS[2:]),row['before'][2:])
            self.assertEqual(saved['annotation_memo'],'보존 메모')
        self.assertEqual(self.s.core(self.c[0],6)['detail'],'분리 내역')
        self.assertEqual(self.s.core(self.c[0],6)['core_id'],'임시-1')
        after=self.snap();self.assertEqual(before[0]['splices'],after[0]['splices'])
        self.s.undo();self.assertEqual(self.snap(),before);self.s.redo();self.assertEqual(self.snap(),after)
        self.assertEqual((self.home/'gis.sqlite3').read_bytes(),self.gis)
        self.s.close();self.s=code['Store'](self.home/'working.sqlite3');self.assertEqual(self.snap(),after)
    def test_id_only_and_name_only_change_only_requested_column(self):
        p=self.preview(detail='원래 내역 0');wf.field_route_identity_commit(self.s,p)
        for r in p['rows']:self.assertEqual(self.s.core(*r['slot'])['detail'],r['before'][1])
        p=self.preview(cid='REAL-NEW',detail='이름만 수정');wf.field_route_identity_commit(self.s,p)
        self.assertTrue(all(self.s.core(*r['slot'])['core_id']=='REAL-NEW' for r in p['rows']))
        self.assertEqual(self.s.core(self.c[0],6)['detail'],'분리 내역')
    def test_real_conflict_duplicates_remote_lock_and_no_change(self):
        self.s.update_core(self.c[2],1,('OTHER','다른 실제코어','normal','','off'));before=self.snap()
        with self.assertRaisesRegex(ValueError,'다른 실제'):self.preview()
        self.assertEqual(self.snap(),before)
        self.s.update_core(self.c[2],1,('임시-2','다른 임시','normal','','off'))
        self.s.update_core(self.c[0],3,('REAL-NEW','분리 실코어','normal','','unknown'))
        with self.assertRaisesRegex(ValueError,'이미'):self.preview()
        self.s.set_node_locked(self.n[-2],True)
        with self.assertRaisesRegex(ValueError,'잠긴'):self.preview(cid='NEW')
        self.s.set_node_locked(self.n[-2],False)
        with self.assertRaisesRegex(ValueError,'먼저 변경'):self.preview(cid='',detail='')
    def test_stale_tampered_preview_write_and_backup_failure_are_atomic(self):
        p=self.preview();p['rows'][0]['after']=('HACK','bad','','','')
        with self.assertRaises(ValueError):wf.field_route_identity_commit(self.s,p)
        p=self.preview();self.s.update_core(self.c[0],5,('UNRELATED','새 작업','','',''))
        with self.assertRaises(ValueError):wf.field_route_identity_commit(self.s,p)
        p=self.preview();before=self.snap()
        with patch.object(self.s,'backup_to',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):wf.field_route_identity_commit(self.s,p)
        self.assertEqual(self.snap(),before)
        self.s.conn.execute("CREATE TEMP TRIGGER fail_route BEFORE UPDATE ON ports BEGIN SELECT RAISE(ABORT,'synthetic late failure'); END")
        with self.assertRaises(Exception):wf.field_route_identity_commit(self.s,p)
        self.assertEqual(self.snap(),before)
    def test_batch_conflicting_route_and_duplicate_id_no_partial_writes(self):
        before=self.snap()
        with self.assertRaisesRegex(ValueError,'같은 코어ID'):
            wf.field_route_identity_preview(self.s,self.c[0],[(1,'NEW','x'),(2,'NEW','y')])
        self.assertEqual(self.snap(),before)
        # A valid route may return over a second number in the source cable.
        with self.s.action('합성 되돌아온 경로'):
            a,b=sorted(((self.c[0],2),(self.c[1],1)));self.s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(self.n[1],*a,*b))
        with self.assertRaisesRegex(ValueError,'중복 접속'):self.preview()
    def test_existing_local_edit_and_other_stages_unchanged(self):
        self.s.apply_core_identity_changes(self.c[0],[(1,'LOCAL','로컬 수정')])
        self.assertEqual(self.s.core(self.c[1],1)['core_id'],'임시-1')
        for kind in ('after','gis'):
            self.s.conn.execute("UPDATE meta SET value=? WHERE key='active_scenario'",(kind,));self.s.conn.commit()
            with self.assertRaises(ValueError):self.preview()


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=str(Path(temp)/'ui')),patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showerror') as error,patch.object(code['messagebox'],'askyesno',return_value=True):
        Path(temp,'ui').mkdir();s,n,c=fixture(Path(temp)/'drawing.sqlite3');s.close()
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            app.replace_current_from(Path(temp)/'drawing.sqlite3');app.deiconify();app.update();s=app.store
            editor=code['CableDialog'](app,s,c[0]);editor.notebook.select(editor.identity_tab);app.update()
            editor.identity_tree.selection_set('1');vals=list(editor.identity_tree.item('1','values'));vals[1:3]=['REAL-UI','화면에서 수정한 내역'];editor.identity_tree.item('1',values=vals)
            editor.id_var.set('아직 저장하지 않은 케이블명')
            before=wf.plan_snapshot(s.conn);draft=editor.route_identity_draft()
            editor.route_identity_button.invoke();app.update();review=editor._route_identity_dialog
            assert len(review.tree.get_children())==4
            review.cancel_button.invoke();app.update();assert editor.route_identity_draft()==draft and wf.plan_snapshot(s.conn)==before
            editor.route_identity_button.invoke();app.update();review=editor._route_identity_dialog
            from check_desktop_design import screenshot
            screenshot(review,Path(temp)/'v127-field-route-identity.png')
            review.geometry('760x400');app.update()
            button=review.apply_button;assert button.winfo_ismapped() and button.winfo_rooty()+button.winfo_height()<=review.winfo_rooty()+review.winfo_height()
            button.event_generate('<ButtonPress-1>',x=8,y=8);button.event_generate('<ButtonRelease-1>',x=8,y=8);app.update()
            assert not review.winfo_exists()
            assert all(s.core(owner,1)['core_id']=='REAL-UI' for owner in c)
            assert s.core('PORT:'+n[-1],1)['detail']=='화면에서 수정한 내역'
            assert s.core(c[0],6)['core_id']=='임시-1'
            assert editor.id_var.get()=='아직 저장하지 않은 케이블명'
            after=wf.plan_snapshot(s.conn);s.undo();app.refresh();app.update();assert wf.plan_snapshot(s.conn)==before
            s.redo();app.refresh();app.update();assert wf.plan_snapshot(s.conn)==after
            # A draft changed while reviewing cannot overwrite the newer input.
            editor.reload_identity();vals=list(editor.identity_tree.item('1','values'));vals[2]='검토 내역';editor.identity_tree.item('1',values=vals)
            editor.route_identity_button.invoke();app.update();review=editor._route_identity_dialog
            vals[2]='더 최신 입력';editor.identity_tree.item('1',values=vals);review.apply_button.invoke();app.update()
            assert review.winfo_exists() and wf.plan_snapshot(s.conn)==after
            assert error.call_count==1,error.call_args_list
            review.destroy();editor.destroy();assert not errors,errors
        finally:app.on_close()
    print('PASS Windows field route button, preview/cancel, RN scope, compact apply, dirty drafts, header preservation, undo/redo')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RouteTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
