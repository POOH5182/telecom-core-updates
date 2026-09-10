"""GIS-preserving field comparisons, explicit correction and local review gate."""
import os
from legacy_field_fixture import existing_field
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_field_survey import code,wf


class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.s=code['Store'](self.home/'drawing.sqlite3');s=self.s
        s.conn.execute("INSERT INTO meta VALUES('active_scenario','before')");s.conn.commit()
        self.a=s.add_node('시작',0,0);self.h=s.add_node('현장 함체',240,0)
        self.b=s.add_node('다음 함체',480,0);self.end=s.add_node('끝',720,0)
        self.left=s.add_cable(self.a,self.h,'A','6C','기설')
        self.right=s.add_cable(self.h,self.b,'B','6C','기설')
        self.tail=s.add_cable(self.b,self.end,'C','6C','기설')
        for i in (1,2):
            s.update_core(self.left,i,(f'ID-{i}',f'원래 내역 {i}','normal','','off'))
            s.connect(self.h,(self.left,i),(self.right,i));s.connect(self.b,(self.right,i),(self.tail,i))
        self.reference=wf.field_capture_reference(s.conn)
    def tearDown(self):self.s.close();self.temp.cleanup()
    def snapshot(self):return wf.plan_snapshot(self.s.conn),wf.field_records(self.s),wf.field_reference(self.s)
    def apply(self,raw,node=None):
        return wf.field_overlay_commit(self.s,wf.field_overlay_preview(self.s,node or self.h,raw,self.reference))
    def rows(self,node=None):return wf.FieldSurvey(self.s,node or self.h).report()
    def pair(self,a,ai,b,bi):return wf.field_pair(((a,ai),(b,bi)))
    def mark(self,rows,status='OK',node=None):
        return wf.field_local_mark(self.s,node or self.h,{r['key'] for r in rows},status,self.s.data_revision(),self.s._view_generation)

    def test_partial_2_to_2_preserves_1_to_1_and_incremental_observations(self):
        original=wf.plan_snapshot(self.s.conn);result=self.apply('A\tB\n2\t2')
        self.assertEqual(wf.plan_snapshot(self.s.conn),original)
        self.assertEqual(wf.field_local_summary(self.s,self.h),{'ok':1,'not_ok':1,'total':2})
        self.assertEqual(next(r for r in self.rows() if r['source']=='미조사')['slots'],self.pair(self.left,1,self.right,1))
        self.assertTrue(result['backup'].exists())
        self.apply('B\tA\n3\t3')
        observed={r['slots'] for r in self.rows() if r['source']=='조사표'}
        self.assertEqual(observed,{self.pair(self.left,2,self.right,2),self.pair(self.left,3,self.right,3)})
        self.assertIsNotNone(self.s.splice_for(self.h,self.left,1))

    def test_conflicting_field_numbers_preserve_gis_splices_and_all_content(self):
        original={tuple((r['cable_id'],r['core_index'])):r for r in self.s.all_core_rows()}
        remote=[dict(r) for r in self.s.conn.execute('SELECT * FROM splices WHERE node_id=?',(self.b,))]
        result=self.apply('A\tB\n1\t2\n2\t1')
        self.assertEqual((result['deferred'],result['added'],result['removed']),(2,0,0))
        self.assertEqual(wf.FieldSurvey(self.s,self.h).pairs,{self.pair(self.left,1,self.right,1),self.pair(self.left,2,self.right,2)})
        self.assertEqual({tuple((r['cable_id'],r['core_index'])):r for r in self.s.all_core_rows()},original)
        self.assertEqual([dict(r) for r in self.s.conn.execute('SELECT * FROM splices WHERE node_id=?',(self.b,))],remote)
        self.assertTrue(all(r['local_status']=='NOT OK' for r in self.rows()))
        with self.assertRaises(ValueError):self.mark(self.rows())
        self.assertEqual(wf.field_summary(self.s,self.h)['issues'],4)
        self.assertTrue(any(r['category']=='현장 NOT OK' for r in wf.field_check_rows(self.s)))

    def test_one_to_two_stays_pending_until_reviewed_edit_then_manual_ok(self):
        self.apply('A\tB\n2\t2')
        missing=next(r for r in self.rows() if r['source']=='미조사');self.mark([missing])
        original=wf.plan_snapshot(self.s.conn)
        result=self.apply('A\tB\n1\t2')
        self.assertEqual(wf.plan_snapshot(self.s.conn),original)
        self.assertEqual(result['deferred'],1)
        observed=next(r for r in self.rows() if r['source']=='조사표')
        self.assertTrue(observed['local_pending']);self.assertEqual(observed['local_mode'],'현장 선번 미반영')
        self.assertIn('A / 1번',observed['baseline_connection']);self.assertIn('B / 2번',observed['baseline_connection'])
        self.assertIn('B / 1번 → B / 2번',observed['difference_text'])
        self.assertTrue(all(r['local_status']=='NOT OK' for r in self.rows()))
        self.assertTrue(all(wf.field_local_slots(self.s,self.h)[slot]=='NOT OK' for slot in ((self.left,1),(self.right,1),(self.left,2),(self.right,2))))
        with self.assertRaises(ValueError):self.mark([observed])
        with self.assertRaises(ValueError):self.mark([next(r for r in self.rows() if r['key']==missing['key'])])
        saved=self.snapshot();path=self.s.path;self.s.close();self.s=code['Store'](path)
        self.assertEqual(self.snapshot(),saved)
        choice={observed['key']:dict(self.s.core(self.left,1))}
        preview=wf.field_resolution_preview(self.s,self.h,choice,'현장 1-2 확인 후 직접 수정')
        self.assertEqual(self.snapshot(),saved)
        wf.field_commit_resolution(self.s,preview)
        current=next(r for r in self.rows() if r['key']==observed['key'])
        self.assertFalse(current['local_pending']);self.assertEqual(current['local_status'],'NOT OK')
        self.mark([current]);current=next(r for r in self.rows() if r['key']==observed['key'])
        self.assertEqual(current['local_status'],'OK');self.assertEqual(current['treatment'],'수정·확인 완료')
        final=wf.plan_snapshot(self.s.conn)
        self.apply('A\tB\n1\t2')
        self.assertEqual(wf.plan_snapshot(self.s.conn),final)
        self.assertEqual(next(r for r in self.rows() if r['key']==observed['key'])['local_status'],'OK')
        self.assertEqual(wf.field_reference(self.s),self.reference)

    def test_new_gis_missing_pair_gets_temporary_identity_and_automatic_ok(self):
        result=self.apply('A\tB\n3\t3\n4\t4')
        self.assertEqual(result['auto_ok'],2)
        self.assertEqual(sum(c[0]=='현장 신규 자동 OK' for c in result['changes']),2)
        ids=[]
        for index in (3,4):
            cid=self.s.core(self.left,index)['core_id'];ids.append(cid)
            self.assertTrue(cid.startswith('임시-'));self.assertEqual(self.s.core(self.right,index)['core_id'],cid)
            row=next(r for r in self.rows() if (self.left,index) in r['slots']);self.assertEqual(row['local_status'],'OK')
            self.assertEqual(row['local_mode'],'현장 신규 자동 OK');self.assertEqual(row['treatment'],'신규 자동 OK')
            self.assertEqual(row['baseline_relation'],'선번 다름')
        self.assertNotEqual(*ids);self.assertEqual(wf.field_reference(self.s),self.reference)
        self.apply('A\tB\n3\t3')
        self.assertEqual([self.s.core(self.left,i)['core_id'] for i in (3,4)],ids)
        self.assertEqual(self.s.core(self.tail,3)['core_id'],'') # No remote identity propagation.
        # Existing real metadata in a changed pair is never replaced by a temp ID.
        self.apply('A\tB\n1\t5')
        self.assertEqual(self.s.core(self.left,1)['core_id'],'ID-1')
        self.assertEqual(self.s.core(self.right,5)['core_id'],'')
        self.assertEqual(self.s.core(self.right,1)['core_id'],'ID-1')

    def test_saved_v69_temporary_pair_becomes_ok_without_rewriting_data(self):
        # V69 persisted a real temporary splice and survey evidence, with no
        # local decision for its automatically computed NOT OK status.
        with self.s.action('V69 신규 임시 연결 저장'):
            wf.field_keep_reference(self.s,self.reference)
            for cable in (self.left,self.right):
                self.s._write_core(cable,3,('임시-9001','기존 현장 내역','normal','','off'))
            self.s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(self.h,self.left,3,self.right,3))
            engine=wf.FieldSurvey(self.s,self.h)
            engine.record.update(text='A\tB\n3\t3',overlay_mode=True,overlay_policy='preserve_gis',gis_known=True,
                                 gis_pairs=[list(p) for p in wf.FieldReference(self.reference,self.h).pairs])
            engine.persist('V69 현장 조사 저장')
        saved=self.snapshot();path=self.s.path;self.s.close();self.s=code['Store'](path)
        revision=self.s.data_revision()
        row=next(r for r in self.rows() if r['source']=='조사표')
        self.assertEqual(row['local_status'],'OK');self.assertEqual(row['local_mode'],'현장 신규 자동 OK')
        self.assertEqual(self.snapshot(),saved);self.assertEqual(self.s.data_revision(),revision)
        self.assertEqual(wf.field_local_slots(self.s,self.h)[(self.right,3)],'OK')
        self.assertEqual(wf.field_local_slots(self.s,self.b)[(self.right,3)],'NOT OK')
        # An intentional manual NOT OK remains available after automatic OK.
        wf.field_local_mark(self.s,self.h,{row['key']},'NOT OK',self.s.data_revision(),self.s._view_generation,'현장 재조사 필요')
        self.apply('A\tB\n3\t3')
        row=next(r for r in self.rows() if r['source']=='조사표')
        self.assertEqual(row['local_status'],'NOT OK');self.assertEqual(row['local_mode'],'수동 NOT OK')
        self.assertEqual(row['local_reason'],'현장 재조사 필요')

    def test_automatic_temporary_ok_requires_matching_ids_and_actual_connection(self):
        self.apply('A\tB\n3\t3');cid=self.s.core(self.left,3)['core_id']
        with self.s.action('코어ID 불일치 확인'):
            self.s.conn.execute("UPDATE cores SET core_id='임시-9999' WHERE cable_id=? AND core_index=3",(self.right,))
        row=next(r for r in self.rows() if r['source']=='조사표');self.assertEqual(row['local_status'],'NOT OK')
        with self.s.action('코어ID 복구 후 연결 해제'):
            self.s.conn.execute('UPDATE cores SET core_id=? WHERE cable_id=? AND core_index=3',(cid,self.right))
            self.s.conn.execute('DELETE FROM splices WHERE node_id=? AND core1_index=3',(self.h,))
        row=next(r for r in self.rows() if r['source']=='조사표')
        self.assertEqual(row['local_status'],'NOT OK');self.assertTrue(row['local_pending'])

    def test_known_gis_or_current_identity_is_not_a_new_blank_pair(self):
        # Even empty current slots must not hide a known GIS allocation.
        with self.s.action('수동 배정 해제'):
            self.s.conn.execute('DELETE FROM splices WHERE node_id=?',(self.h,))
            for cable in (self.left,self.right):
                self.s.conn.execute("UPDATE cores SET core_id='' WHERE cable_id=? AND core_index=1",(cable,))
        before=wf.plan_snapshot(self.s.conn);result=self.apply('A\tB\n1\t1')
        self.assertEqual(wf.plan_snapshot(self.s.conn),before);self.assertEqual(result['deferred'],1)
        self.s.update_core(self.left,3,('MANUAL','수동으로 입력한 내역','normal','','off'))
        before=wf.plan_snapshot(self.s.conn);self.apply('A\tB\n3\t3')
        self.assertEqual(wf.plan_snapshot(self.s.conn),before)
        self.assertEqual(self.s.core(self.right,3)['core_id'],'')

    def test_local_checks_are_independent_and_id_changes_invalidate_ok_not_names(self):
        self.apply('A\tB\n2\t2');self.apply('B\tC\n2\t2',self.b)
        missing=next(r for r in self.rows() if r['source']=='미조사')
        self.mark([missing])
        self.assertEqual(wf.field_local_slots(self.s,self.h)[(self.right,1)],'OK')
        self.assertEqual(wf.field_local_slots(self.s,self.b)[(self.right,1)],'NOT OK')
        self.s.update_core(self.left,1,('ID-1','이름만 변경','normal','','off'))
        self.assertEqual(next(r for r in self.rows() if r['key']==missing['key'])['local_status'],'OK')
        with self.s.action('코어ID 정리'):
            self.s.conn.execute("UPDATE cores SET core_id='ID-CHANGED' WHERE core_id='ID-1'")
        self.assertEqual(next(r for r in self.rows() if r['key']==missing['key'])['local_status'],'NOT OK')
        self.mark([next(r for r in self.rows() if r['row']==2)],'NOT OK')
        self.apply('A\tB\n2\t2')
        self.assertEqual(next(r for r in self.rows() if r['row']==2)['local_status'],'NOT OK')

    def test_manual_identity_resolution_then_local_ok_keeps_original_history(self):
        self.apply('A\tB\n1\t2\n2\t1')
        choices={r['key']:dict(self.s.core(self.left,next(i for c,i in r['slots'] if c==self.left))) for r in self.rows() if r['source']=='조사표'}
        result=wf.field_commit_resolution(self.s,wf.field_resolution_preview(self.s,self.h,choices,'현장 양단의 ID 확인'))
        self.assertTrue(result['backup'].exists());self.assertTrue(all(r['local_status']=='NOT OK' for r in self.rows()))
        self.mark(self.rows());self.assertTrue(all(r['local_status']=='OK' for r in self.rows()))
        self.assertTrue(all(r['baseline_relation']=='선번 다름' for r in self.rows()))
        records=wf.field_records(self.s)[self.h]['corrections']
        self.assertEqual(len(records),2);self.assertEqual(records[0]['kind'],'현장 조사 저장')
        self.assertEqual(records[0]['preserved'][0]['core_id'] in ('ID-1','ID-2'),True)

    def test_invalid_input_locks_staleness_and_failed_backup_are_all_or_nothing(self):
        for raw in ('A\tB\n1\t2\n1\t1','A\tB\n1\t999','A\tB\n1\t','A\tB\n'):
            original=self.snapshot()
            with self.assertRaises(ValueError):wf.field_overlay_preview(self.s,self.h,raw,self.reference)
            self.assertEqual(self.snapshot(),original)
        self.s.set_node_locked(self.h,True);original=self.snapshot()
        with self.assertRaises(ValueError):self.apply('A\tB\n1\t2')
        self.assertEqual(self.snapshot(),original);self.s.set_node_locked(self.h,False)
        self.s.set_node_locked(self.a,True);original=self.snapshot()
        with self.assertRaises(ValueError):self.apply('A\tB\n1\t2\n3\t3')
        self.assertEqual(self.snapshot(),original);self.s.set_node_locked(self.a,False)
        preview=wf.field_overlay_preview(self.s,self.h,'A\tB\n1\t2',self.reference);original=self.snapshot()
        with patch.object(self.s,'backup_to',side_effect=OSError('backup failed')):
            with self.assertRaises(OSError):wf.field_overlay_commit(self.s,preview)
        self.assertEqual(self.snapshot(),original)
        self.s.set_node_details(self.h,'수정된 함체');original=self.snapshot()
        with self.assertRaises(ValueError):wf.field_overlay_commit(self.s,preview)
        self.assertEqual(self.snapshot(),original)

    def test_undo_reopen_cloud_and_frozen_gis_preserve_overlay_and_checks(self):
        original=self.snapshot();groups=len(self.s.history_rows())
        self.apply('A\tB\n1\t2\n2\t1\n3\t3');after=self.snapshot()
        self.assertEqual(len(self.s.history_rows()),groups+1)
        self.s.undo();self.assertEqual(self.snapshot(),original);self.s.redo();self.assertEqual(self.snapshot(),after)
        folder=self.home/'scenarios';folder.mkdir()
        for kind in ('gis','before','after'):self.s.backup_to(folder/(kind+'.sqlite3'))
        contents=wf.cloud_unpack(wf.cloud_bundle(self.s,folder));target=self.home/'restored.sqlite3';target.write_bytes(contents['working.sqlite3'])
        other=code['Store'](target)
        try:self.assertEqual(wf.field_records(other),wf.field_records(self.s));self.assertEqual(wf.field_reference(other),self.reference)
        finally:other.close()
        path=self.s.path;self.s.close();self.s=code['Store'](path)
        self.assertEqual(self.snapshot(),after)

    def test_display_toggle_is_independent_and_terminal_rn_rules_remain(self):
        self.apply('A\tB\n2\t2');warning=self.s.node_warning_summary()[self.h]
        options=dict(code['DISPLAY_DEFAULTS'],badges=False)
        badges=code['node_badge_rows'](code['visible_node_warning'](warning,options))
        self.assertEqual([b[0] for b in badges],['OK 1','NOT OK 1'])
        options['field_checks']=False
        self.assertFalse(code['node_badge_rows'](code['visible_node_warning'](warning,options)))
        path=self.home/'display_options.json';code['save_display_options'](path,options)
        self.assertFalse(code['read_display_options'](path)['field_checks'])
        self.assertFalse(wf.field_local_summary(self.s,self.a)['total'])
        rn=self.s.add_node('RN',900,0,'rn');self.assertTrue(wf.field_required(self.s,self.s.node(rn)))


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'askyesno',return_value=True), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *args:errors.append(str(args))
            try:
                s=app.store;a=s.add_node('시작',140,160);h=s.add_node('현장 함체',380,160);b=s.add_node('다음 함체',620,160);end=s.add_node('끝',860,160)
                left=s.add_cable(a,h,'A','6C','기설');right=s.add_cable(h,b,'B','6C','기설');tail=s.add_cable(b,end,'C','6C','기설')
                for i in (1,2):
                    s.update_core(left,i,(f'ID-{i}',f'원본 {i}','normal','','off'));s.connect(h,(left,i),(right,i));s.connect(b,(right,i),(tail,i))
                assert (existing_field(app) or app.load_scenario('before'));s=app.store;gis=app.scenario_path('gis').read_bytes()
                node=code['NodeDialog'](app,s,h);node.field_survey_open();app.update()
                dialog=next(w for w in node.winfo_children() if isinstance(w,wf.FieldSurveyDialog))
                sheet=dialog.sheet;sheet.focus_cell(0,0);app.clipboard_clear();app.clipboard_append('A\tB\n2\t2')
                sheet.tree.event_generate('<Control-v>');app.update();before=wf.plan_snapshot(s.conn)
                def review(accept):
                    popup=next(w for w in dialog.winfo_children() if isinstance(w,wf.TableDialog))
                    if accept:popup.confirm()
                    else:popup.destroy()
                app.after(200,lambda:review(False));dialog.overlay_button.invoke();app.update()
                assert wf.plan_snapshot(s.conn)==before and not wf.field_records(s)
                app.after(200,lambda:review(True));dialog.overlay_button.invoke();app.update()
                assert s.splice_for(h,left,1) and wf.field_local_summary(s,h)=={'ok':1,'not_ok':1,'total':2}
                dialog.filter.set('NOT OK');dialog.show_rows();app.update();assert len(dialog.visible)==1
                dialog.tree.selection_set('0');dialog.mark('OK');app.update()
                assert wf.field_local_slots(s,h)[(right,1)]=='OK' and wf.field_local_slots(s,b)[(right,1)]=='NOT OK'
                # The enclosure left/right trees reflect the local endpoint status.
                node.left_var.set(next(k for k,v in node.by_label.items() if v==left))
                node.right_var.set(next(k for k,v in node.by_label.items() if v==right));node.reload_all();app.update()
                for tree,var in ((node.left_tree,node.left_var),(node.right_tree,node.right_var)):
                    cid=node.by_label.get(var.get())
                    if cid in (left,right):assert tree.set('1','field')=='OK'
                app.clipboard_clear();app.clipboard_append('A\tB\n1\t2\n2\t1\n3\t3');sheet.paste_from_a1();app.update()
                app.after(200,lambda:review(True));dialog.overlay_button.invoke();app.update()
                assert s.core(left,1)['core_id']=='ID-1' and s.core(right,2)['core_id']=='ID-2'
                assert wf.FieldSurvey(s,h).pairs=={wf.field_pair(((left,i),(right,i))) for i in (1,2,3)}
                assert s.core(left,3)['core_id']==s.core(right,3)['core_id'] and s.core(left,3)['core_id'].startswith('임시-')
                assert '현장 선번 미반영 2건' in dialog.summary.get()
                dialog.filter.set('현장 선번 미반영');dialog.show_rows();app.update();assert len(dialog.visible)==2
                assert all(dialog.tree.set(iid,'treatment')=='현장 선번 미반영' for iid in dialog.tree.get_children())
                dialog.tree.selection_set('0');app.update()
                assert '미반영' in dialog.comparison_panel.status.get()
                assert '임시코어 자동 OK 1건' in dialog.summary.get()
                dialog.filter.set('OK');dialog.show_rows();app.update();assert len(dialog.visible)==1
                assert dialog.tree.set('0','treatment')=='현장 신규 자동 OK'
                dialog.tree.selection_set('0');app.update();assert '자동 OK' in dialog.comparison_panel.status.get()
                assert node.left_tree.set('3','field')=='OK' and node.right_tree.set('3','field')=='OK'
                dialog.filter.set('NOT OK');dialog.show_rows();app.update();assert len(dialog.visible)==4
                dialog.tree.cycle_sort('current');app.update()
                assert all(dialog.tree.set(iid,'status')=='NOT OK' for iid in dialog.tree.get_children())
                row=next(r for r in dialog.rows if (left,3) in r['slots'])
                assert row['local_status']=='OK' and row['local_mode']=='현장 신규 자동 OK'
                assert wf.field_local_slots(s,h)[(right,3)]=='OK'
                archive=wf.FieldArchiveDialog(dialog,s,h);app.update();assert len(archive.items)==2
                archive.tree.selection_set('0');archive.pick();assert '현장 선번' in archive.details.get('1.0','end');archive.destroy()
                app.display_options['badges']=False;app.display_options['field_checks']=True;app.refresh();app.update()
                assert 'NOT OK 4' in app.drawing_svg()
                settings=code['DisplaySettingsDialog'](app);settings.values['field_checks'].set(False);settings.apply();app.update()
                assert 'NOT OK' not in app.drawing_svg()
                texts=[app.canvas.itemcget(i,'text') for i in app.canvas.find_all() if app.canvas.type(i)=='text']
                assert not any('NOT OK' in t or t.startswith('OK ') for t in texts)
                # A reviewed correction changes the connections; OK is a separate step.
                dialog.reload();dialog.filter.set('현장 선번 미반영');dialog.show_rows();app.update()
                dialog.tree.selection_set(('0','1'));dialog.resolve_selected();app.update()
                editor=next(w for w in dialog.winfo_children() if isinstance(w,wf.FieldResolutionDialog))
                for index,row in enumerate(editor.rows):
                    number=next(i for c,i in row['slots'] if c==left)
                    editor.tree.selection_set(str(index));app.update()
                    editor.source.set(next(k for k,v in editor.labels.items() if v.get('core_id')==f'ID-{number}'))
                    editor.source_changed();editor.assign()
                editor.reason.set('GIS와 현장 차이 확인 후 선번 직접 수정')
                def accept_correction():
                    popup=next(w for w in editor.winfo_children() if isinstance(w,wf.ConnectionRouteDialog));popup.confirm()
                app.after(200,accept_correction);editor.preview();app.update()
                assert wf.FieldSurvey(s,h).pairs=={wf.field_pair(((left,1),(right,2))),wf.field_pair(((left,2),(right,1))),wf.field_pair(((left,3),(right,3)))}
                assert not any(r['local_pending'] for r in dialog.rows)
                dialog.filter.set('NOT OK');dialog.show_rows();app.update();assert len(dialog.visible)==2
                dialog.tree.selection_set(('0','1'));dialog.mark('OK');app.update()
                assert all(r['local_status']=='OK' for r in dialog.rows)
                dialog.filter.set('수정·확인 완료');dialog.show_rows();app.update();assert len(dialog.visible)==2
                assert app.scenario_path('gis').read_bytes()==gis
                dialog.destroy();node.destroy()
                reopened=code['NodeDialog'](app,s,h);reopened.field_survey_open();app.update()
                saved=next(w for w in reopened.winfo_children() if isinstance(w,wf.FieldSurveyDialog))
                assert len([r for r in saved.rows if r['source']=='조사표'])==3
                assert next(r for r in saved.rows if (left,3) in r['slots'])['local_mode']=='현장 신규 자동 OK'
                saved.destroy();reopened.destroy();assert not errors,errors
            finally:app.on_close()
    print('PASS Windows automatic OK for new temporary field cores, retained GIS mismatches, explicit correction, endpoint columns, archive, display and reopen')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(OverlayTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS GIS-preserving field comparison, deferred mismatches, explicit correction then OK, temporary cores, atomic backup/history and GIS preservation')
