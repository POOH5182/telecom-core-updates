"""Incremental field-sheet input, additive saving and explicit manual correction."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_field_survey import code,wf


class SheetTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.store=code['Store'](self.home/'drawing.sqlite3');s=self.store
        s.conn.execute("INSERT INTO meta VALUES('active_scenario','before')");s.conn.commit()
        self.a=s.add_node('시작',0,0);self.h=s.add_node('조사 함체',240,0)
        self.b=s.add_node('끝 B',480,0);self.c=s.add_node('끝 C',240,240)
        self.left=s.add_cable(self.a,self.h,'A','6C','기설');self.right=s.add_cable(self.h,self.b,'B','6C','기설');self.third=s.add_cable(self.h,self.c,'C','6C','기설')
        for index in (1,2):
            s.update_core(self.left,index,(f'OLD-{index}',f'내역 {index}','normal','','off'))
            s.connect(self.h,(self.left,index),(self.right,index))
    def tearDown(self):self.store.close();self.temp.cleanup()
    def engine(self):return wf.FieldSurvey(self.store,self.h)
    def save(self,raw):return wf.field_save_sheet(self.store,self.h,raw,None,self.store.data_revision(),self.store._view_generation)
    def snapshot(self):return wf.plan_snapshot(self.store.conn),wf.field_records(self.store)

    def test_incremental_paste_reorders_columns_preserves_unmentioned_and_blanks(self):
        old='A\tB\tC\n1\t1\t\n2\t2\t'
        merged,counts=wf.field_merge_sheet(self.engine(),old,'C\tA\n3\t3\n4\t4')
        rows=self.engine().parse(merged)
        self.assertEqual(len(rows),4);self.assertEqual(counts,{'added':2,'updated':0,'kept':2})
        self.assertEqual(rows[2]['slots'],wf.field_pair(((self.third,3),(self.left,3))))
        changed,counts=wf.field_merge_sheet(self.engine(),merged,'C\tA\n1\t1')
        self.assertEqual(len(self.engine().parse(changed)),4)
        self.assertEqual(counts['kept'],3);self.assertEqual(counts['updated'],1)
        row=next(r for r in self.engine().report(changed) if r['row']==2)
        self.assertEqual((row['status'],row['comparison']),('불일치','기존과 다름'))
        # Pasting a heading range with duplicate owners never collapses cells.
        with self.assertRaises(ValueError):wf.field_merge_sheet(self.engine(),old,'A\tA\n3\t4')

    def test_new_connections_added_differences_preserved_backup_and_single_undo(self):
        s=self.store;before=self.snapshot();groups=len(s.history_rows())
        result=self.save('A\tB\tC\n1\t\t1\n3\t3\t\n999\t4\t')
        self.assertEqual(result['added'],1);self.assertTrue(result['backup'].exists())
        self.assertEqual(len(s.history_rows()),groups+1)
        self.assertEqual(s.splice_for(self.h,self.left,1)['cable2_id'] in (self.left,self.right),True)
        self.assertEqual(self.engine().pairs,{wf.field_pair(((self.left,i),(self.right,i))) for i in (1,2,3)})
        rows=self.engine().report();self.assertEqual(rows[0]['status'],'불일치');self.assertEqual(rows[1]['comparison'],'신규 추가됨');self.assertEqual(rows[2]['status'],'이상')
        self.assertEqual(s.core(self.third,1)['core_id'],'')
        after=self.snapshot();s.undo();self.assertEqual(self.snapshot(),before);s.redo();self.assertEqual(self.snapshot(),after)
        path=s.path;s.close();self.store=code['Store'](path);self.assertEqual(self.snapshot(),after)
        self.assertEqual(self.save(wf.field_records(self.store)[self.h]['text'])['added'],0)

    def test_source_six_columns_preserve_real_metadata_and_fill_new_core(self):
        raw='코어ID\t코어명\t회선번호\t회선명\t가입자명\t중요여부\tA\tB\nNEW-3\t새 이름\t0001\t회선\t가입자\tY\t3\t3\nDIFFERENT\t다른 이름\t\t\t\t\t1\t1'
        self.assertEqual(self.save(raw)['added'],1)
        self.assertEqual(self.store.core(self.left,3)['core_id'],'NEW-3')
        self.assertEqual(self.store.core(self.right,3)['detail'],'새 이름')
        self.assertEqual(self.store.core(self.left,1)['core_id'],'OLD-1');self.assertEqual(self.store.core(self.left,1)['detail'],'내역 1')
        report=self.engine().report();self.assertEqual(report[1]['status'],'불일치');self.assertIn('기존 ID OLD-1',report[1]['reason'])
        merged,_=wf.field_merge_sheet(self.engine(),raw,'B\tA\n3\t3\n4\t4')
        table=wf.field_table(merged);self.assertEqual(table[1][:6],['NEW-3','새 이름','0001','회선','가입자','Y'])
        self.assertEqual(self.save(merged)['added'],1)

    def test_conflicts_and_locks_defer_without_touching_existing_rows(self):
        s=self.store;s.update_core(self.left,3,('REAL-A','A 이름','','','off'));s.update_core(self.right,3,('REAL-B','B 이름','','','on'))
        old=wf.plan_snapshot(s.conn)
        result=self.save('A\tB\n3\t3')
        self.assertEqual((result['added'],result['deferred']),(0,1));self.assertEqual(wf.plan_snapshot(s.conn),old)
        self.assertEqual(self.engine().report()[0]['status'],'불일치')
        s.set_node_locked(self.a,True);old=wf.plan_snapshot(s.conn)
        result=self.save('A\tB\n4\t4');self.assertEqual(result['added'],0);self.assertEqual(wf.plan_snapshot(s.conn),old)
        s.set_node_locked(self.h,True);snapshot=self.snapshot()
        with self.assertRaises(ValueError):self.save('A\tB\n5\t5')
        self.assertEqual(self.snapshot(),snapshot)

    def test_manual_correction_preserves_other_connections_and_invalidates_confirmation(self):
        s=self.store;self.save('A\tB\tC\n1\t\t1\n2\t2\t')
        row=self.engine().report()[0];self.assertEqual(row['status'],'불일치')
        preview=wf.field_preview(s,self.h,{row['key']});before=self.snapshot()
        self.assertEqual(self.snapshot(),before)
        wf.field_apply(s,self.h,preview['keys'],preview['revision'],preview['generation'])
        self.assertEqual(self.engine().report()[0]['status'],'확인완료')
        self.assertIn(wf.field_pair(((self.left,2),(self.right,2))),self.engine().pairs)
        self.assertEqual(s.core(self.right,1)['core_id'],'OLD-1')
        s.disconnect(self.h,self.third,1);self.assertNotEqual(self.engine().report()[0]['status'],'확인완료')

    def test_stale_and_backup_failure_are_no_write_and_flags_survive_import(self):
        s=self.store;self.save('A\tB\n1\t1')
        key=self.engine().report()[0]['key'];self.engine().mark({key},'이상','나중에 현장 재확인')
        self.save('A\tB\n1\t1\n3\t3');self.assertEqual(self.engine().report()[0]['status'],'이상')
        old=self.snapshot();rev=s.data_revision()
        with self.assertRaises(ValueError):wf.field_save_sheet(s,self.h,'A\tB\n4\t4',None,rev-1,s._view_generation)
        self.assertEqual(self.snapshot(),old)
        with patch.object(s,'backup_to',side_effect=OSError('backup failed')):
            with self.assertRaises(OSError):self.save('A\tB\n4\t4')
        self.assertEqual(self.snapshot(),old)

    def test_delete_only_middle_cable_both_enclosures_need_assignment_again(self):
        s=self.store;end=s.add_node('다음 끝',720,0);tail=s.add_cable(self.b,end,'TAIL','6C','기설')
        s.connect(self.b,(self.right,1),(tail,1))
        s.connect(self.b,(self.right,2),(tail,2))
        outer={slot:dict(s.core(*slot)) for slot in ((self.left,1),(tail,1))}
        before=self.snapshot();groups=len(s.history_rows())
        self.assertTrue(s.delete_core_assignment(self.right,1))
        self.assertEqual(len(s.history_rows()),groups+1)
        self.assertTrue(all(not s.core(self.right,1)[key] for key in ('core_id','detail','status1','status2','signal')))
        self.assertEqual({slot:dict(s.core(*slot)) for slot in outer},outer)
        self.assertIsNone(s.splice_for(self.h,self.right,1));self.assertIsNone(s.splice_for(self.b,self.right,1))
        self.assertEqual(s.node_assignment_needs(self.h),{self.left:{1}})
        self.assertEqual(s.node_assignment_needs(self.b),{tail:{1}})
        warnings=s.node_warning_summary();self.assertEqual((warnings[self.h]['count'],warnings[self.b]['count']),(1,1))
        self.assertIsNotNone(s.splice_for(self.h,self.right,2)) # Other core numbers survive.
        s.auto_connect_same_ids();self.assertEqual(s.core(self.right,1)['core_id'],'')
        s.undo();self.assertEqual(self.snapshot(),before)


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showwarning',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showinfo',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True), \
             patch.object(code['messagebox'],'askyesno',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *args:errors.append(str(args))
            try:
                s=app.store;a=s.add_node('시작',0,0);h=s.add_node('조사 함체',240,0);b=s.add_node('끝 B',480,0);c=s.add_node('끝 C',240,240)
                left=s.add_cable(a,h,'A','6C','기설');right=s.add_cable(h,b,'B','6C','기설');third=s.add_cable(h,c,'C','6C','기설')
                s.update_core(left,1,('OLD','기존 이름','normal','','off'));s.connect(h,(left,1),(right,1))
                assert app.load_scenario('before');s=app.store
                node=code['NodeDialog'](app,s,h);node.field_survey_open();app.update()
                dialog=next(w for w in node.winfo_children() if isinstance(w,wf.FieldSurveyDialog));sheet=dialog.sheet
                sheet.focus_cell(0,0);app.clipboard_clear();app.clipboard_append('A\tB\tC\n1\t\t1\n2\t2\t')
                sheet.tree.event_generate('<Control-v>');app.update()
                assert sheet.data[1][:3]==['1','','1'];assert any(r['status']=='불일치' for r in dialog.rows)
                assert s.core(left,2)['core_id']=='' # Clipboard and comparison are read only.
                dialog.inspect();app.update();assert s.core(left,2)['core_id'].startswith('임시-')
                assert wf.field_pair(((left,1),(right,1))) in wf.FieldSurvey(s,h).pairs
                assert sheet.tree.item('2','tags')==('difference',)
                # Reordered incoming headers append a row and keep earlier observations.
                app.clipboard_clear();app.clipboard_append('C\tA\n3\t3');sheet.paste_from_a1();app.update()
                assert len(wf.FieldSurvey(s,h).parse(sheet.get_text()))==3
                before=sheet.get_text();sheet.focus_cell(1,2);sheet.begin_edit();app.update()
                sheet.editor.delete(0,'end');sheet.editor.insert(0,'4');sheet.editor.event_generate('<Return>');app.update()
                sheet.cancel_editor();sheet.tree.focus_force();app.update();assert sheet.data[1][2]=='4'
                sheet.tree.event_generate('<Control-z>');app.update();assert sheet.get_text()==before
                sheet.tree.event_generate('<Control-y>');app.update();assert sheet.data[1][2]=='4'
                # Correct the first row manually to match the retained original connection.
                sheet.focus_cell(1,2);sheet.clear_cell();sheet.focus_cell(1,1);sheet.begin_edit();app.update()
                sheet.editor.insert(0,'1');sheet.commit_editor();dialog.inspect();app.update()
                assert wf.FieldSurvey(s,h).report()[0]['status']=='확인완료'
                assert s.core(left,3)['core_id']==s.core(third,3)['core_id']!=''
                saved=wf.field_records(s)[h]['text'];dialog.destroy();node.destroy()
                node=code['NodeDialog'](app,s,h);node.field_survey_open();app.update()
                dialog=next(w for w in node.winfo_children() if isinstance(w,wf.FieldSurveyDialog))
                assert dialog.sheet.get_text()==saved
                # The result row button takes the user back to a real editable cell.
                dialog.tree.selection_set('0');dialog.edit_selected();app.update();assert dialog.sheet.editor is not None
                dialog.sheet.cancel_editor();dialog.destroy();node.destroy();assert not errors,errors
                # Invoke the user's actual cable-only delete button on a through route.
                end=s.add_node('다음 끝',720,0);tail=s.add_cable(b,end,'TAIL','6C','기설')
                s.connect(b,(right,1),(tail,1));outer=[dict(s.core(left,1)),dict(s.core(tail,1))]
                s.connect(b,(right,2),(tail,2))
                cable_dialog=code['CableDialog'](app,s,right);app.update();cable_dialog.tree.selection_set('1')
                cable_dialog.delete_core(cable_dialog.tree);app.update()
                assert s.core(right,1)['core_id']==''
                assert [dict(s.core(left,1)),dict(s.core(tail,1))]==outer
                assert s.node_warning_summary()[h]['count']==1 and s.node_warning_summary()[b]['count']==1
                labels=[app.canvas.itemcget(i,'text') for i in app.canvas.find_all() if app.canvas.type(i)=='text']
                assert labels.count('배정필요 1')>=2
                cable_dialog.destroy();assert not errors,errors
            finally:app.on_close()
    print('PASS Windows field Excel Ctrl+V, incremental headers, red differences, no-write comparison, automatic additions, cell edit/undo/redo and reopened saved grid')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SheetTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS incremental field sheet, six-column source format, additive save, retained conflicts, backup/undo and manual correction')
