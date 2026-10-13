"""RN preassignment without cables, local identities, clipboard and native buttons."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code,wf


class RNIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.s=code['Store'](self.home/'drawing.sqlite3');self.rn=self.s.add_node('합성 RN',0,0,node_type='rn');self.owner='PORT:'+self.rn
    def tearDown(self):self.s.close();self.temp.cleanup()
    def save(self,changes):return wf.rn_identity_save(self.s,self.rn,changes,self.s.data_revision(),self.s._view_generation)
    def snap(self):return wf.plan_snapshot(self.s.conn),wf.state(self.s)
    def test_preassign_without_cable_blanks_history_reopen(self):
        before=self.snap();self.assertEqual(self.save([(1,'SYNTH-1','끝단 회선'),(2,'SYNTH-2','두 번째')]),2)
        after=self.snap();self.assertFalse(after[0]['splices']);self.assertFalse(after[0]['cables'])
        self.s.undo();self.assertEqual(self.snap(),before);self.s.redo();self.assertEqual(self.snap(),after)
        self.assertEqual(self.save([(1,'',''),(2,'','')]),0)
        self.save([(1,'','새 내역')]);self.assertEqual(self.s.core(self.owner,1)['core_id'],'SYNTH-1')
        path=self.s.path;self.s.close();self.s=code['Store'](path);self.assertEqual(self.s.core(self.owner,1)['detail'],'새 내역')
    def test_field_local_preserves_signals_splices_and_other_end(self):
        s=self.s;s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')");s.conn.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('field_identity_policy',wf.FIELD_SLOT_POLICY));s.conn.commit()
        a=s.add_node('합성 끝단',300,0);c=s.add_cable(a,self.rn,'SYNTH','6C','기설')
        s.update_core(c,1,('SYNTH-1','케이블 내역','normal','','on'));s.connect(self.rn,(c,1),(self.owner,1))
        s.update_core(self.owner,1,('임시-123','임시 내역','broken','','off'))
        before=self.snap();source=self.home/'gis.sqlite3';s.backup_to(source);frozen=source.read_bytes()
        self.save([(1,'SYNTH-1','RN 내역')]);after=self.snap()
        self.assertEqual(before[0]['cores'],after[0]['cores']);self.assertEqual(before[0]['splices'],after[0]['splices'])
        row=s.core(self.owner,1);self.assertEqual(tuple(row[k] for k in ('status1','status2','signal')),('broken','','off'))
        self.assertEqual(source.read_bytes(),frozen);s.undo();self.assertEqual(self.snap(),before)
    def test_end_to_end_explicit_field_connections(self):
        s=self.s;s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')");s.conn.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',('field_identity_policy',wf.FIELD_SLOT_POLICY));s.conn.commit()
        other=s.add_node('반대 RN',400,0,node_type='rn');self.save([(1,'SYNTH-1','양끝 회선')])
        wf.rn_identity_save(s,other,[(1,'SYNTH-1','양끝 회선')],s.data_revision(),s._view_generation)
        c=s.add_cable(self.rn,other,'SYNTH','6C','기설')
        s.connect(self.rn,(self.owner,1),(c,1));s.connect(other,(c,1),('PORT:'+other,1))
        self.assertTrue(wf.completion_report(s)['by_id']['SYNTH-1']['complete'])
    def test_atomic_validation_stale_lock_backup_and_write_failure(self):
        before=self.snap()
        for changes in ([(1,'VALID','ok'),(9999,'BAD','bad')],[(1,'','name')],[(1,'A',''),(1,'B','')]):
            with self.assertRaises(ValueError):self.save(changes)
            self.assertEqual(self.snap(),before)
        with self.assertRaises(ValueError):wf.rn_identity_save(self.s,self.rn,[(1,'A','')],-1,self.s._view_generation)
        with patch.object(wf,'locked',return_value=True),self.assertRaises(ValueError):self.save([(1,'A','')])
        with patch.object(self.s,'backup_to',side_effect=OSError('backup failed')),self.assertRaises(OSError):self.save([(1,'A','')])
        original=self.s._write_core_identity
        def fail(owner,index,*args):
            if index==2:raise ValueError('late failure')
            original(owner,index,*args)
        with patch.object(self.s,'_write_core_identity',side_effect=fail),self.assertRaises(ValueError):self.save([(1,'A',''),(2,'B','')])
        self.assertEqual(self.snap(),before)
        self.save([(1,'A','')]);saved=self.snap()
        with self.assertRaises(ValueError):self.save([(2,'B',''),(1,'OTHER','')])
        self.assertEqual(self.snap(),saved)
    def test_after_existing_unique_auto_join_preserves_metadata(self):
        s=self.s;s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','after')");s.conn.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(wf.AFTER_AUTO_POLICY,'1'));s.conn.commit()
        a=s.add_node('합성 끝단',300,0);c=s.add_cable(a,self.rn,'SYNTH','6C','기설');s.update_core(c,1,('SYNTH-1','케이블','normal','','on'))
        before=self.snap();self.save([(1,'SYNTH-1','RN 내역')]);after=self.snap()
        self.assertEqual(len(after[0]['splices']),1);self.assertEqual(before[0]['cores'],after[0]['cores']);s.undo();self.assertEqual(self.snap(),before)
    def test_clipboard_blank_offsets_quoted_names_and_atomic_overflow(self):
        result=wf.rn_identity_paste('코어ID\t코어내역\r\nA\t"첫\n내역"\r\n\t\r\n임시코어7\t끝\r\n',[1,2,3,4],2)
        self.assertEqual(result,[(2,'A','첫\n내역'),(3,'',''),(4,'임시-7','끝')])
        for raw in ('A\tB\tC','A\tB\nC\tD'):
            with self.assertRaises(ValueError):wf.rn_identity_paste(raw,[1],1)


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=str(Path(temp)/'ui')),patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showerror') as error:
        Path(temp,'ui').mkdir();app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            app.deiconify();app.update();s=app.store;rn=s.add_node('예시 RN · 내부 사전 입력',200,120,node_type='rn');app.refresh()
            node=code['NodeDialog'](app,s,rn);app.update();before=wf.plan_snapshot(s.conn)
            def click(widget):
                widget.event_generate('<ButtonPress-1>',x=8,y=8);widget.event_generate('<ButtonRelease-1>',x=8,y=8);app.update()
            click(node.rn_identity_button);editor=node._rn_identity_dialog;assert editor.winfo_exists()
            editor.id_entry.insert(0,'SYNTH-1');editor.detail_entry.insert(0,'RN 양끝 사전 배정');app.update()
            node.rn_identity_button.invoke();assert node._rn_identity_dialog is editor and editor.core_id.get()=='SYNTH-1'
            with patch.object(code['messagebox'],'askyesno',return_value=False):editor.close()
            assert editor.winfo_exists() and wf.plan_snapshot(s.conn)==before
            # Sort, then paste using stable physical port indices and blank offsets.
            editor.tree.cycle_sort('port');editor.tree.selection_set('2');app.update();editor.clipboard_clear();editor.clipboard_append('SYNTH-2\t두 번째\n\t\nSYNTH-4\t네 번째')
            click(editor.paste_button);assert editor.drafts[2]==('SYNTH-2','두 번째') and editor.drafts[4]==('SYNTH-4','네 번째')
            assert not editor.drafts[3][0]
            editor.geometry('700x460');app.update()
            for button in (editor.save_button,editor.close_button,editor.paste_button):
                assert button.winfo_ismapped()
                assert button.winfo_rooty()+button.winfo_height()<=editor.winfo_rooty()+editor.winfo_height()
            from check_desktop_design import screenshot
            screenshot(editor,Path(temp)/'v129-rn-identity.png')
            click(editor.save_button);assert not error.called,error.call_args
            assert s.core('PORT:'+rn,1)['core_id']=='SYNTH-1' and s.core('PORT:'+rn,4)['detail']=='네 번째'
            after=wf.plan_snapshot(s.conn);editor.close();app.update()
            s.undo();app.refresh();assert wf.plan_snapshot(s.conn)==before
            s.redo();app.refresh();assert wf.plan_snapshot(s.conn)==after
            click(node.rn_identity_button);editor=node._rn_identity_dialog;editor.core_id.set('UNSAVED')
            s.set_node_details(rn,'변경된 RN');saved=wf.plan_snapshot(s.conn);editor.save();assert error.called and wf.plan_snapshot(s.conn)==saved
            assert editor.core_id.get()=='UNSAVED'
            with patch.object(code['messagebox'],'askyesno',return_value=True):node.close_dialog()
            assert not node.winfo_exists() and not errors,errors
            print('PASS Windows RN input button, no-cable drafts, paste/sort, compact save, cancel, stale input and undo/redo')
        finally:app.destroy()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RNIdentityTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
