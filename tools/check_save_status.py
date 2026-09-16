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
    fixture.HEADLESS=False
    with tempfile.TemporaryDirectory() as tmp:
        app,c=fixture.make_app(Path(tmp)/'pc',TimeoutServer());errors=[]
        app.report_callback_exception=lambda *args:errors.append(args)
        try:
            fixture.new_drawing(app,c,'Save UI');app.deiconify();app.geometry('1000x760');app.update()
            assert not app.advanced_tools_visible
            assert app.after_identity_button.winfo_viewable()
            assert app.after_identity_button.master is app.utility_toolbar
            s=app.store;s.add_node('Saved locally',0,0);c.session.fail='timeout'
            real=fixture.ns['DrawingSavedDialog'];observed=[]
            def dialog(*args,**kwargs):
                d=real(*args,**kwargs)
                def check():
                    if c.jobs.busy:d.after(50,check);return
                    try:
                        d.refresh_sync()
                        observed.append(d.sync_text.get())
                        assert d.title()=='PC 저장 완료'
                        assert '시간 초과' in observed[-1],observed
                        assert 'canceling' not in observed[-1]
                        assert app.scenario_path(app.scenario_kind()).exists()
                    except Exception as error:errors.append(error)
                    finally:d.destroy()
                d.after(200,check);return d
            with patch.dict(fixture.ns,DrawingSavedDialog=dialog):app.save_current_drawing()
            assert observed and not errors,(observed,errors)
            c.session.fail=None;c.sync_now();fixture.pump(app,c)
            d=real(app,'Save UI',app.scenario_kind(),s.path,app.scenario_path(app.scenario_kind()),'synthetic',cloud=c)
            assert d.sync_text.get().startswith('클라우드 저장 완료');d.destroy();app.update()
            assert not errors,errors
        finally:c.finish_close()
    print('PASS Windows actual save dialog: PC receipt, live timeout/recovery, timer cleanup and visible field identity button')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SaveStatusTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
