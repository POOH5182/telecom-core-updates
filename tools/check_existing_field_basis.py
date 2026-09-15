"""V88: saved splice baseline, optional survey and incremental re-evaluation."""
import os
import faulthandler
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_field_survey import code, wf
from check_field_slots import ScenarioHarness


def route(s):
    nodes=[s.add_node(name,i*240,0) for i,name in enumerate(('끝 A','함체 1','함체 2','끝 B'))]
    cables=[s.add_cable(nodes[i],nodes[i+1],name,'6C','기설') for i,name in enumerate(('A','B','C'))]
    for index in (1,2):
        s.update_core(cables[0],index,('ID-'+str(index),'기존 회선','normal','','unknown'))
        for i in (1,2):s.connect(nodes[i],(cables[i-1],index),(cables[i],index))
    return nodes,cables


class ExistingBasisTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.gis=self.home/'gis.sqlite3';g=code['Store'](self.gis)
        self.nodes,self.cables=route(g)
        self.reference=wf.field_capture_reference(g.conn)['snapshot'];g.close()
        self.original=self.gis.read_bytes();self.path=self.home/'before.sqlite3'
        wf.field_slot_copy(self.gis,self.path);self.s=code['Store'](self.path)
    def tearDown(self):self.s.close();self.temp.cleanup()
    def legacy(self):
        self.s.conn.execute("DELETE FROM meta WHERE key='field_identity_policy'")
        self.s.conn.commit();self.assertFalse(wf.field_slot_mode(self.s))
    def snapshot(self):return wf.plan_snapshot(self.s.conn),wf.state(self.s),self.s.history_rows()
    def progress(self,done=2):
        report=wf.completion_report(self.s)
        self.assertEqual((report['total'],report['done']),(2,done),report)
    def test_new_copy_uses_saved_splices_without_survey_and_is_read_only(self):
        self.assertEqual(wf.field_capture_reference(self.s.conn)['snapshot'],self.reference)
        self.assertFalse(wf.field_records(self.s));self.assertFalse(self.s.history_rows())
        before=self.snapshot();self.progress()
        self.assertFalse(self.s.before_drawing_check_rows())
        self.assertTrue(ScenarioHarness(self.s).field_ready_for_after())
        for node in self.nodes[1:3]:
            self.assertEqual(wf.field_summary(self.s,node),dict(done=2,pending=0,issues=0,total=2))
            rows=wf.FieldSurvey(self.s,node).report()
            self.assertTrue(all(r['completion_basis']=='기존 선번' and r['local_status']=='OK' for r in rows))
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.gis.read_bytes(),self.original)
    def test_legacy_saved_connections_need_no_survey_or_gis_evidence(self):
        self.legacy()
        self.s.conn.execute('DELETE FROM workflow_state WHERE key=?',(wf.FIELD_REFERENCE_KEY,));self.s.conn.commit()
        self.assertFalse(wf.field_reference(self.s));before=self.snapshot();self.progress()
        self.assertFalse(self.s.before_drawing_check_rows())
        self.assertTrue(ScenarioHarness(self.s).field_ready_for_after())
        self.assertEqual(wf.field_local_summary(self.s,self.nodes[1]),dict(ok=2,not_ok=0,total=2))
        self.assertEqual(self.snapshot(),before)
    def test_saved_manual_disconnection_is_never_reseeded_on_check_or_reopen(self):
        for legacy in (False,True):
            with self.subTest(legacy=legacy):
                if legacy:self.legacy()
                self.s.disconnect(self.nodes[2],self.cables[1],1)
                before=self.snapshot();self.progress(1)
                self.assertTrue(self.s.before_drawing_check_rows())
                self.s.check_auto_splice_on_open(self.nodes[2])
                self.assertEqual(self.snapshot(),before)
                self.s.close();self.s=code['Store'](self.path);self.progress(1)
                self.assertIsNone(self.s.splice_for(self.nodes[2],self.cables[1],1))
    def test_partial_survey_rechecks_only_observed_node_and_preserves_other_pairs(self):
        nid=self.nodes[1];left,mid,right=self.cables
        baseline=wf.plan_snapshot(self.s.conn);self.progress()
        wf.FieldSurvey(self.s,nid).save('A\tB\n1\t2')
        self.assertEqual(wf.plan_snapshot(self.s.conn),baseline);self.progress(0)
        self.assertTrue(self.s.before_drawing_check_rows())
        saved=self.snapshot()
        wf.field_overlay_commit(self.s,wf.field_overlay_preview(self.s,nid,'A\tB\n1\t2'))
        self.assertEqual(self.s.splice_for(nid,left,1)['core2_index'],2)
        self.assertIsNone(self.s.splice_for(nid,left,2));self.progress(0)
        for index in (1,2):self.assertIsNotNone(self.s.splice_for(self.nodes[2],mid,index))
        self.assertEqual(self.s.core(mid,2)['core_id'],'ID-2')
        self.s.undo();self.assertEqual(self.snapshot()[:2],saved[:2]);self.progress(0)
        self.s.undo();self.progress()
        wf.field_overlay_commit(self.s,wf.field_overlay_preview(self.s,nid,'A\tB\n2\t2'))
        self.progress();self.assertFalse(self.s.before_drawing_check_rows())
        self.assertEqual(wf.plan_snapshot(self.s.conn),baseline)
        self.assertEqual(set(wf.field_records(self.s)),{nid})
        rows=wf.FieldSurvey(self.s,nid).report()
        self.assertEqual({r['completion_basis'] for r in rows},{'기존 선번','현장 조사'})
        self.s.close();self.s=code['Store'](self.path);self.progress()
        self.assertEqual(self.gis.read_bytes(),self.original)
    def test_legacy_new_evidence_and_explicit_hold_recompute_completion(self):
        self.legacy();self.progress();nid=self.nodes[1]
        wf.FieldSurvey(self.s,nid).save('A\tB\n1\t2');self.progress(0)
        self.s.undo();self.progress()
        row=wf.FieldSurvey(self.s,nid).report()[0]
        wf.field_local_mark(self.s,nid,{row['key']},'NOT OK',self.s.data_revision(),self.s._view_generation,'직접 확인')
        self.progress(1);self.assertTrue(wf.field_check_rows(self.s))
        self.s.undo();self.progress()
    def test_locked_initial_copy_keeps_original_splices_and_protections(self):
        self.s.set_node_locked(self.nodes[1],True);source=self.home/'locked.sqlite3';target=self.home/'copy.sqlite3'
        self.s.backup_to(source);original=source.read_bytes();wf.field_slot_copy(source,target)
        other=code['Store'](target)
        try:
            self.assertEqual(other.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0],4)
            self.assertTrue(wf.node_locked(other,self.nodes[1]))
            with self.assertRaises(ValueError):other.disconnect(self.nodes[1],self.cables[0],1)
            self.assertEqual(wf.completion_report(other)['done'],2)
            self.assertEqual(source.read_bytes(),original)
        finally:other.close()
    def test_existing_id_signal_and_rn_faults_still_need_work(self):
        with self.s.action('신호 불일치'):
            self.s.conn.execute("UPDATE cores SET signal='on' WHERE cable_id=? AND core_index=1",(self.cables[0],))
            self.s.conn.execute("UPDATE cores SET signal='off' WHERE cable_id=? AND core_index=1",(self.cables[1],))
        self.progress(1);self.assertTrue(self.s.before_drawing_check_rows());self.s.undo()
        with self.s.action('끝단 RN'):
            self.s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.nodes[-1],))
        self.progress(0);self.assertTrue(self.s.before_drawing_check_rows())
        self.s.undo();self.progress()


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(75, exit=True)
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(str(a))), \
             patch.object(code['messagebox'],'showinfo'), \
             patch.object(code['messagebox'],'askyesno',return_value=True), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *a:errors.append(str(a))
            try:
                print('UI V88: initial copy',flush=True)
                nodes,cables=route(app.store);assert app.load_scenario('before');s=app.store
                app.deiconify();app.update()
                assert not wf.field_records(s) and wf.completion_report(s)['rate']==100
                assert '기존 저장 선번' in app.work_progress_note.cget('text')
                print('UI V88: after-stage gate',flush=True)
                assert app.field_ready_for_after();assert app.load_scenario('after')
                assert app.load_scenario('before');assert wf.completion_report(s)['done']==2
                original=wf.plan_snapshot(s.conn);gis=app.scenario_path('gis').read_bytes()
                print('UI V88: open survey',flush=True)
                node=code['open_detail_dialog'](app,s,'node',nodes[1]);node.field_survey_open();app.update()
                dialog=next(w for w in node.winfo_children() if isinstance(w,wf.FieldSurveyDialog))
                dialog.sheet.set_text('A\tB\n1\t2')
                buttons=[w for frame in dialog.winfo_children() for w in frame.winfo_children() if isinstance(w,code['ttk'].Button)]
                print('UI V88: compare-only save',flush=True)
                next(w for w in buttons if w.cget('text')=='비교만 저장').invoke();app.update()
                assert wf.plan_snapshot(s.conn)==original and wf.completion_report(s)['done']==0
                assert app.work_progress_incomplete.cget('fg')=='#c62828'
                real=wf.TableDialog
                def reviewed(*args,**kwargs):
                    result=real(*args,**kwargs)
                    if result.accept_button is not None:result.after(30,result.confirm)
                    return result
                print('UI V88: survey apply',flush=True)
                with patch.object(wf,'TableDialog',side_effect=reviewed):dialog.overlay_button.invoke();app.update()
                assert s.splice_for(nodes[1],cables[0],1)['core2_index']==2
                assert all(s.splice_for(nodes[2],cables[1],i) for i in (1,2))
                assert wf.completion_report(s)['done']==0
                print('UI V88: undo and recheck',flush=True)
                dialog.destroy();node.destroy();s.undo();s.undo();app.refresh();app.update()
                assert wf.completion_report(s)['done']==2 and app.field_ready_for_after()
                assert app.work_progress_incomplete.cget('fg')!='#c62828'
                print('UI V88: reload',flush=True)
                app.save_current_drawing(silent=True);assert app.load_scenario('gis');assert app.load_scenario('before')
                assert wf.plan_snapshot(s.conn)==original and not wf.field_records(s)
                assert app.scenario_path('gis').read_bytes()==gis
                assert not errors,errors
            finally:
                print('UI V88: cleanup',flush=True)
                app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows V88 no-survey GIS copy, dashboard, actual after-stage gate, later survey save/apply, undo and reload')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ExistingBasisTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
    print('PASS V88 saved connection baseline, optional field survey, partial recheck, current edits and protected GIS preservation')
