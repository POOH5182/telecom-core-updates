"""Frozen GIS comparison, manual real-ID swaps and retained missing identities."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code,wf


class CompareTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.store=code['Store'](self.root/'drawing.sqlite3');s=self.store
        s.conn.execute("INSERT INTO meta VALUES('active_scenario','before')");s.conn.commit()
        self.a=s.add_node('왼쪽 끝',0,0);self.h=s.add_node('조사 함체',300,0);self.b=s.add_node('오른쪽 끝',600,0)
        self.left=s.add_cable(self.a,self.h,'A','6C','기설');self.right=s.add_cable(self.h,self.b,'B','6C','기설')
        for i in (1,2,3):
            s.update_core(self.left,i,(f'ID-{i}',f'{i}번 회선','normal','','on' if i==1 else 'off'));s.connect(self.h,(self.left,i),(self.right,i))
        wf.save_annotations(s,(self.left,1),['정상','첫 회선'],'A 주석');wf.save_annotations(s,(self.left,2),['정상','둘째 회선'],'B 주석')
        self.reference=wf.field_capture_reference(s.conn)
    def tearDown(self):self.store.close();self.temp.cleanup()
    def save(self,raw,add_new=False):
        s=self.store;return wf.field_save_sheet(s,self.h,raw,None,s.data_revision(),s._view_generation,self.reference,add_new=add_new)
    def rows(self):return [r for r in wf.FieldSurvey(self.store,self.h).report() if r['source']=='조사표']
    def snapshot(self):return wf.plan_snapshot(self.store.conn),wf.field_records(self.store),copy.deepcopy(wf.field_reference(self.store)),self.store.data_revision(),self.store.history_rows()
    def swap_choices(self):return {row['key']:dict(self.store.core(self.left,int(row['row'])-1)) for row in self.rows()[:2]}

    def test_comparison_save_preserves_all_connections_and_records_exact_changes(self):
        before=wf.plan_snapshot(self.store.conn);self.save('A\tB\n1\t2\n2\t1\n3\t3\n4\t4')
        self.assertEqual(wf.plan_snapshot(self.store.conn),before)
        a,b,c,d=self.rows();self.assertEqual([r['baseline_relation'] for r in (a,b,c,d)],['선번 다름','선번 다름','같음','선번 다름'])
        self.assertEqual(c['status'],'확인완료');self.assertEqual(a['status'],'불일치')
        self.assertIn('A / 1번 : B / 1번 → B / 2번',a['differences'])
        self.assertIn('ID-2',a['baseline_detail']);self.assertIn('2번 회선',a['baseline_detail'])
        self.assertEqual(self.store.core(self.left,4)['core_id'],'')
        snapshot=self.snapshot();wf.FieldSurvey(self.store,self.h).report();self.assertEqual(self.snapshot(),snapshot)

    def test_swapped_real_ids_are_explicit_atomic_and_keep_original_annotations(self):
        s=self.store;self.save('A\tB\n1\t2\n2\t1\n3\t3');choices=self.swap_choices()
        before=self.snapshot();annotations=copy.deepcopy(wf.annotation_map(s));unrelated=[dict(s.core(self.left,3)),dict(s.core(self.right,3))]
        with self.assertRaises(ValueError):wf.field_preview(s,self.h,set(choices))
        preview=wf.field_resolution_preview(s,self.h,choices,'현장 확인한 두 회선 선번 교차')
        self.assertEqual(self.snapshot(),before);result=wf.field_commit_resolution(s,preview)
        self.assertTrue(result['backup'].exists());self.assertEqual(len(s.history_rows()),len(before[-1])+1)
        self.assertEqual(s.core(self.right,2)['core_id'],'ID-1');self.assertEqual(s.core(self.right,1)['core_id'],'ID-2')
        self.assertEqual(wf.annotation_map(s),annotations);self.assertEqual([dict(s.core(self.left,3)),dict(s.core(self.right,3))],unrelated)
        self.assertTrue(all(r['status']=='확인완료' for r in self.rows()));self.assertEqual(self.rows()[0]['baseline_relation'],'선번 다름')
        self.assertEqual(self.rows()[0]['treatment'],'수정·확인 완료');self.assertEqual(s.drawing_connection_progress()['rate'],100)
        saved=wf.field_records(s)[self.h]['corrections'][0];self.assertIn('ID-2',{r['core_id'] for r in saved['preserved']})
        self.assertEqual(wf.field_reference(s),before[2])
        after=(wf.plan_snapshot(s.conn),wf.field_records(s));s.undo();self.assertEqual((wf.plan_snapshot(s.conn),wf.field_records(s)),before[:2])
        s.redo();self.assertEqual((wf.plan_snapshot(s.conn),wf.field_records(s)),after)

    def test_memos_reference_and_corrections_survive_repaste_reopen_and_cloud_bundle(self):
        self.save('A\tB\n1\t2\n2\t1\n3\t3');row=self.rows()[0]
        wf.field_save_note(self.store,self.h,{row['key']},'A1은 현장 B2 · ID-1 확인')
        original=copy.deepcopy(wf.field_reference(self.store));choices=self.swap_choices()
        wf.field_commit_resolution(self.store,wf.field_resolution_preview(self.store,self.h,choices,'교차 확인'))
        self.reference=wf.field_capture_reference(self.store.conn,'나중에 바뀐 도면')
        self.save('B\tA\n2\t1\n1\t2\n3\t3')
        self.assertEqual(wf.field_reference(self.store),original)
        self.assertEqual(self.rows()[0]['note'],'A1은 현장 B2 · ID-1 확인')
        before=wf.field_records(self.store);path=self.store.path;self.store.close();self.store=code['Store'](path)
        self.assertEqual(wf.field_records(self.store),before);self.assertEqual(wf.field_reference(self.store),original)
        folder=self.root/'scenarios';folder.mkdir();self.store.backup_to(folder/'before.sqlite3')
        contents=wf.cloud_unpack(wf.cloud_bundle(self.store,folder));restored=self.root/'other.sqlite3';restored.write_bytes(contents['working.sqlite3'])
        other=code['Store'](restored)
        try:self.assertEqual(wf.field_records(other),before);self.assertEqual(wf.field_reference(other),original)
        finally:other.close()

    def test_displaced_identity_is_retained_and_does_not_disappear_from_completion(self):
        s=self.store;s.update_core(self.right,4,('LOST','기존 실제 내역','','','on'))
        self.save('A\tB\n1\t4\n2\t2\n3\t3');row=self.rows()[0];choices={row['key']:dict(s.core(self.left,1))}
        result=wf.field_commit_resolution(s,wf.field_resolution_preview(s,self.h,choices,'현장 ID-1 확인, LOST 위치 미확인'))
        self.assertFalse(s.all_core_rows('LOST'));pending=wf.field_pending_identities(s)
        self.assertEqual([p['core_id'] for p in pending],['LOST'])
        self.assertEqual(pending[0]['rows'][0]['detail'],'기존 실제 내역')
        report=s.drawing_connection_progress();self.assertEqual(report['total'],4);self.assertFalse(report['by_id']['LOST']['complete'])
        self.assertIn('LOST',{r['core_id'] for r in s.incomplete_core_groups()})
        self.assertTrue(any(r['core_id']=='LOST' for r in wf.field_check_rows(s)))
        with self.assertRaises(ValueError):wf.field_review_pending(s,self.h,pending[0]['id'],'재배정 확인','연결 안 됨')
        old=self.snapshot();wf.field_review_pending(s,self.h,pending[0]['id'],'GIS 오기록 확인','원본 중복 기재 확인')
        self.assertNotIn('LOST',s.drawing_connection_progress()['by_id']);self.assertEqual(wf.field_records(s)[self.h]['pending_identities'][0]['state'],'GIS 오기록 확인')
        s.undo();self.assertEqual(wf.field_records(s),old[1])

    def test_remote_route_changes_are_previewed_but_other_same_ids_stay_untouched(self):
        s=self.store;end=s.add_node('다음 끝',900,0);tail=s.add_cable(self.b,end,'TAIL','6C','기설')
        s.connect(self.b,(self.right,2),(tail,2));other=s.add_cable(self.a,end,'OTHER','6C','기설');s.update_core(other,6,('ID-2','분리된 같은 ID','','','off'))
        kept=dict(s.core(other,6));remote_splice=dict(s.splice_for(self.b,self.right,2));self.save('A\tB\n1\t2')
        choices={self.rows()[0]['key']:dict(s.core(self.left,1))};preview=wf.field_resolution_preview(s,self.h,choices,'양방향 끝단 확인')
        self.assertTrue(any('TAIL' in row[1] for row in preview['changes']))
        wf.field_commit_resolution(s,preview);self.assertEqual(s.core(tail,2)['core_id'],'ID-1')
        self.assertEqual(dict(s.core(other,6)),kept);self.assertEqual(dict(s.splice_for(self.b,self.right,2)),remote_splice)

    def test_locks_stale_and_backup_failure_never_partially_apply(self):
        s=self.store;self.save('A\tB\n1\t2\n2\t1');choices=self.swap_choices()
        s.set_node_locked(self.b,True);old=self.snapshot()
        with self.assertRaises(ValueError):wf.field_resolution_preview(s,self.h,choices,'잠금 시험')
        self.assertEqual(self.snapshot(),old);s.set_node_locked(self.b,False)
        preview=wf.field_resolution_preview(s,self.h,choices,'확인');old=self.snapshot()
        with patch.object(s,'backup_to',side_effect=OSError('backup failed')):
            with self.assertRaises(OSError):wf.field_commit_resolution(s,preview)
        self.assertEqual(self.snapshot(),old);wf.field_save_note(s,self.h,set(choices),'다른 편집');old=self.snapshot()
        with self.assertRaises(ValueError):wf.field_commit_resolution(s,preview)
        self.assertEqual(self.snapshot(),old)

    def test_repeated_survey_and_metadata_changes_require_recheck(self):
        self.save('A\tB\n1\t1');row=self.rows()[0];self.assertEqual(row['status'],'확인완료')
        self.store.update_core(self.left,1,('ID-1','수정된 내역','normal','','on'))
        self.assertEqual(self.rows()[0]['status'],'미확인');self.assertIn('1번 회선',self.rows()[0]['baseline_detail'])
        self.assertIn('수정된 내역',self.rows()[0]['current_detail'])
        self.save('A\tB\n1\t1');self.assertEqual(self.rows()[0]['status'],'확인완료')

    def test_invalid_duplicate_or_conflicting_assignments_are_read_only(self):
        self.save('A\tB\n1\t2\n2\t2');rows=self.rows();old=self.snapshot()
        choices={r['key']:dict(self.store.core(self.left,1)) for r in rows}
        with self.assertRaises(ValueError):wf.field_resolution_preview(self.store,self.h,choices,'중복')
        self.assertEqual(self.snapshot(),old)

    def test_manual_connection_cannot_create_a_loop_through_a_remote_facility(self):
        s=self.store;bridge=s.add_cable(self.a,self.b,'우회 케이블','6C','기설')
        s.connect(self.a,(self.left,6),(bridge,6),temporary=True);s.connect(self.b,(bridge,6),(self.right,6),temporary=True)
        self.save('A\tB\n6\t6');row=self.rows()[0];before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'순환'):wf.field_resolution_preview(s,self.h,{row['key']:dict(s.core(self.left,6))},'순환 검증')
        self.assertEqual(self.snapshot(),before)


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showwarning',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showinfo',return_value=None), \
             patch.object(code['messagebox'],'askyesno',return_value=True), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *args:errors.append(str(args))
            try:
                s=app.store;a=s.add_node('왼쪽',100,300);h=s.add_node('비교 함체',400,300);b=s.add_node('오른쪽',700,300)
                left=s.add_cable(a,h,'A','6C','기설');right=s.add_cable(h,b,'B','6C','기설')
                for i in (1,2,3):s.update_core(left,i,(f'ID-{i}',f'{i}번 회선','normal','','off'));s.connect(h,(left,i),(right,i))
                app.load_scenario('before');s=app.store;gis=app.scenario_path('gis').read_bytes();app.update()
                node=code['NodeDialog'](app,s,h);node.field_survey_open();app.update()
                dialog=next(w for w in node.winfo_children() if isinstance(w,wf.FieldSurveyDialog))
                before=wf.plan_snapshot(s.conn);app.clipboard_clear();app.clipboard_append('A\tB\n1\t2\n2\t1\n3\t3\n4\t4')
                dialog.sheet.focus_cell(0,0);dialog.sheet.tree.event_generate('<Control-v>');app.update();dialog.inspect(add_new=False);app.update()
                assert wf.plan_snapshot(s.conn)==before;assert s.core(left,4)['core_id']==''
                dialog.tree.selection_set('0');app.update();panel=dialog.comparison_panel
                assert 'B / 1번 → B / 2번' in panel.status.get();assert 'ID-2' in panel.texts[0].get('1.0','end')
                assert '현재 도면 연결' in dialog.tree.heading('current')['text']
                panel.note.set('A1은 B2 · 현장 ID-1 확인');panel.save_note();app.update()
                dialog.tree.selection_set(('0','1'));app.update();dialog.resolve_selected();app.update()
                editor=next(w for w in dialog.winfo_children() if isinstance(w,wf.FieldResolutionDialog))
                for i,cid in enumerate(('ID-1','ID-2')):
                    editor.tree.selection_set(str(i));app.update()
                    label=next(k for k,v in editor.labels.items() if v.get('core_id')==cid)
                    editor.source.set(label);editor.source_changed();editor.assign()
                editor.reason.set('현장 조사로 두 회선 선번 교차 확인');before=wf.plan_snapshot(s.conn)
                def cancel_preview():
                    preview=next(w for w in editor.winfo_children() if isinstance(w,wf.ConnectionRouteDialog));preview.destroy()
                app.after(150,cancel_preview);editor.preview();app.update();assert wf.plan_snapshot(s.conn)==before
                def accept_preview():
                    preview=next(w for w in editor.winfo_children() if isinstance(w,wf.ConnectionRouteDialog));preview.confirm()
                app.after(150,accept_preview);editor.preview();app.update()
                assert s.core(right,2)['core_id']=='ID-1' and s.core(right,1)['core_id']=='ID-2'
                assert dialog.rows[0]['baseline_relation']=='선번 다름';assert dialog.rows[0]['treatment']=='수정·확인 완료'
                dialog.filter.set('GIS와 다른 항목');dialog.show_rows();app.update();assert len(dialog.visible)==3
                archive=wf.FieldArchiveDialog(dialog,s,h);app.update();assert archive.items;assert '변경 전 보존내역' in archive.details.get('1.0','end');archive.destroy()
                assert app.scenario_path('gis').read_bytes()==gis
                dialog.destroy();node.destroy();app.scenario_path('gis').unlink() # comparison is embedded in the working drawing
                node=code['NodeDialog'](app,s,h);node.field_survey_open();app.update()
                reopened=next(w for w in node.winfo_children() if isinstance(w,wf.FieldSurveyDialog));reopened.tree.selection_set('0');app.update()
                assert reopened.rows[0]['note']=='A1은 B2 · 현장 ID-1 확인'
                assert 'ID-2' in reopened.comparison_panel.texts[0].get('1.0','end')
                assert reopened.rows[0]['treatment']=='수정·확인 완료';reopened.destroy();node.destroy();assert not errors,errors
            finally:app.on_close()
    print('PASS Windows Excel comparison-only save, three evidence panels, notes, explicit swap chooser, cancel/apply preview, archive and reopened GIS-free comparison')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CompareTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS frozen GIS evidence, exact field differences, atomic scoped identity swaps, preservation, pending completion, stale guards, backups and cloud bundle')
