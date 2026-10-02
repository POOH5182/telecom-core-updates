"""Drawing-list removal: retained work, tombstones, retries and native controls."""
import base64
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import smoke_cloud_windows as smoke

cloud,ns=smoke.cloud,smoke.ns


class DrawingDeleteTests(unittest.TestCase):
    def setUp(self):
        smoke.HEADLESS=True
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.home=self.root/'pc'
        self.env=patch.dict(os.environ,{});self.env.start()
        self.info=patch.object(cloud.messagebox,'showinfo');self.info.start()
        self.warning=patch.object(cloud.messagebox,'showwarning');self.warning.start()
        self.server=smoke.Server();self.app,self.c=smoke.make_app(self.home,self.server)
        self.key=smoke.new_drawing(self.app,self.c,'삭제 대상')
        self.app.store.add_node('보존할 작업',100,100)
        for phase in ('gis','before','after'):self.app.store.backup_to(self.app.scenario_path(phase))
        self.c.sync_now();smoke.pump(self.app,self.c)

    def tearDown(self):
        self.c.finish_close();self.warning.stop();self.info.stop();self.env.stop();self.temp.cleanup()

    def delete(self,row=None,confirmed=True):
        with patch.object(cloud.messagebox,'askyesno',return_value=confirmed):self.c.delete_drawing(row or self.server.rows[self.key])
        smoke.pump(self.app,self.c)

    def test_active_removal_keeps_unsent_work_stages_history_and_other_drawing(self):
        other=smoke.new_drawing(self.app,self.c,'유지할 도면');original=copy.deepcopy(self.server.rows[other])
        self.c.open_drawing(self.server.rows[self.key]);smoke.pump(self.app,self.c)
        self.app.store.add_node('마지막 미전송 작업',200,200)
        before=cloud.cloud_unpack(cloud.cloud_bundle(self.app.store,self.app.scenario_folder()))
        self.c.capture();pending=(self.c.outbox()/(self.key+'.json')).read_bytes()
        self.delete()
        self.assertNotIn(self.key,self.c.index['docs']);self.assertIsNone(self.c.current)
        self.assertEqual(smoke.names(self.app),set());self.assertEqual(self.server.rows[other],original)
        folder=self.home/'cloud_deleted'/self.key
        self.assertEqual(cloud.cloud_unpack((folder/'drawing.zip').read_bytes()),before)
        self.assertEqual((folder/'pending.json').read_bytes(),pending)
        self.assertEqual(set(before),cloud.CLOUD_FILES);self.assertFalse(list(self.c.outbox().glob('*.json')))
        self.c.finish_close();self.app,self.c=smoke.make_app(self.home,self.server)
        self.assertNotIn(self.key,self.c.index['docs']);self.c.sync_now();smoke.pump(self.app,self.c)
        self.assertEqual([r['id'] for r in self.server.call('list')],[other])

    def test_cancel_busy_drafts_access_loss_and_failed_backup_preserve_drawing(self):
        original=copy.deepcopy(self.server.rows);index=copy.deepcopy(self.c.index)
        self.delete(confirmed=False)
        self.app.pending_drag=True;self.delete();self.app.pending_drag=False
        with patch.object(cloud,'stage_open_editors',return_value=[object()]):self.delete()
        self.c.access_lost=True;self.delete();self.c.access_lost=False
        with patch.object(cloud,'cloud_bundle',side_effect=OSError('backup failed')):self.delete()
        self.assertEqual(self.server.rows,original);self.assertEqual(self.c.index,index)
        self.assertEqual(self.c.current,self.key)

    def test_network_failure_stale_revision_and_lost_ack(self):
        original=copy.deepcopy(self.c.index);row=copy.deepcopy(self.server.rows[self.key])
        self.server.fail='network';self.delete();self.assertEqual(self.c.index,original)
        self.server.fail=None;self.server.rows[self.key]['revision']+=1
        self.delete(row);self.assertEqual(self.c.index,original);self.assertFalse(self.server.rows[self.key].get('deleted'))
        row=copy.deepcopy(self.server.rows[self.key]);self.server.fail='lost_ack';self.delete(row)
        self.assertIn(self.key,self.c.index['docs']);self.assertTrue(self.server.rows[self.key]['deleted'])
        revision=self.server.rows[self.key]['revision'];self.delete(row)
        self.assertNotIn(self.key,self.c.index['docs']);self.assertEqual(self.server.rows[self.key]['revision'],revision)

    def test_other_pc_pending_save_cannot_resurrect_and_is_quarantined(self):
        self.app.store.add_node('다른 PC 미전송 수정',200,0);self.c.capture()
        row=self.server.rows[self.key]
        self.server.call('delete',id=self.key,name=row['name'],base_revision=row['revision'],operation_id='synthetic')
        self.c.sync_now();smoke.pump(self.app,self.c)
        self.assertNotIn(self.key,self.c.index['docs']);self.assertEqual(self.server.call('list'),[])
        self.assertTrue((self.home/'cloud_deleted'/self.key/'pending.json').exists())
        self.assertEqual(len(self.server.rows),1)

    def test_remote_only_and_unsynced_local_removal(self):
        row=copy.deepcopy(self.server.rows[self.key]);self.c.finish_close()
        self.app,self.c=smoke.make_app(self.root/'pc-two',self.server)
        self.delete(row);self.assertEqual(self.server.call('list'),[])
        self.server.fail='network';key=smoke.new_drawing(self.app,self.c,'아직 PC에만 있음')
        self.server.fail=None;self.delete(dict(id=key,name='아직 PC에만 있음',revision=0))
        self.assertNotIn(key,self.c.index['docs']);self.assertTrue(self.server.rows[key]['deleted'])
        self.assertFalse(list(self.c.outbox().glob('*.json')))

    def test_catalog_removes_old_cache_and_poll_clears_current(self):
        row=self.server.rows[self.key]
        self.server.call('delete',id=self.key,name=row['name'],base_revision=row['revision'],operation_id='synthetic')
        self.c.poll_remote();smoke.pump(self.app,self.c)
        self.assertIsNone(self.c.current);self.assertNotIn(self.key,self.c.index['docs'])
        self.assertEqual(self.c.reconcile_catalog(self.server.call('catalog')),[])

    def test_local_index_failure_can_reconcile_after_server_success(self):
        with patch.object(self.c,'persist',side_effect=OSError('synthetic index failure')):self.delete()
        self.assertIn(self.key,self.c.index['docs']);self.assertEqual(self.c.current,self.key)
        self.assertTrue(self.server.rows[self.key]['deleted'])
        self.c.reconcile_catalog(self.server.call('catalog'))
        self.assertNotIn(self.key,self.c.index['docs']);self.assertIsNone(self.c.current)


def windows_ui():
    if sys.platform!='win32':return
    smoke.HEADLESS=False
    with tempfile.TemporaryDirectory() as temp,patch.object(cloud.messagebox,'showinfo'),patch.object(cloud.messagebox,'showwarning'):
        server=smoke.Server();app,c=smoke.make_app(Path(temp)/'pc',server);errors=[]
        app.report_callback_exception=lambda *a:errors.append(str(a))
        try:
            key=smoke.new_drawing(app,c,'SYNTH 삭제 확인 대상');app.store.add_node('SYNTH 함체',0,0)
            c.sync_now();smoke.pump(app,c);app.deiconify();app.update();c.projects();smoke.pump(app,c);app.update()
            def widgets(w):
                for child in w.winfo_children():yield child;yield from widgets(child)
            window=c.dialog;tree=next(w for w in widgets(window) if isinstance(w,cloud.ttk.Treeview))
            buttons={w.cget('text'):w for w in widgets(window) if isinstance(w,cloud.ttk.Button)}
            for button in buttons.values():
                assert button.winfo_ismapped()
                assert button.winfo_rootx()+button.winfo_width()<=window.winfo_rootx()+window.winfo_width()
                assert button.winfo_rooty()+button.winfo_height()<=window.winfo_rooty()+window.winfo_height()
            tree.selection_set(key)
            with patch.object(cloud.messagebox,'askyesno',return_value=False) as confirm:buttons['도면 삭제'].invoke()
            assert key in tree.get_children() and c.current==key
            assert 'SYNTH 삭제 확인 대상' in confirm.call_args.args[1] and confirm.call_args.kwargs['default']=='no'
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True);screenshot(window,Path('dist')/'v125-drawing-list-delete.png')
            with patch.object(cloud.messagebox,'askyesno',return_value=True):buttons['도면 삭제'].invoke()
            smoke.pump(app,c);app.update()
            assert key not in tree.get_children() and c.current is None and not smoke.names(app)
            assert (c.home/'cloud_deleted'/key/'drawing.zip').exists()
            buttons['새로고침'].invoke();smoke.pump(app,c);assert not tree.get_children()
            with patch.object(cloud.simpledialog,'askstring',return_value='SYNTH 새 도면'):buttons['새 도면'].invoke()
            smoke.pump(app,c);app.update();assert c.current and c.current!=key
            assert not errors,errors
        finally:c.finish_close()
    print('PASS Windows drawing delete: visible controls, named cancel/default-no, active/last removal, backup, refresh and new drawing')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DrawingDeleteTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
