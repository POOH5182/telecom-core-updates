"""Unique physical after joins, preserved ON/unknown signals and atomic undo."""
import os
import faulthandler
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_after_plan import LocalApp,code,wf,update


class AutoConnectTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store
        s=self.s
        self.a=s.add_node('말단1',0,0);self.h=s.add_node('함체',200,0);self.b=s.add_node('말단2',400,0)
        self.l=s.add_cable(self.a,self.h,'LEFT','12C','기설');self.r=s.add_cable(self.h,self.b,'RIGHT','12C','기설')
    def tearDown(self):self.s.close();self.temp.cleanup()
    def fill(self):
        update(self.s,self.l,1,dict(core_id='CORE',detail='같은 내역',signal='on'))
        update(self.s,self.r,7,dict(core_id='CORE',detail='같은 내역',signal='unknown'))
    def connected(self):return bool(self.s.splice_for(self.h,self.l,1))
    def complete(self):return wf.completion_report(self.s)['by_id']['CORE']['complete']

    def test_edit_automatically_connects_different_numbers_in_one_undo(self):
        wf.after_auto_activate(self.s)
        update(self.s,self.l,1,dict(core_id='CORE',detail='같은 내역',signal='on'))
        old=wf.plan_snapshot(self.s.conn);history=len(self.s.history_rows())
        update(self.s,self.r,7,dict(core_id='CORE',detail='같은 내역',signal='unknown'))
        self.assertTrue(self.connected());self.assertTrue(self.complete())
        self.assertFalse(self.s.waiting_connection_groups(self.h));self.assertFalse(self.s.incomplete_core_groups())
        self.assertEqual(self.s.core(self.l,1)['signal'],'on');self.assertEqual(self.s.core(self.r,7)['signal'],'unknown')
        self.assertEqual(len(self.s.history_rows()),history+1)
        self.s.undo();self.assertEqual(wf.plan_snapshot(self.s.conn),old)
        self.s.redo();self.assertTrue(self.complete())

    def test_existing_wait_migrates_once_with_backup_and_undo_survives_reopen(self):
        self.fill();old=wf.plan_snapshot(self.s.conn)
        self.assertEqual(wf.after_auto_activate(self.s),1);self.assertTrue(self.complete())
        self.assertTrue(list((self.s.path.parent/'backup').glob('before_same_id_*.sqlite3')))
        self.s.undo();self.assertEqual(wf.plan_snapshot(self.s.conn),old)
        path=self.s.path;self.s.close();self.s=code['Store'](path)
        self.assertEqual(wf.after_auto_activate(self.s),0);self.assertFalse(self.connected())
        self.s.redo();self.assertTrue(self.complete())

    def test_on_unknown_connected_route_is_complete_and_values_never_change(self):
        self.fill();self.s.connect(self.h,(self.l,1),(self.r,7))
        for signal in ('unknown','','확인필요'):
            with self.s.action('신호 보존'):
                self.s.conn.execute('UPDATE cores SET signal=? WHERE cable_id=? AND core_index=7',(signal,self.r))
            old=wf.plan_snapshot(self.s.conn)
            self.assertTrue(self.complete());self.assertFalse(self.s.incomplete_core_groups())
            for cid,index in ((self.l,1),(self.r,7)):
                self.assertEqual(wf.core_completion_brief(self.s,(cid,index)),('연결완료',''))
                self.assertEqual(self.s.cable_core_warning_summary()[cid]['incomplete_total'],0)
            self.assertEqual(wf.plan_snapshot(self.s.conn),old)
        # A real missing splice remains incomplete even with matching names.
        self.s.disconnect(self.h,self.l,1);self.assertFalse(self.complete())

    def test_names_do_not_block_matching_ids_and_disconnect_stays_explicit(self):
        self.fill();update(self.s,self.r,7,dict(detail='별도 표시명'))
        wf.after_auto_activate(self.s);self.assertTrue(self.connected())
        self.assertEqual(self.s.core(self.r,7)['detail'],'별도 표시명')
        self.s.disconnect(self.h,self.l,1);update(self.s,self.r,7,dict(detail='수정명'))
        self.assertFalse(self.connected())

    def test_ambiguous_and_retired_and_locked_do_not_join(self):
        self.fill();update(self.s,self.r,8,dict(core_id='CORE'))
        self.assertFalse(wf.after_auto_pairs(self.s))
        self.s.delete_core_assignment(self.r,8)
        self.s.set_node_status(self.h,'철거');self.assertFalse(wf.after_auto_pairs(self.s));self.s.undo()
        self.s.set_node_locked(self.h,True);wf.after_auto_activate(self.s);self.assertFalse(self.connected())
        self.s.set_node_locked(self.h,False);self.assertTrue(self.connected())

    def test_same_id_elsewhere_off_conflict_and_field_never_join(self):
        self.fill();update(self.s,self.r,7,dict(signal='off'))
        self.assertFalse(wf.after_auto_pairs(self.s))
        update(self.s,self.r,7,dict(signal='unknown'))
        self.s.conn.execute("UPDATE meta SET value='before' WHERE key='active_scenario'");self.s.conn.commit()
        self.assertEqual(wf.after_auto_activate(self.s),0);self.assertFalse(self.connected())

    def test_rn_needs_real_port_and_on_unknown_can_complete(self):
        with self.s.action('RN 변경'):self.s.conn.execute("UPDATE nodes SET type='rn' WHERE id=?",(self.a,))
        self.s.ensure_ports(self.a,{'mp':1,'sp':0,'p':1})
        self.fill();wf.after_auto_activate(self.s);self.assertTrue(self.connected());self.assertFalse(self.complete())
        update(self.s,'PORT:'+self.a,1,dict(core_id='CORE',detail='같은 내역',signal='unknown'))
        self.assertTrue(self.s.splice_for(self.a,'PORT:'+self.a,1));self.assertTrue(self.complete())
        self.assertEqual(self.s.core('PORT:'+self.a,1)['signal'],'unknown')
        self.s.disconnect(self.a,'PORT:'+self.a,1);self.assertFalse(self.complete())


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(65,exit=True)
    with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,TELECOM_APP_HOME=t), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showerror') as errors, \
         patch.object(code['messagebox'],'showwarning') as warnings,patch.object(code['messagebox'],'askyesno',return_value=True):
        app=code['App']();callbacks=[];app.report_callback_exception=lambda *args:callbacks.append(args)
        try:
            print('AUTO UI: activate',flush=True)
            app.set_scenario_kind('after');s=app.store
            a=s.add_node('말단1',100,150);h=s.add_node('함체',400,150);b=s.add_node('말단2',700,150)
            l=s.add_cable(a,h,'LEFT','12C','기설');r=s.add_cable(h,b,'RIGHT','12C','기설')
            update(s,l,1,dict(core_id='CORE',detail='동일내역',signal='on'))
            print('AUTO UI: editor',flush=True)
            editor=code['open_detail_dialog'](app,s,'cable',l);editor.focus_core(1);app.update()
            print('AUTO UI: join',flush=True)
            update(s,r,7,dict(core_id='CORE',detail='동일내역',signal='unknown'));app.refresh();app.update()
            assert s.splice_for(h,l,1) and not s.incomplete_core_groups()
            assert wf.core_completion_brief(s,(l,1))==('연결완료','')
            assert s.drawing_connection_progress()['done']==1
            assert s.core(r,7)['signal']=='unknown'
            s.undo();app.refresh();app.update();assert not s.splice_for(h,l,1)
            s.redo();app.refresh();app.update();assert s.drawing_connection_progress()['done']==1
            assert not callbacks,callbacks;assert not errors.called,errors.call_args_list;assert not warnings.called,warnings.call_args_list
        finally:app.on_close();faulthandler.cancel_dump_traceback_later()
    print('PASS after automatic same-ID join, ON/unknown completion, UI refresh and undo/redo')


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(AutoConnectTests)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():raise SystemExit(1)
    windows_ui()
