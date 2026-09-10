"""V76 local GIS selection, safe legacy separation, view controls and locks."""
import json
import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from check_field_slots import SlotFieldTests,code,wf


class FieldGISTests(unittest.TestCase):
    setUp=SlotFieldTests.setUp
    tearDown=SlotFieldTests.tearDown
    slot=SlotFieldTests.slot
    set=SlotFieldTests.set
    apply=SlotFieldTests.apply
    audit=SlotFieldTests.audit
    snapshot=SlotFieldTests.snapshot
    splices=SlotFieldTests.splices

    def select(self,node,enabled=True):
        return wf.field_gis_commit(self.s,wf.field_gis_preview(self.s,self.nodes[node],enabled))

    def legacy(self):
        self.s.close();self.s=code['Store'](self.gis)
        self.s.conn.execute("UPDATE meta SET value='before' WHERE key='active_scenario'");self.s.conn.commit()
        self.reference=wf.field_capture_reference(self.s.conn)

    def test_gis_selection_is_local_preserves_values_and_ok_is_not_complete(self):
        before=self.snapshot();preview=wf.field_gis_preview(self.s,self.nodes[1],True)
        self.assertEqual(self.snapshot(),before)
        self.assertFalse(wf.field_gis_selected(self.s,self.nodes[1]))
        result=wf.field_gis_commit(self.s,preview)
        self.assertTrue(result['backup'].exists());self.assertTrue(wf.field_gis_selected(self.s,self.nodes[1]))
        self.assertFalse(wf.field_gis_selected(self.s,self.nodes[2]))
        self.assertEqual({r[0] for r in self.splices()},{self.nodes[1]})
        self.assertEqual(self.s.trace_core_paths('CORE-A',slot=self.slot(0))['highlight'],set(self.cables[:2]))
        self.assertTrue(all(r['local_status']=='OK' for r in wf.FieldSurvey(self.s,self.nodes[1]).report()))
        self.assertEqual(wf.completion_report(self.s)['done'],0)
        self.assertEqual(wf.plan_snapshot(self.s.conn)['cores'],before[0]['cores'])
        self.select(2);self.assertEqual(wf.completion_report(self.s)['rate'],100)
        self.assertEqual(self.gis.read_bytes(),self.gis_bytes)

    def test_uncheck_restores_previous_local_field_and_preserves_other_node_undo_redo(self):
        self.apply(1,'A\tB\n1\t2');before=self.snapshot();self.select(1)
        self.assertTrue(wf.field_gis_selected(self.s,self.nodes[1]));self.select(2)
        self.select(1,False)
        self.assertEqual(wf.field_local_pairs(self.s,self.nodes[1]),{wf.field_pair((self.slot(0),self.slot(1,2)))})
        self.assertTrue(wf.field_local_pairs(self.s,self.nodes[2]))
        self.assertEqual(wf.field_records(self.s)[self.nodes[1]],before[1]['field_surveys'][self.nodes[1]])
        self.s.undo();self.assertTrue(wf.field_gis_selected(self.s,self.nodes[1]))
        self.s.redo();self.assertFalse(wf.field_gis_selected(self.s,self.nodes[1]))

    def test_empty_uncheck_reopen_and_read_only_preview(self):
        before=self.snapshot();self.select(1);self.s.close();self.s=code['Store'](self.path)
        self.assertTrue(wf.field_gis_selected(self.s,self.nodes[1]))
        self.select(1,False);self.assertEqual(self.splices(),[])
        self.assertEqual(self.snapshot()[0],before[0])
        self.assertEqual(wf.field_records(self.s),{})
        self.assertEqual(wf.field_reference(self.s),before[2])

    def test_later_manual_input_invalidates_gis_check_and_stale_actions_refuse(self):
        self.select(1);preview=wf.field_gis_preview(self.s,self.nodes[1],False)
        self.apply(1,'A\tB\n1\t2');before=self.snapshot()
        self.assertFalse(wf.field_gis_selected(self.s,self.nodes[1]))
        with self.assertRaises(ValueError):wf.field_gis_commit(self.s,preview)
        with self.assertRaises(ValueError):self.select(1,False)
        self.assertEqual(self.snapshot(),before)

    def test_gis_never_rewrites_current_ids_or_signals_and_mismatch_is_not_ok(self):
        self.set(1,1,'OTHER','現場','off');before=self.snapshot()[0]['cores'];self.select(1)
        self.assertEqual(wf.plan_snapshot(self.s.conn)['cores'],before)
        self.assertTrue(all(r['local_status']=='NOT OK' for r in wf.FieldSurvey(self.s,self.nodes[1]).report()))
        self.assertEqual(wf.completion_report(self.s)['done'],0)

    def test_lock_and_missing_gis_refuse_without_changes(self):
        self.s.set_node_locked(self.nodes[1],True);before=self.snapshot()
        with self.assertRaises(ValueError):self.select(1)
        self.assertEqual(self.snapshot(),before)
        self.s.set_node_locked(self.nodes[1],False)
        self.s.conn.execute('DELETE FROM workflow_state WHERE key=?',(wf.FIELD_REFERENCE_KEY,));self.s.conn.commit()
        with self.assertRaises(ValueError):self.select(1)

    def test_legacy_separation_preserves_observed_node_and_can_be_undone(self):
        self.legacy();wf.FieldSurvey(self.s,self.nodes[1]).save('A\tB\n1\t1')
        before=self.snapshot();preview=wf.field_connection_separation_preview(self.s,self.reference)
        self.assertEqual(self.snapshot(),before)
        self.assertEqual({nid for nid,pair in preview['removed']},{self.nodes[2]})
        result=wf.field_connection_separation_commit(self.s,preview)
        self.assertTrue(result['backup'].exists());self.assertTrue(wf.field_slot_mode(self.s))
        self.assertEqual({r[0] for r in self.splices()},{self.nodes[1]})
        self.assertEqual(wf.plan_snapshot(self.s.conn)['cores'],before[0]['cores'])
        self.assertIsNotNone(wf.field_slot_json_pack(self.s))
        self.s.undo();self.assertFalse(wf.field_slot_mode(self.s));self.assertEqual(self.snapshot(),before)
        self.s.redo();self.assertTrue(wf.field_slot_mode(self.s));self.select(2)
        self.assertEqual(wf.completion_report(self.s)['done'],1)

    def test_legacy_manual_keep_unknown_reference_stale_and_locked_are_guarded(self):
        self.legacy();preview=wf.field_connection_separation_preview(self.s,self.reference,[self.nodes[2]])
        self.assertEqual({nid for nid,pair in preview['removed']},{self.nodes[1]})
        self.s.set_node_locked(self.nodes[1],True);before=self.snapshot()
        with self.assertRaises(ValueError):wf.field_connection_separation_commit(self.s,preview)
        preview=wf.field_connection_separation_preview(self.s,self.reference)
        with self.assertRaises(ValueError):wf.field_connection_separation_commit(self.s,preview)
        self.assertEqual(self.snapshot(),before)
        with self.assertRaises(ValueError):wf.field_connection_separation_preview(self.s,dict(self.reference,source='조사 시작 도면 (GIS 기준본 없음)'))

    def test_all_locks_preserve_data_are_atomic_and_survive_reopen(self):
        self.select(1);before=self.snapshot();count=self.s.set_all_enclosures_locked(True)
        self.assertEqual(count,4);self.assertTrue(self.s.all_enclosures_locked())
        self.assertTrue(all(wf.cable_locked(self.s,c) for c in self.cables))
        with self.assertRaises(ValueError):self.s.disconnect(self.nodes[1],*self.slot(0))
        self.assertEqual(self.s.core(*self.slot(0))['core_id'],'CORE-A')
        self.s.close();self.s=code['Store'](self.path);self.assertTrue(self.s.all_enclosures_locked())
        self.s.undo();self.assertFalse(self.s.all_enclosures_locked());self.assertEqual(self.snapshot(),before)
        self.s.redo();self.assertTrue(self.s.all_enclosures_locked())
        self.assertEqual(self.s.set_all_enclosures_locked(False),4)
        self.assertFalse(self.s.all_enclosures_locked())
        for table in ('cores','ports','splices','cables'):self.assertEqual(self.snapshot()[0][table],before[0][table])
        self.s.set_node_locked(self.nodes[1],True);self.assertFalse(self.s.all_enclosures_locked())
        self.assertEqual(self.s.set_all_enclosures_locked(True),3)

    def test_display_legacy_defaults_persistence_and_independent_node_badges(self):
        path=self.home/'display.json';path.write_text('{"badges":true}',encoding='utf-8')
        options=code['read_display_options'](path)
        for key in ('hamche_assignment','cable_unassigned','cable_incomplete','cable_temporary'):self.assertTrue(options[key]);options[key]=False
        code['save_display_options'](path,options);self.assertEqual(code['read_display_options'](path),options)
        warning={'count':3,'waiting_count':1,'rn_in':True,'field_local':{'total':2,'ok':1,'not_ok':1}}
        labels=[r[0] for r in code['node_badge_rows'](code['visible_node_warning'](warning,options))]
        self.assertFalse(any('배정필요' in s for s in labels));self.assertIn('OK 1',labels);self.assertIn('연결대기 1개',labels)


def windows_ui():
    if sys.platform!='win32':return
    case=FieldGISTests();case.setUp()
    try:
        (case.home/'ui').mkdir()
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error:
            app=code['App']();app.store.close();app.store=case.s;errors=[]
            app.report_callback_exception=lambda *args:errors.append(str(args[1]))
            try:
                app.refresh();app.update()
                assert str(app.all_lock_button.cget('text'))=='🔓'
                node=code['NodeDialog'](app,case.s,case.nodes[1]);app.update()
                node.gis_control.check.invoke();app.update()
                assert wf.field_gis_selected(case.s,case.nodes[1])
                assert wf.completion_report(case.s)['done']==0
                node.left_var.set(next(k for k,v in node.by_label.items() if v==case.cables[0]));node.reload_all()
                node.left_tree.selection_set('1');node.show_core_paths();app.update()
                assert app.highlight_cables==set(case.cables[:2])
                app.all_lock_button.invoke();app.update();assert str(app.all_lock_button.cget('text'))=='🔒'
                assert str(node.gis_control.check.cget('state'))=='disabled'
                node.lift();node.name_entry.focus_force();app.update()
                node.name_entry.event_generate('<Control-a>');node.name_entry.event_generate('<Control-c>');app.update()
                assert app.clipboard_get()=='함체 1'
                app.all_lock_button.invoke();app.update();assert str(app.all_lock_button.cget('text'))=='🔓'
                assert str(node.gis_control.check.cget('state'))=='normal'
                node.destroy()
                settings=code['DisplaySettingsDialog'](app);app.update()
                for k in ('hamche_assignment','cable_unassigned','cable_incomplete','cable_temporary'):settings.values[k].set(False)
                settings.apply();app.update()
                nodes={r['id']:r for r in case.s.nodes()};warnings=case.s.cable_core_warning_summary()
                # Synthetic warning counts isolate visibility from completion rules.
                warnings={cid:dict(unassigned=2,incomplete_badge=3,temporary=1,marked_error=1) for cid in case.cables}
                layout=app.cable_label_layout(nodes,case.s.cables(),warnings)
                texts=[p['text'] for item in layout for p in item['parts']]
                assert not any(any(k in t for k in ('미배정코어','미완료코어','임시코어')) for t in texts)
                assert any('오류코어' in t for t in texts)
                survey=wf.FieldSurveyDialog(app,case.s,case.nodes[2]);app.update();survey.gis_control.check.invoke();app.update()
                assert wf.field_gis_selected(case.s,case.nodes[2]);assert wf.completion_report(case.s)['rate']==100
                survey.destroy();assert not errors,errors;assert not error.called,error.call_args
            finally:app.on_close()
        print('PASS Windows GIS checkbox partial trace, auto OK vs completion, lock icon/copy, grouped visibility and survey checkbox')
    finally:case.tearDown()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FieldGISTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
