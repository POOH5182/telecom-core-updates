"""Field identity materialization, deleted sections, immutable baselines and UI."""
import copy
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import code,wf
from check_field_slots import ScenarioHarness


def route(s):
    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')")
    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('field_identity_policy',?)",(wf.FIELD_SLOT_POLICY,));s.conn.commit()
    nodes=[s.add_node('함체 '+str(i),150+i*200,350) for i in range(5)]
    cables=[s.add_cable(nodes[i],nodes[i+1],'C'+str(i),'12C','기설') for i in range(4)]
    slots=[(c,i*2+1) for i,c in enumerate(cables)]
    for i,slot in enumerate(slots):s.update_core(*slot,('CORE' if i==0 else '임시-'+str(80+i),'통일한 코어내역' if i==0 else '임시접속코어','normal','', 'on' if i==0 else 'unknown'))
    for i in range(1,4):s.connect(nodes[i],slots[i-1],slots[i])
    return nodes,cables,slots


class App:
    def __init__(self,s,home):self.store=s;self.home=Path(home)
    def scenario_kind(self):return wf.completion_kind(self.store)
    def scenario_path(self,kind):return self.home/(kind+'.sqlite3')


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name);self.s=code['Store'](self.home/'working.sqlite3')
        self.nodes,self.cables,self.slots=route(self.s);self.before=self.home/'before.sqlite3';self.after=self.home/'after.sqlite3'
        self.s.backup_to(self.before);self.original=self.before.read_bytes()
    def tearDown(self):self.s.close();self.temp.cleanup()
    def old_after(self):
        self.s.close();shutil.copy2(self.before,self.after);self.s=code['Store'](self.after)
        self.s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','after')");self.s.conn.commit()
        return wf.AfterIdentitySync(App(self.s,self.home))
    def delete(self,cable):
        with self.s.action('후도면 케이블 삭제'):
            self.s.conn.execute('DELETE FROM splices WHERE cable1_id=? OR cable2_id=?',(cable,cable))
            self.s.conn.execute('DELETE FROM cables WHERE id=?',(cable,))
    def assert_identity(self,s,slots):
        for slot in slots:self.assertEqual(tuple(s.core(*slot)[k] for k in ('core_id','detail')),('CORE','통일한 코어내역'))

    def test_fresh_copy_materializes_all_numbers_preserves_original_and_after_delete(self):
        source=wf.plan_snapshot(self.s.conn);report=wf.after_identity_copy(code['Store'],self.before,self.after)
        self.assertEqual((report['routes'],report['changed']),(1,3));self.assertFalse(report['skipped'])
        self.assertEqual(self.before.read_bytes(),self.original);self.assertEqual(wf.plan_snapshot(self.s.conn),source)
        self.s.close();self.s=code['Store'](self.after);self.assert_identity(self.s,self.slots)
        after=wf.plan_snapshot(self.s.conn)
        for table in ('nodes','cables','ports','splices','core_annotations','survey_rows'):self.assertEqual(after[table],source[table])
        for old,new in zip(source['cores'],after['cores']):
            for key in ('cable_id','core_index','status1','status2','signal'):self.assertEqual(old[key],new[key])
        self.assertTrue(wf.completion_report(self.s)['by_id']['CORE']['complete'])
        self.delete(self.cables[1]);self.assert_identity(self.s,[s for s in self.slots if s[0]!=self.cables[1]])
        service=wf.AfterRoutePlanner(App(self.s,self.home));ctx=service.context()
        key=next(k for k,v in ctx['entries'].items() if v['core_id']=='CORE')
        self.assertEqual(len(service.problem(key,ctx)['components']),2)

    def test_real_stage_transition_materializes_only_after_snapshot(self):
        app=ScenarioHarness(self.s);original=wf.plan_snapshot(self.s.conn)
        with patch.object(code['messagebox'],'askyesno',return_value=True),patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'askyesnocancel',return_value=True):
            self.assertTrue(app.load_scenario('after'))
        self.assert_identity(self.s,self.slots);baseline=code['Store'](app.scenario_path('before'))
        try:self.assertEqual(wf.plan_snapshot(baseline.conn),original)
        finally:baseline.close()

    def test_existing_after_repairs_survivors_even_after_real_identity_cable_deleted_with_undo(self):
        service=self.old_after();self.delete(self.cables[0]);before=wf.plan_snapshot(self.s.conn);history=self.s.history_rows()
        p=service.preview();self.assertEqual(len(p['changes']),3)
        self.assertEqual((wf.plan_snapshot(self.s.conn),self.s.history_rows()),(before,history))
        backup=service.apply(p);self.assertTrue(backup.exists());self.assert_identity(self.s,self.slots[1:])
        self.assertIsNone(self.s.cable(self.cables[0]));after=wf.plan_snapshot(self.s.conn)
        self.assertEqual(after['splices'],before['splices']);self.assertEqual(after['core_annotations'],before['core_annotations'])
        self.s.undo();self.assertEqual(wf.plan_snapshot(self.s.conn),before);self.s.redo();self.assertEqual(wf.plan_snapshot(self.s.conn),after)
        self.s.close();self.s=code['Store'](self.after);self.assert_identity(self.s,self.slots[1:]);self.assertEqual(self.before.read_bytes(),self.original)

    def test_manual_reassignment_rewire_and_empty_unconnected_slots_are_preserved(self):
        service=self.old_after()
        with self.s.action('후도면 재배정'):wf.field_slot_write(self.s,self.slots[0],['OTHER','새 내역','normal','','on'])
        before=wf.plan_snapshot(self.s.conn);p=service.preview();self.assertFalse(p['changes']);self.assertTrue(p['skipped']);self.assertEqual(wf.plan_snapshot(self.s.conn),before)
        self.s.undo();self.delete(self.cables[0]);self.s.disconnect(self.nodes[2],*self.slots[1])
        with self.s.action('빈 예비번호로 정리'):wf.field_slot_write(self.s,self.slots[1],['','','','',''])
        p=service.preview();self.assertNotIn(list(self.slots[1]),[r['slot'] for r in p['changes']]);service.apply(p)
        self.assertEqual(self.s.core(*self.slots[1])['core_id'],'')

    def test_ambiguous_names_and_unfinished_or_temporary_only_paths_are_not_guessed(self):
        self.s.update_core(*self.slots[3],('CORE','다른 이름','normal','','unknown'));self.s.backup_to(self.before)
        r=wf.after_identity_copy(code['Store'],self.before,self.after);self.assertEqual(r['changed'],0);self.assertIn('여러 개',r['skipped'][0][1])
        self.s.undo();self.s.disconnect(self.nodes[2],*self.slots[1]);self.s.backup_to(self.before)
        r=wf.after_identity_copy(code['Store'],self.before,self.after);self.assertEqual(r['changed'],0)
        self.s.undo();self.s.update_core(*self.slots[0],('임시-90','임시접속코어','normal','','unknown'));self.s.backup_to(self.before)
        r=wf.after_identity_copy(code['Store'],self.before,self.after);self.assertEqual(r['routes'],0)

    def test_locked_initial_copy_preserves_locks_existing_sync_obeys_locks_and_stale_guard(self):
        self.s.set_node_locked(self.nodes[2],True);self.s.backup_to(self.before);original=self.before.read_bytes()
        wf.after_identity_copy(code['Store'],self.before,self.after);target=code['Store'](self.after)
        try:
            self.assert_identity(target,self.slots);self.assertTrue(wf.node_locked(target,self.nodes[2]))
            with self.assertRaises(ValueError):target.update_core(*self.slots[1],('NO','禁止','','',''))
        finally:target.close()
        self.assertEqual(self.before.read_bytes(),original)
        service=self.old_after();self.assertFalse(service.preview()['changes'])
        self.s.set_node_locked(self.nodes[2],False);p=service.preview();self.assertTrue(p['changes'])
        self.s.set_node_locked(self.nodes[2],True)
        with self.assertRaisesRegex(ValueError,'변경'):service.apply(p)

    def test_rn_internal_port_and_explicit_confirmation_are_materialized(self):
        with self.s.action('RN 말단'):self.s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.nodes[-1],))
        self.s.ensure_ports(self.nodes[-1],{'mp':1,'sp':1,'p':1});port=('PORT:'+self.nodes[-1],1)
        self.s.connect(self.nodes[-1],self.slots[-1],port);self.s.backup_to(self.before)
        wf.after_identity_copy(code['Store'],self.before,self.after);other=code['Store'](self.after)
        try:self.assert_identity(other,self.slots+[port]);self.assertTrue(wf.completion_report(other)['by_id']['CORE']['complete'])
        finally:other.close()
        wf.field_slot_confirm(self.s,self.slots[0],'CORE','통일한 코어내역',False);self.s.backup_to(self.before)
        self.assertEqual(wf.after_identity_copy(code['Store'],self.before,self.after)['changed'],0)

    def test_atomic_failure_tampering_and_reference_changes_do_not_partially_apply(self):
        service=self.old_after();p=service.preview();before=wf.plan_snapshot(self.s.conn);history=self.s.history_rows();write=wf.field_slot_write;count=0
        def fail(*args):
            nonlocal count
            write(*args);count+=1
            if count==2:raise ValueError('injected')
        with patch.object(wf,'field_slot_write',side_effect=fail):
            with self.assertRaisesRegex(ValueError,'injected'):service.apply(p)
        self.assertEqual((wf.plan_snapshot(self.s.conn),self.s.history_rows()),(before,history))
        p=service.preview();bad=copy.deepcopy(p);bad['changes'][0]['new'][0]='WRONG'
        with self.assertRaisesRegex(ValueError,'변경'):service.apply(bad)
        source=code['Store'](self.before)
        try:source.update_core(*self.slots[0],('CORE','변경 내역','normal','','on'))
        finally:source.close()
        with self.assertRaisesRegex(ValueError,'변경'):service.apply(p)
        target_bytes=self.after.read_bytes()
        with patch.object(Path,'replace',side_effect=OSError('failed replace')):
            with self.assertRaises(OSError):wf.after_identity_copy(code['Store'],self.before,self.after)
        self.assertEqual(self.after.read_bytes(),target_bytes);self.assertFalse(list(self.home.glob('*.new')))


def windows_ui():
    if sys.platform!='win32':return
    import faulthandler
    faulthandler.dump_traceback_later(75,exit=True)
    with tempfile.TemporaryDirectory() as temp:
        os.environ['TELECOM_APP_HOME']=temp;errors=[]
        with patch.object(code['messagebox'],'showerror',side_effect=lambda *a,**k:errors.append(a)), \
             patch.object(code['messagebox'],'showwarning',side_effect=lambda *a,**k:errors.append(a)), \
             patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'askyesno',return_value=True), \
             patch.object(code['messagebox'],'askyesnocancel',return_value=True):
            app=code['App']();app.report_callback_exception=lambda *a:errors.append(a)
            try:
                nodes,cables,slots=route(app.store);app.refresh();app.update()
                assert app.load_scenario('after');app.update();s=app.store
                assert all(s.core(*p)['core_id']=='CORE' and s.core(*p)['detail']=='통일한 코어내역' for p in slots)
                assert wf.completion_report(s)['by_id']['CORE']['complete']
                # Reopen a pre-V93 after drawing, then delete the only real-ID cable.
                app.replace_current_from(app.scenario_path('before'));app.set_scenario_kind('after')
                with s.action('후도면 원래 ID 케이블 삭제'):
                    s.conn.execute('DELETE FROM splices WHERE cable1_id=? OR cable2_id=?',(cables[0],cables[0]));s.conn.execute('DELETE FROM cables WHERE id=?',(cables[0],))
                app.refresh();app.update();original=wf.plan_snapshot(s.conn);real=wf.TableDialog
                def review(accept):
                    def show(*args,**kwargs):
                        d=real(*args,**kwargs);d.after(50,d.confirm if accept else d.destroy);return d
                    return show
                with patch.object(wf,'TableDialog',side_effect=review(False)):app.after_identity_button.invoke();app.update()
                assert wf.plan_snapshot(s.conn)==original
                with patch.object(wf,'TableDialog',side_effect=review(True)):app.after_identity_button.invoke();app.update()
                assert all(s.core(*p)['core_id']=='CORE' for p in slots[1:]);assert s.cable(cables[0]) is None
                app.undo();app.update();assert wf.plan_snapshot(s.conn)==original
                # Scenario manager's explicit regeneration uses the same materialization.
                assert app.load_scenario('before');manager=code['ScenarioDialog'](app)
                manager.copy_after();app.update();assert app.load_scenario('after');app.update()
                assert all(s.core(*p)['core_id']=='CORE' for p in slots);manager.destroy()
                assert not errors,errors
            finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows initial after creation, existing drawing repair button, preview cancel/apply, deletion, undo and manager regeneration')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(IdentityTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
