"""Local save receipts, timeout retry and acknowledgements of the latest edit."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import smoke_cloud_windows as fixture

cloud=fixture.cloud


class TimeoutServer(fixture.Server):
    def call(self,action,**request):
        if self.fail=='timeout' and action=='save':
            raise cloud.CloudError('canceling statement due to statement timeout','57014')
        return super().call(action,**request)


class SaveStatusTests(unittest.TestCase):
    def setUp(self):
        fixture.HEADLESS=True
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)/'pc'
        self.server=TimeoutServer();self.app,self.c=fixture.make_app(self.home,self.server)
        self.key=fixture.new_drawing(self.app,self.c,'Synthetic save')
    def tearDown(self):self.c.finish_close();self.temp.cleanup()
    def saved_names(self):
        data=cloud.cloud_unpack(base64.b64decode(self.server.rows[self.c.current]['payload']))
        path=self.home/'verify.sqlite3';path.write_bytes(data['working.sqlite3'])
        store=fixture.ns['Store'](path)
        try:return {r['name'] for r in store.nodes()}
        finally:store.close()

    def test_timeout_keeps_local_snapshot_and_same_operation_across_restart(self):
        self.app.store.add_node('PC saved',0,0)
        self.app.store.backup_to(self.app.scenario_path('before'))
        self.server.fail='timeout';self.c.sync_now();fixture.pump(self.app,self.c)
        self.assertIn('시간 초과',self.c.save_status());self.assertNotIn('canceling',self.c.status.value)
        pending=self.c.outbox()/(self.key+'.json');operation=json.loads(pending.read_bytes())['operation_id']
        original=self.app.scenario_path('before').read_bytes()
        self.c.finish_close();self.app,self.c=fixture.make_app(self.home,self.server)
        self.c.activate(self.key)
        self.assertIn('대기',self.c.save_status());self.assertEqual(json.loads(pending.read_bytes())['operation_id'],operation)
        self.server.fail=None;self.c.sync_now();fixture.pump(self.app,self.c)
        self.assertTrue(self.c.save_status().startswith('클라우드 저장 완료'))
        self.assertEqual(self.server.rows[self.key]['operation_id'],operation)
        self.assertEqual(self.app.scenario_path('before').read_bytes(),original)
        self.assertIn('PC saved',self.saved_names())

    def test_late_edit_is_uploaded_before_completion(self):
        self.app.store.add_node('first',0,0);self.c.sync_now()
        self.app.store.add_node('late',1,1)
        self.assertFalse(self.c.save_status().startswith('클라우드 저장 완료'))
        self.c.jobs.step()
        self.assertTrue(self.c.jobs.busy)
        self.assertFalse(self.c.save_status().startswith('클라우드 저장 완료'))
        fixture.pump(self.app,self.c)
        self.assertEqual(self.saved_names(),{'first','late'})
        self.assertTrue(self.c.save_status().startswith('클라우드 저장 완료'))

    def test_lost_ack_is_pending_until_idempotent_retry(self):
        self.app.store.add_node('accepted',0,0);self.server.fail='lost_ack'
        self.c.sync_now();fixture.pump(self.app,self.c);revision=self.server.rows[self.key]['revision']
        self.assertIn('미완료',self.c.save_status());self.assertIn('응답',self.c.save_status())
        self.c.sync_now();fixture.pump(self.app,self.c)
        self.assertEqual(self.server.rows[self.key]['revision'],revision)
        self.assertTrue(self.c.save_status().startswith('클라우드 저장 완료'))

    def test_wrong_receipt_and_local_queue_failure_never_report_success(self):
        self.app.store.add_node('unacknowledged',0,0)
        with patch.object(self.server,'call',return_value={'id':self.key,'revision':999,'sha256':'wrong'}):
            self.c.sync_now();fixture.pump(self.app,self.c)
        self.assertTrue(list(self.c.outbox().glob('*.json')))
        self.assertIn('미완료',self.c.save_status())
        self.c.sync_now();fixture.pump(self.app,self.c)
        self.app.store.add_node('queue error',1,1)
        with patch.object(self.c,'capture',side_effect=OSError('Synthetic disk full')):self.c.sync_now()
        self.assertIn('미완료',self.c.status.value)
        self.assertNotIn('PC에 저장됨',self.c.status.value)


def windows_ui():
    if sys.platform!='win32':return
    import threading
    from types import SimpleNamespace
    from check_popup_monitor import assert_centered
    fixture.HEADLESS=False
    class HeldServer(TimeoutServer):
        def __init__(self):super().__init__();self.hold=False;self.release=threading.Event();self.release.set()
        def call(self,action,**request):
            if action=='save' and self.hold:
                if not self.release.wait(5):raise cloud.CloudError('Synthetic held upload timeout','network')
            return super().call(action,**request)
    with tempfile.TemporaryDirectory() as tmp:
        server=HeldServer();app,c=fixture.make_app(Path(tmp)/'pc',server);errors=[]
        app.report_callback_exception=lambda *args:errors.append(args)
        def guarded(fn):
            def run():
                try:fn()
                except Exception as exc:
                    errors.append(exc)
                    d=getattr(app,'_save_dialog',None)
                    if d is not None and d.winfo_exists():d.destroy()
            return run
        def key(d,name='space'):
            d.primary.focus_force();app.update_idletasks()
            d.primary.event_generate('<KeyPress-'+name+'>');d.primary.event_generate('<KeyRelease-'+name+'>')
        def saved_when_ready(d,check):
            def poll():
                if d.save_phase=='complete':check();return
                assert d.save_phase!='error',d.detail.get()
                d.after(25,guarded(poll))
            d.after(25,guarded(poll))
        def run_save(inspect,event=None):
            app.after(100,guarded(lambda:inspect(app._save_dialog)))
            timeout=app.after(12000,guarded(lambda:(_ for _ in ()).throw(AssertionError('Save dialog did not finish'))))
            try:app.save_current_drawing(event)
            finally:app.after_cancel(timeout)
            assert not errors,errors
            assert app._save_dialog is None and not app._saving_now
        try:
            fixture.new_drawing(app,c,'Save UI');app.deiconify();app.geometry('1000x760+30+40');app.update()
            assert not app.advanced_tools_visible and app.drawing_tools.edit_button.winfo_viewable()
            s=app.store;s.add_node('Saved locally',0,0)
            before=app.scenario_path(app.scenario_kind())
            old=before.read_bytes() if before.exists() else None
            def cancel(d):
                assert d.message.get()=='저장하시겠습니까?' and d.detail.get()==''
                assert d.save_phase=='confirm';assert_centered(d,app)
                d.secondary.invoke()
            with patch.object(app,'save_current_snapshot',wraps=app.save_current_snapshot) as commit:
                run_save(cancel);assert commit.call_count==0
            assert (before.read_bytes() if before.exists() else None)==old
            # A held real background upload cannot be mistaken for a completed save.
            server.hold=True;server.release.clear()
            def confirm_held(d):
                key(d)
                def during():
                    assert d.save_phase=='saving' and d.local_done and c.jobs.busy
                    assert before.exists() and 'disabled' in d.primary.state()
                    d.close_notice();assert d.winfo_exists()
                    d.tk.call(d.protocol('WM_DELETE_WINDOW'));assert d.winfo_exists()
                    d.event_generate('<Escape>');assert d.winfo_exists()
                    key(d,'Return');assert d.winfo_exists()
                    app.save_current_drawing();assert app._save_dialog is d
                    d.primary.event_generate('<KeyPress-space>')
                    server.hold=False;server.release.set()
                    def complete():
                        assert d.message.get()=='저장 완료되었습니다.' and 'PC·클라우드 저장 완료' in d.detail.get()
                        assert d.winfo_exists() and d.sync_timer is None
                        # Release of a key held during upload must not dismiss completion.
                        d.primary.event_generate('<KeyRelease-space>');assert d.winfo_exists()
                        key(d);assert not d.winfo_exists()
                    saved_when_ready(d,complete)
                d.after(100,guarded(during))
            with patch.object(app,'save_current_snapshot',wraps=app.save_current_snapshot) as commit:
                run_save(confirm_held);assert commit.call_count==1
            assert cloud.CloudController.save_status(c).startswith('클라우드 저장 완료')
            # Failed cloud saves keep the same popup, PC receipt and retry operation.
            s.add_node('Retry latest',100,0);server.fail='timeout'
            owner=cloud.RememberedToplevel(app);owner.geometry('540x300');owner.grab_set();app.update()
            def retry_flow(d):
                assert d.master is owner;assert_centered(d,owner);d.primary.invoke()
                def failed():
                    if d.save_phase=='saving':d.after(25,guarded(failed));return
                    assert d.save_phase=='error' and d.winfo_exists() and d.local_done
                    assert '시간 초과' in d.detail.get() and 'canceling' not in d.detail.get()
                    request=c.outbox()/(c.current+'.json');operation=json.loads(request.read_bytes())['operation_id']
                    server.fail=None;d.primary.invoke()
                    def complete():
                        assert server.rows[c.current]['operation_id']==operation
                        assert '편집창' in d.detail.get();key(d,'Return')
                    saved_when_ready(d,complete)
                d.after(100,guarded(failed))
            run_save(retry_flow,SimpleNamespace(widget=owner));assert owner.grab_current() is owner
            owner.destroy();app.update()
            # Disk failures remain visible and never claim PC or cloud success.
            def failed_disk(d):
                d.primary.invoke()
                def check():
                    assert d.save_phase=='error' and not d.local_done
                    assert d.message.get()=='저장하지 못했습니다.' and '디스크' in d.detail.get()
                    d.secondary.invoke()
                d.after(100,guarded(check))
            with patch.object(app,'save_current_snapshot',side_effect=OSError('디스크 시험 실패')),patch.object(c,'sync_now') as sync:
                run_save(failed_disk);assert not sync.called
            # Local-only saving also waits for the snapshot and keeps completion visible.
            def local(d):
                key(d)
                def complete():
                    assert d.local_done and d.detail.get()=='이 PC에 저장되었습니다.';key(d)
                saved_when_ready(d,complete)
            with patch.object(app,'cloud',None):run_save(local)
            app.save_current_drawing(silent=True);app.update();fixture.pump(app,c)
            assert not errors,errors
        finally:server.release.set();c.finish_close()
    print('PASS Windows simple confirmation/Space, no-write cancel, held upload, blocked close/duplicate keys, persistent completion, cloud retry/PC receipt, disk failure, owner monitor/grab and silent save')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SaveStatusTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
