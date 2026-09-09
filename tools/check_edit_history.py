"""Regression gates for Excel blank-cell preservation and history checkpoint restore."""
import json
import os
from pathlib import Path
import runpy
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'app'))
code=runpy.run_path(str(ROOT/'app'/'telecom_core_app.pyw'),run_name='edit_history_check')
wf=code['App'].__init__.__globals__['workflow'];parse=code['parse_core_identity_paste']


def fixture(store):
    a=store.add_node('시작',0,0);h=store.add_node('함체',300,0);b=store.add_node('끝',600,0)
    left=store.add_cable(a,h,'L','12C','기설');right=store.add_cable(h,b,'R','12C','기설')
    for i in range(1,6):store.connect(h,(left,i),(right,i),temporary=True)
    return a,h,b,left,right


class EditHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=code['Store'](Path(self.temp.name)/'drawing.sqlite3')
        self.a,self.h,self.b,self.left,self.right=fixture(self.store)
    def tearDown(self):self.store.close();self.temp.cleanup()
    def snapshot(self):return wf.plan_snapshot(self.store.conn)

    def test_original_blank_paste_preserves_three_connections(self):
        s=self.store;original=self.snapshot();temp=[s.core(self.left,i)['core_id'] for i in range(1,6)]
        applied,unchanged,errors=s.apply_core_identity_changes(self.left,[(1,'',''),(2,'',''),(3,'',''),(4,'REAL-4','내역4'),(5,'REAL-5','내역5')])
        self.assertEqual(applied,[4,5]);self.assertEqual(unchanged,[1,2,3]);self.assertFalse(errors)
        for i in range(1,4):
            self.assertEqual(s.core(self.left,i)['core_id'],temp[i-1]);self.assertEqual(s.core(self.right,i)['core_id'],temp[i-1])
        for i in (4,5):self.assertEqual(s.core(self.right,i)['core_id'],f'REAL-{i}')
        self.assertEqual(self.snapshot()['splices'],original['splices'])
        changed=self.snapshot();s.undo();self.assertEqual(self.snapshot(),original);s.redo();self.assertEqual(self.snapshot(),changed)

    def test_partial_blank_fields_and_metadata(self):
        s=self.store;cid=s.core(self.left,4)['core_id']
        s.update_core(self.left,4,(cid,'기존 내역','normal','','off'))
        wf.save_annotations(s,(self.left,4),['정상'],'메모 보존')
        s.apply_core_identity_changes(self.left,[(4,'REAL-4','')])
        for cable in (self.left,self.right):
            row=s.core(cable,4);self.assertEqual((row['core_id'],row['detail'],row['signal']),('REAL-4','기존 내역','off'))
            self.assertEqual(row['annotation_memo'],'메모 보존')
        s.apply_core_identity_changes(self.left,[(4,'','이름만 변경')])
        self.assertEqual(s.core(self.right,4)['detail'],'이름만 변경');self.assertEqual(s.core(self.left,4)['core_id'],'REAL-4')
        before=self.snapshot();revision=s.data_revision();s.apply_core_identity_changes(self.left,[(i,'  ','\t') for i in range(1,6)])
        self.assertEqual(self.snapshot(),before);self.assertEqual(s.data_revision(),revision)

    def test_real_id_conflict_preserved_and_preview_has_no_disconnect(self):
        s=self.store;s.apply_core_identity_changes(self.left,[(4,'REAL-4','기존')])
        result,events=wf.bulk_trial(s,'apply_core_identity_changes',(self.left,[(1,'',''),(2,'',''),(3,'',''),(4,'OTHER','교체'),(5,'REAL-5','신규')]))
        self.assertTrue(result[2]);self.assertEqual(s.core(self.left,4)['core_id'],'REAL-4')
        self.assertFalse(any(e['table_name']=='splices' for e in events))

    def test_two_column_blanks_offsets_and_single_name_column(self):
        rows,blanks=parse('\t\r\n\t\r\n\t\r\nREAL-4\t내역4\r\nREAL-5\t내역5\r\n',1,'#2',set(range(1,13)))
        self.assertEqual(rows,[(4,'REAL-4','내역4'),(5,'REAL-5','내역5')]);self.assertEqual(blanks,6)
        rows,_=parse('\n\n\n내역4\n내역5\n',1,'#3',set(range(1,13)))
        self.assertEqual(rows,[(4,None,'내역4'),(5,None,'내역5')])
        rows,_=parse('\nID-7\t\n',6,'#2',set(range(1,13)))
        self.assertEqual(rows,[(7,'ID-7',None)])

    def test_explicit_numbers_headers_and_excel_quoted_cells(self):
        rows,_=parse('번호\t코어ID\t코어명\n1\t\t\n4\tREAL4\t"첫 줄\n두번째 줄"\n5\tREAL5\t"탭\t포함"\n',12,'#2',set(range(1,13)))
        self.assertEqual(rows,[(4,'REAL4','첫 줄\n두번째 줄'),(5,'REAL5','탭\t포함')])
        self.assertEqual(parse('ID-코어명\t이름',1,'#2',{1})[0],[(1,'ID-코어명','이름')])
        for raw in ('1\tA\tname\n1\tB\tname','99\tA\tname','X\tA\tname'):
            with self.assertRaises(ValueError):parse(raw,1,'#2',set(range(1,13)))

    def test_history_before_after_and_forward_again(self):
        s=self.store;original=self.snapshot()
        s.apply_core_identity_changes(self.left,[(4,'REAL4','이름4')]);first=s.history_rows()[-1]['id'];checkpoint=self.snapshot()
        s.set_cable_lot_no(self.left,'LOT-1');s.delete_core_assignment(self.left,1);last=s.history_rows()[-1]['id'];latest=self.snapshot()
        out=s.restore_history(first,False,s.data_revision());self.assertEqual(out['count'],2);self.assertTrue(out['backup'].exists());self.assertEqual(self.snapshot(),checkpoint)
        s.restore_history(last,False,s.data_revision());self.assertEqual(self.snapshot(),latest)
        s.restore_history(first,True,s.data_revision());self.assertEqual(self.snapshot(),original)
        # Reopening retains the undo cursor and the forward checkpoints.
        path=s.path;s.close();self.store=code['Store'](path);s=self.store
        s.restore_history(last,False,s.data_revision());self.assertEqual(self.snapshot(),latest)

    def test_restore_legacy_blank_deletion_recovers_splices(self):
        s=self.store;before=self.snapshot()
        # Exact former deletion path; these old history events remain restorable.
        with s.action('코어ID·코어명 일괄수정'):
            for i in range(1,4):s.update_core(self.left,i,('','','','',''))
        group=s.history_rows()[-1]['id'];self.assertEqual(len(self.snapshot()['splices']),2)
        s.restore_history(group,True,s.data_revision());self.assertEqual(self.snapshot(),before)

    def test_stale_and_new_branch(self):
        s=self.store;s.set_cable_lot_no(self.left,'ONE');first=s.history_rows()[-1]['id']
        s.set_cable_lot_no(self.left,'TWO');last=s.history_rows()[-1]['id'];revision=s.data_revision()
        s.set_cable_lot_no(self.right,'CHANGED')
        with self.assertRaisesRegex(ValueError,'변경'):s.restore_history(first,False,revision)
        s.restore_history(first,False,s.data_revision());s.set_cable_lot_no(self.left,'NEW')
        self.assertNotIn(last,{r['id'] for r in s.history_rows()})
        with self.assertRaisesRegex(ValueError,'더 이상'):s.restore_history(last,False,s.data_revision())

    def test_multi_step_failure_rolls_back_every_group(self):
        s=self.store
        with s.action('이름1'):s.conn.execute('UPDATE nodes SET name=? WHERE id=?',('이름1',self.a))
        first=s.history_rows()[-1]['id'];s.set_cable_lot_no(self.left,'LOT');s.delete_core_assignment(self.left,2)
        snapshot=self.snapshot();history=s.history_rows();revision=s.data_revision()
        s.conn.execute("CREATE TRIGGER test_restore_failure BEFORE UPDATE ON nodes WHEN NEW.name='시작' BEGIN SELECT RAISE(ABORT,'test failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):s.restore_history(first,True,s.data_revision())
        self.assertEqual(self.snapshot(),snapshot);self.assertEqual(s.history_rows(),history);self.assertEqual(s.data_revision(),revision)

    def test_retention_is_bounded(self):
        s=self.store
        for i in range(105):s.set_cable_lot_no(self.left,str(i))
        self.assertEqual(len(s.history_rows()),100)
        first=s.history_rows()[0]['id'];s.restore_history(first,True,s.data_revision())
        self.assertTrue(all(r['undone'] for r in s.history_rows()))


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**kw:errors.append(str(a))),patch.object(code['messagebox'],'showwarning',side_effect=lambda *a,**kw:errors.append(str(a))),patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'askyesno',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *e:errors.append(str(e))
            a,h,b,left,right=fixture(app.store);app.refresh();original=wf.plan_snapshot(app.store.conn)
            dialog=code['CableDialog'](app,app.store,cable_id=left);dialog.notebook.select(dialog.identity_tab);app.update()
            dialog.identity_tree.selection_set('1');dialog.identity_active_col='#2'
            raw='\t\r\n\t\r\n\t\r\nREAL-4\t내역4\r\nREAL-5\t내역5\r\n'
            with patch.object(dialog,'clipboard_get',return_value=raw):dialog.paste_identity_from_clipboard()
            assert str(dialog.identity_tree.item('1','values')[1]).startswith('임시코어')
            assert dialog.identity_tree.item('4','values')[1]=='REAL-4'
            assert wf.plan_snapshot(app.store.conn)==original
            dialog.identity_tree.focus_force();app.update();dialog.identity_tree.event_generate('<Control-z>');app.update()
            assert str(dialog.identity_tree.item('4','values')[1]).startswith('임시코어')
            dialog.identity_tree.event_generate('<Control-y>');app.update();assert dialog.identity_tree.item('4','values')[1]=='REAL-4'
            # Both cancellation and explicit acceptance use the real preview UI.
            original_dialog=wf.TableDialog;accept=[False]
            class AutoPreview(original_dialog):
                def __init__(self,*args,**kw):
                    super().__init__(*args,**kw)
                    assert not any('접속 delete' in str(self.table.item(i,'values')) for i in self.table.get_children())
                    self.after(20,self.confirm if accept[0] else self.destroy)
            with patch.object(wf,'TableDialog',AutoPreview):
                dialog.apply_identity_changes();assert wf.plan_snapshot(app.store.conn)==original
                accept[0]=True;dialog.apply_identity_changes()
            app.update();assert app.store.core(right,4)['core_id']=='REAL-4';assert len(wf.plan_snapshot(app.store.conn)['splices'])==5
            applied=wf.plan_snapshot(app.store.conn);group=app.store.history_rows()[-1]['id']
            dialog.identity_tree.focus_force();app.update();dialog.identity_tree.event_generate('<Control-z>');app.update()
            assert wf.plan_snapshot(app.store.conn)==original
            dialog.identity_tree.event_generate('<Control-y>');app.update();assert wf.plan_snapshot(app.store.conn)==applied
            history=app.open_history();app.update();history.tree.selection_set(group);history.show_selection()
            assert 'REAL-4' in history.details.get('1.0','end')
            history.restore(before=True);app.update();assert wf.plan_snapshot(app.store.conn)==original
            assert not dialog.winfo_exists()
            history.tree.selection_set(group);history.show_selection();history.restore(before=False);app.update()
            assert wf.plan_snapshot(app.store.conn)==applied
            history.destroy();app.update();app.on_close();assert not errors,errors
    print('PASS Windows Excel clipboard, draft Ctrl+Z/Ctrl+Y, cancel/apply preview, saved popup undo/redo and history checkpoint UI')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(EditHistoryTests))
    if not result.wasSuccessful():sys.exit(1)
    windows_ui()
    print('PASS blank/partial Excel preservation, old deletion recovery, history persistence, branching, bounded retention and atomic checkpoint restore')
