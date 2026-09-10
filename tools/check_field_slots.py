"""V72: actual field topology, independent identities and reviewed finalization."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_field_survey import code,wf
from legacy_field_fixture import existing_field


class ScenarioHarness:
    """Exercise the real App scenario methods without needing a Tk display."""
    def __init__(self,store):
        self.store=store;self.cloud=None;self.status=unittest.mock.Mock()
        self.scenario_saved_revision=store.data_revision()
        self.highlight_blink_job=None;self.selected=set();self.highlight_cables=set();self.highlight_cable_colors={}
        self.refresh_count=0
    def __getattr__(self,name):
        method=code['App'].__dict__.get(name)
        if callable(method):return method.__get__(self,type(self))
        raise AttributeError(name)
    def scenario_folder(self):
        path=self.store.path.parent/'scenarios';path.mkdir(exist_ok=True);return path
    def update_title(self):pass
    def refresh(self):self.refresh_count+=1
    def manual_backup(self,silent=False):
        path=self.store.path.parent/'working-backup.sqlite3';self.store.backup_to(path);return path


class SlotFieldTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        gis=code['Store'](self.home/'gis-working.sqlite3')
        gis.conn.execute("INSERT INTO meta VALUES('active_scenario','gis')");gis.conn.commit()
        self.nodes=[gis.add_node(name,i*240,0) for i,name in enumerate(('끝 A','함체 1','함체 2','끝 B'))]
        self.cables=[gis.add_cable(self.nodes[i],self.nodes[i+1],name,'6C','기설') for i,name in enumerate(('A','B','C'))]
        gis.update_core(self.cables[0],1,('CORE-A','GIS 내역','normal','','on'))
        for i in (1,2):gis.connect(self.nodes[i],(self.cables[i-1],1),(self.cables[i],1))
        gis.conn.execute("UPDATE cores SET signal='on' WHERE core_index=1");gis.conn.commit()
        self.original=wf.field_capture_reference(gis.conn)['snapshot'];self.gis=self.home/'gis.sqlite3';gis.backup_to(self.gis);gis.close()
        self.gis_bytes=self.gis.read_bytes();self.path=self.home/'field.sqlite3'
        wf.field_slot_copy(self.gis,self.path);self.s=code['Store'](self.path)

    def tearDown(self):self.s.close();self.temp.cleanup()
    def slot(self,cable,index=1):return self.cables[cable],index
    def set(self,cable,index,cid,name='',signal='unknown'):
        self.s.update_core(self.cables[cable],index,(cid,name,'normal','',signal))
    def apply(self,node,raw):return wf.field_overlay_commit(self.s,wf.field_overlay_preview(self.s,self.nodes[node],raw))
    def connect_all(self):self.apply(1,'A\tB\n1\t1');self.apply(2,'B\tC\n1\t1')
    def audit(self,cable=0,index=1):return wf.field_slot_audit(self.s)['by_slot'][self.slot(cable,index)]
    def confirm(self,cable=0,index=1,cid='CORE-A',name='확정 내역',cleanup=True):
        return wf.field_slot_confirm_commit(self.s,wf.field_slot_confirm_preview(self.s,self.slot(cable,index),cid,name,cleanup))
    def snapshot(self):return wf.plan_snapshot(self.s.conn),wf.state(self.s),wf.field_reference(self.s)
    def splices(self):return sorted(tuple(r) for r in self.s.conn.execute('SELECT * FROM splices'))

    def test_new_copy_clears_only_assignments_preserves_gis_slots_ports_locks(self):
        self.assertTrue(wf.field_slot_mode(self.s));self.assertEqual(self.splices(),[])
        actual=wf.field_capture_reference(self.s.conn)['snapshot']
        for table in ('nodes','cables','cores','ports','core_annotations'):self.assertEqual(actual[table],self.original[table])
        self.assertEqual(wf.field_reference(self.s)['snapshot'],self.original)
        self.assertEqual(self.gis.read_bytes(),self.gis_bytes)
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.s.check_auto_splice_on_open(self.nodes[1]);self.assertEqual(self.splices(),[])
        self.s.auto_splice_slots(node_ids=self.nodes);self.assertEqual(self.splices(),[])
        self.s.set_node_locked(self.nodes[1],True);self.s.backup_to(self.home/'locked-gis.sqlite3')
        wf.field_slot_copy(self.home/'locked-gis.sqlite3',self.home/'locked-field.sqlite3')
        other=code['Store'](self.home/'locked-field.sqlite3')
        try:
            self.assertTrue(wf.node_locked(other,self.nodes[1]))
            with self.assertRaises(ValueError):other.connect(self.nodes[1],self.slot(0),self.slot(1))
        finally:other.close()

    def test_recopy_from_active_field_clears_connections_and_keeps_latest_backup(self):
        import shutil
        app=ScenarioHarness(self.s);shutil.copy2(self.gis,app.scenario_path('gis'))
        self.s.backup_to(app.scenario_path('before'))
        self.connect_all();self.set(1,2,'FIELD-EDIT','복사 직전 수정','off')
        before=self.snapshot();gis=app.scenario_path('gis').read_bytes()
        with patch.object(code['messagebox'],'showinfo'):
            self.assertTrue(app.copy_gis_to_field(replace=True))
        self.assertTrue(wf.field_slot_mode(self.s));self.assertEqual(self.splices(),[])
        self.assertEqual(wf.field_records(self.s),{})
        self.assertEqual(self.s.core(*self.slot(1,2))['core_id'],'')
        self.assertEqual(app.scenario_path('gis').read_bytes(),gis)
        archive=next(app.scenario_folder().glob('before_previous_*.sqlite3'))
        old=code['Store'](archive)
        try:self.assertEqual((wf.plan_snapshot(old.conn),wf.state(old),wf.field_reference(old)),before)
        finally:old.close()
        self.assertGreater(app.refresh_count,0)
        self.assertIn('접속 연결 0건',app.status.set.call_args.args[0])
        self.connect_all();self.assertTrue(app.copy_gis_to_field(replace=True))
        self.assertEqual(self.splices(),[])
        self.assertEqual(len(list(app.scenario_folder().glob('before_previous_*.sqlite3'))),2)
        saved=code['Store'](app.scenario_path('before'))
        try:
            self.assertTrue(wf.field_slot_mode(saved))
            self.assertEqual(saved.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0],0)
        finally:saved.close()

    def test_recopy_requires_saved_gis_and_never_uses_field_as_source(self):
        app=ScenarioHarness(self.s);self.connect_all();before=self.snapshot()
        with patch.object(code['messagebox'],'showinfo') as notice:
            self.assertFalse(app.copy_gis_to_field(replace=True))
        self.assertEqual(self.snapshot(),before)
        self.assertFalse(app.scenario_path('gis').exists())
        self.assertIn('GIS',str(notice.call_args))

    def test_field_allocation_accepts_conflicting_ids_without_rewriting_other_slots(self):
        self.set(1,2,'CORE-B','다른 내역','off');before=[dict(r) for r in self.s.all_core_rows()]
        self.apply(1,'A\tB\n1\t2');self.apply(2,'B\tC\n2\t1')
        self.assertEqual([dict(r) for r in self.s.all_core_rows()],before)
        self.assertIn('서로 다른 코어ID',self.audit()['reason']);self.assertIn('신호 불일치',self.audit()['reason'])
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertTrue(self.s.error_core_rows(self.nodes[1]))
        self.assertTrue(all(r['local_status']=='NOT OK' for r in wf.FieldSurvey(self.s,self.nodes[1]).report()))
        with self.assertRaises(ValueError):self.confirm()

    def test_normal_connect_and_excel_paste_do_not_promote_or_copy_identity(self):
        self.set(1,1,'OTHER','원래 다른 이름','off')
        self.s.connect(self.nodes[1],self.slot(0),self.slot(1))
        self.assertEqual(self.s.core(*self.slot(0))['core_id'],'CORE-A')
        self.assertEqual(self.s.core(*self.slot(1))['core_id'],'OTHER')
        self.s.apply_core_identity_changes(self.cables[1],[(1,'CORE-A','새 이름')])
        self.assertEqual(self.s.core(*self.slot(0))['detail'],'GIS 내역')
        self.assertEqual(self.s.core(*self.slot(1))['detail'],'새 이름')
        self.assertEqual(self.s.core(*self.slot(1))['signal'],'off')
        self.s.apply_core_identity_changes(self.cables[1],[(1,'','')])
        self.assertEqual(self.s.core(*self.slot(1))['core_id'],'CORE-A')
        self.s.set_core_signal('CORE-A','unknown',slot=self.slot(1))
        self.assertEqual(self.s.core(*self.slot(0))['signal'],'on')

    def test_neutral_temporary_and_unknown_signal_need_explicit_final_confirmation(self):
        self.set(1,1,'임시-77','','unknown');self.connect_all()
        self.assertTrue(self.audit()['coherent']);self.assertFalse(self.audit()['complete'])
        self.assertIn('최종 확정',self.audit()['reason'])
        self.assertEqual(self.s.core(*self.slot(1))['core_id'],'임시-77')
        self.confirm()
        self.assertEqual({self.s.core(*self.slot(i))['core_id'] for i in range(3)},{'CORE-A'})
        self.assertEqual({self.s.core(*self.slot(i))['detail'] for i in range(3)},{'확정 내역'})
        self.assertEqual(self.s.core(*self.slot(1))['signal'],'unknown')
        self.assertEqual((wf.completion_report(self.s)['total'],wf.completion_report(self.s)['done']),(1,1))
        self.assertFalse([r for r in self.s.before_drawing_check_rows() if r['level']=='오류'])

    def test_name_only_and_signal_only_paths_are_mandatory_and_can_be_identified(self):
        for i in range(3):self.set(i,1,'','이름만' if i==0 else '', 'on' if i==2 else 'unknown')
        self.connect_all();self.assertTrue(self.audit()['coherent'])
        self.assertEqual(wf.completion_report(self.s)['total'],1)
        self.confirm(cid='RESOLVED-ID',name='확인한 회선')
        self.assertTrue(wf.completion_report(self.s)['by_id']['RESOLVED-ID']['complete'])

    def test_move_exchange_preserves_all_splices_and_default_signals_undo_redo(self):
        self.set(1,2,'OTHER','교환할 이름','off');self.connect_all()
        before=self.snapshot();splices=self.splices();history=len(self.s.history_rows())
        preview=wf.field_slot_transfer_preview(self.s,self.slot(1),self.slot(1,2))
        self.assertEqual(self.snapshot(),before)
        result=wf.field_slot_transfer_commit(self.s,preview)
        self.assertTrue(result['backup'].exists());self.assertEqual(self.splices(),splices)
        self.assertEqual(self.s.core(*self.slot(1))['core_id'],'OTHER')
        self.assertEqual(self.s.core(*self.slot(1))['signal'],'on')
        self.assertEqual(self.s.core(*self.slot(1,2))['core_id'],'CORE-A')
        self.assertEqual(self.s.core(*self.slot(1,2))['signal'],'off')
        self.assertEqual(len(self.s.history_rows()),history+1);after=self.snapshot()
        self.s.undo();self.assertEqual(self.snapshot(),before);self.s.redo();self.assertEqual(self.snapshot(),after)
        wf.field_slot_transfer_commit(self.s,wf.field_slot_transfer_preview(self.s,self.slot(1),self.slot(1,2),True))
        self.assertEqual(self.s.core(*self.slot(1))['signal'],'off')

    def test_final_confirmation_clears_only_same_id_unconnected_waiting_and_keeps_signals(self):
        self.set(1,3,'CORE-A','GIS 남은 내역','off')
        self.set(1,4,'DIFFERENT','확정 내역','off')
        self.set(1,5,'CORE-A','ON은 유지','on');self.connect_all();splices=self.splices()
        before=self.snapshot();preview=wf.field_slot_confirm_preview(self.s,self.slot(0),'CORE-A','최종 이름')
        self.assertEqual(self.snapshot(),before)
        result=wf.field_slot_confirm_commit(self.s,preview)
        self.assertEqual(result['cleared'],1);self.assertEqual(result['kept'],1)
        self.assertEqual(self.splices(),splices)
        self.assertEqual((self.s.core(*self.slot(1,3))['core_id'],self.s.core(*self.slot(1,3))['detail']),('',''))
        self.assertEqual(self.s.core(*self.slot(1,3))['signal'],'off')
        self.assertEqual(self.s.core(*self.slot(1,4))['core_id'],'DIFFERENT')
        self.assertEqual(self.s.core(*self.slot(1,5))['signal'],'on')
        self.assertFalse(wf.completion_report(self.s)['by_id']['CORE-A']['complete'])
        self.s.undo();self.assertEqual(self.snapshot(),before)
        self.assertEqual(self.gis.read_bytes(),self.gis_bytes)

    def test_cleanup_can_be_disabled_and_required_pending_still_blocks_100_percent(self):
        self.set(1,3,'CORE-A','아직 대기','off');self.connect_all();self.confirm(cleanup=False)
        self.assertEqual(self.s.core(*self.slot(1,3))['core_id'],'CORE-A')
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.confirm();self.assertEqual(wf.completion_report(self.s)['done'],1)

    def test_signal_disagreement_and_disconnected_ends_cannot_be_overridden(self):
        self.connect_all();self.set(1,1,'CORE-A','이름은 달라도 됨','off')
        self.assertFalse(self.audit()['coherent'])
        with self.assertRaises(ValueError):self.confirm()
        self.set(1,1,'CORE-A','이름은 달라도 됨','unknown');self.confirm()
        self.s.disconnect(self.nodes[2],*self.slot(1))
        self.assertFalse(self.audit()['complete'])
        with self.assertRaises(ValueError):self.confirm()

    def test_final_approval_rechecks_after_signal_change_and_survives_reopen_history(self):
        self.connect_all();self.confirm();confirmed=self.snapshot()
        self.s.close();self.s=code['Store'](self.path)
        self.assertEqual(self.snapshot(),confirmed);self.assertTrue(self.audit()['complete'])
        self.set(1,1,'CORE-A','확정 내역','off');self.assertFalse(self.audit()['complete'])
        self.s.undo();self.assertTrue(self.audit()['complete'])
        with self.s.action('위치만 변경'):self.s.conn.execute('UPDATE nodes SET x=x+5 WHERE id=?',(self.nodes[1],))
        self.assertTrue(self.audit()['complete'])

    def test_manual_not_ok_requires_review_and_final_confirmation_clears_it(self):
        self.connect_all();row=next(r for r in wf.FieldSurvey(self.s,self.nodes[1]).report() if r['source']=='조사표')
        wf.field_local_mark(self.s,self.nodes[1],{row['key']},'NOT OK',self.s.data_revision(),self.s._view_generation,'현장 재확인')
        self.assertFalse(self.audit()['complete']);self.confirm()
        self.assertTrue(self.audit()['complete'])
        self.assertTrue(all(r['local_status']=='OK' for r in wf.FieldSurvey(self.s,self.nodes[1]).report()))

    def test_json_retains_each_slot_signal_policy_reference_and_confirmation(self):
        self.set(1,1,'임시-19','','unknown');self.connect_all();self.confirm()
        pack=wf.field_slot_json_pack(self.s)
        self.set(1,1,'CORE-A','확정 내역','off');self.assertFalse(self.audit()['complete'])
        with self.s.action('정확한 슬롯 JSON 복원'):wf.field_slot_json_restore(self.s,json.loads(json.dumps(pack)))
        self.assertEqual(self.s.core(*self.slot(1))['signal'],'unknown');self.assertTrue(self.audit()['complete'])
        self.assertEqual(wf.field_reference(self.s),pack['reference'])
        invalid=json.loads(json.dumps(pack));invalid['rows'].pop();before=self.snapshot()
        with self.assertRaises(ValueError):
            with self.s.action('잘못된 JSON 복원'):wf.field_slot_json_restore(self.s,invalid)
        self.assertEqual(self.snapshot(),before)

    def test_stale_preview_and_locked_remote_target_roll_back_everything(self):
        self.connect_all();preview=wf.field_slot_confirm_preview(self.s,self.slot(0),'CORE-A','확정 이름')
        self.set(1,3,'OTHER','추가 입력')
        with self.assertRaises(ValueError):wf.field_slot_confirm_commit(self.s,preview)
        self.s.set_node_locked(self.nodes[2],True);before=self.snapshot()
        with self.assertRaises(ValueError):wf.field_slot_transfer_preview(self.s,self.slot(0),self.slot(2,3))
        with self.assertRaises(ValueError):self.confirm()
        self.assertEqual(self.snapshot(),before)

    def test_partial_repaste_preserves_unmentioned_connections_and_rewires_only_one_node(self):
        self.connect_all();self.apply(1,'A\tB\n2\t2');remote=[tuple(r) for r in self.s.conn.execute('SELECT * FROM splices WHERE node_id=?',(self.nodes[2],))]
        self.apply(1,'A\tB\n1\t3')
        self.assertIsNotNone(self.s.splice_for(self.nodes[1],self.cables[0],2))
        self.assertEqual([tuple(r) for r in self.s.conn.execute('SELECT * FROM splices WHERE node_id=?',(self.nodes[2],))],remote)
        self.assertEqual(self.s.core(*self.slot(1))['core_id'],'CORE-A')
        before=self.snapshot()
        with self.assertRaises(ValueError):self.apply(1,'A\tB\n1\t1\n1\t2')
        self.assertEqual(self.snapshot(),before)

    def test_rn_requires_internal_port_and_neutral_port_is_accepted(self):
        with self.s.action('RN으로 변경'):self.s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.nodes[3],))
        self.s.ensure_ports(self.nodes[3],{'mp':1,'sp':1,'p':8});self.connect_all()
        self.assertFalse(self.audit()['coherent'])
        self.s.connect(self.nodes[3],self.slot(2),('PORT:'+self.nodes[3],1),temporary=True)
        self.assertTrue(self.audit()['coherent']);self.confirm();self.assertTrue(self.audit()['complete'])


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showinfo',return_value=None), \
             patch.object(code['messagebox'],'askyesno',return_value=True), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *args:errors.append(str(args))
            try:
                s=app.store;a=s.add_node('끝 A',0,0);h=s.add_node('현장 함체',240,0);b=s.add_node('끝 B',480,0)
                left=s.add_cable(a,h,'L','6C','기설');right=s.add_cable(h,b,'R','6C','기설')
                s.update_core(left,1,('ID-A','GIS 이름','normal','','on'));s.connect(h,(left,1),(right,1))
                assert app.load_scenario('before');s=app.store
                assert wf.field_slot_mode(s) and not s.conn.execute('SELECT 1 FROM splices').fetchone()
                gis=app.scenario_path('gis').read_bytes()
                s.update_core(right,1,('ID-B','잘못 놓인 내역','normal','','on'))
                s.update_core(right,2,('ID-A','GIS 이름','normal','','unknown'))
                s.update_core(right,3,('ID-A','미연결 배치대기','normal','','off'))
                app.deiconify();app.update()
                node=code['NodeDialog'](app,s,h);node.field_survey_open();app.update()
                survey=next(w for w in node.winfo_children() if isinstance(w,wf.FieldSurveyDialog))
                survey.sheet.set_text('L\tR\n1\t1')
                original_table=wf.TableDialog
                def reviewed(*args,**kwargs):
                    dialog=original_table(*args,**kwargs)
                    if dialog.accept_button is not None:dialog.after(30,dialog.confirm)
                    return dialog
                with patch.object(wf,'TableDialog',side_effect=reviewed):
                    survey.overlay_button.invoke();app.update()
                    assert s.core(right,1)['core_id']=='ID-B'
                    assert any(r['local_status']=='NOT OK' for r in survey.rows)
                    editor=wf.FieldSlotEditorDialog(survey,s,node_id=h);app.update()
                    assert any(sid==(right,1) for sid in editor.positions.values())
                    editor.source_owner.set(editor.labels[right]);editor.source_index.set('2')
                    editor.target_owner.set(editor.labels[right]);editor.target_index.set('1');editor.move_button.invoke();app.update()
                    assert s.core(right,1)['core_id']=='ID-A' and s.core(right,2)['core_id']=='ID-B'
                    assert s.splice_for(h,left,1)['core2_index']==1
                    confirm=wf.FieldSlotConfirmDialog(editor,s,(left,1));confirm.detail.set('확정 회선 A');confirm.confirm_button.invoke();app.update()
                    assert s.core(right,3)['core_id']=='' and s.core(right,1)['detail']=='확정 회선 A'
                    assert wf.completion_report(s)['by_id']['ID-A']['complete']
                    assert wf.completion_report(s)['done']<wf.completion_report(s)['total']
                    assert app.work_progress_incomplete.cget('fg')=='#c62828'
                    editor.filter_owner.set('전체');editor.reload();assert editor.positions
                    editor.destroy();survey.destroy();node.destroy()
                    s.update_core(left,2,('ID-B','회선 B','normal','','unknown'))
                    s.connect(h,(left,2),(right,2))
                    wf.field_slot_confirm_commit(s,wf.field_slot_confirm_preview(s,(left,2),'ID-B','회선 B'))
                    app.refresh();assert wf.completion_report(s)['rate']==100.0
                    assert app.work_progress_incomplete.cget('fg')!='#c62828'
                    exported=Path(temp)/'field-v72.json';slots_before=s.all_core_rows()
                    with patch.object(code['filedialog'],'asksaveasfilename',return_value=str(exported)):app.export_json()
                    with patch.object(code['filedialog'],'askopenfilename',return_value=str(exported)):app.import_json()
                    assert app.store.all_core_rows()==slots_before
                    assert wf.field_slot_mode(app.store) and wf.completion_report(app.store)['rate']==100.0
                    app.save_current_drawing(silent=True);assert app.load_scenario('gis');assert app.scenario_path('gis').read_bytes()==gis
                    assert app.load_scenario('before');assert wf.completion_report(app.store)['rate']==100.0
                    assert app.load_scenario('after');assert app.scenario_kind()=='after'
                assert not errors,errors
            finally:app.on_close()
    print('PASS Windows V72 new GIS copy, Excel field topology, mismatch display, slot exchange, reviewed finalization, waiting cleanup, 100 percent and phase persistence')


def windows_recopy_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[];notices=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showinfo',side_effect=lambda *a,**k:notices.append(str(a))), \
             patch.object(code['messagebox'],'askyesno',return_value=True), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *args:errors.append(str(args))
            try:
                s=app.store;a=s.add_node('끝 A',0,0);h=s.add_node('조사 함체',240,0);b=s.add_node('끝 B',480,0)
                left=s.add_cable(a,h,'L','6C','기설');right=s.add_cable(h,b,'R','6C','기설')
                s.update_core(left,1,('GIS-ID','GIS 이름','normal','','on'));s.connect(h,(left,1),(right,1))
                existing_field(app);assert app.load_scenario('before');assert not wf.field_slot_mode(s)
                s.update_core(left,1,('FIELD-EDIT','새로 복사 직전 수정','normal','','off'))
                wf.FieldSurvey(s,h).save('L\tR\n1\t1')
                app.deiconify();app.update()
                node=code['open_detail_dialog'](app,s,'node',h);app.update()
                manager=code['ScenarioDialog'](app);app.update()
                controls=[c for w in manager.winfo_children() for c in w.winfo_children()]
                button=next(w for w in controls if isinstance(w,code['ttk'].Button) and w.cget('text')=='GIS → 현장반영 새로 복사')
                old=wf.plan_snapshot(s.conn);gis=app.scenario_path('gis').read_bytes()
                with patch.object(code['messagebox'],'askyesno',return_value=False):button.invoke();app.update()
                assert wf.plan_snapshot(s.conn)==old and not list(app.scenario_folder().glob('before_previous_*.sqlite3'))
                button.invoke();app.update()
                assert wf.field_slot_mode(s) and app.scenario_kind()=='before'
                assert not s.conn.execute('SELECT 1 FROM splices').fetchone() and not wf.field_records(s)
                assert s.core(left,1)['core_id']=='GIS-ID' and s.core(left,1)['signal']=='on'
                assert not node.winfo_exists()
                assert '현재 접속 연결 0건' in manager.info.get('1.0','end')
                assert any('현장반영 초기화 완료' in item and '접속 연결 0건' in item for item in notices)
                old_store=code['Store'](next(app.scenario_folder().glob('before_previous_*.sqlite3')))
                try:
                    assert old_store.core(left,1)['core_id']=='FIELD-EDIT'
                    assert old_store.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0]==1
                    assert wf.field_records(old_store)
                finally:old_store.close()
                reopened=code['open_detail_dialog'](app,s,'node',h);app.update()
                reopened.left_var.set(next(label for label,cid in reopened.by_label.items() if cid==left))
                reopened.right_var.set(next(label for label,cid in reopened.by_label.items() if cid==right))
                reopened.reload_all();app.update()
                assert reopened.left_tree.item('1','values')[5]==''
                assert reopened.right_tree.item('1','values')[5]==''
                s.connect(h,(left,1),(right,1));button.invoke();app.update()
                assert not s.conn.execute('SELECT 1 FROM splices').fetchone()
                assert not reopened.winfo_exists()
                assert app.load_scenario('gis');assert s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0]==1
                button.invoke();app.update()
                assert app.scenario_kind()=='before' and not s.conn.execute('SELECT 1 FROM splices').fetchone()
                assert len(list(app.scenario_folder().glob('before_previous_*.sqlite3')))==3
                assert app.scenario_path('gis').read_bytes()==gis
                manager.destroy();app.save_current_drawing(silent=True)
                assert app.load_scenario('gis');assert app.load_scenario('before')
                assert wf.field_slot_mode(s) and not s.conn.execute('SELECT 1 FROM splices').fetchone()
                assert not errors,errors
            finally:app.on_close()
    print('PASS Windows V73 actual recopy button from existing legacy field and GIS, cancellation, latest backup, zero links in both panes, stale window closure, repeated copy and persistence')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SlotFieldTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    windows_recopy_ui()
    print('PASS V72 slot identities, neutral temporary/unknown, field topology, required names/signals, finalization, cleanup, locks, history and GIS preservation')
