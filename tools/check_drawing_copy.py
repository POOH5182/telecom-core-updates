"""Independent drawing copies: full snapshots/history, durable outbox and real list UI."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import smoke_cloud_windows as smoke

cloud,ns=smoke.cloud,smoke.ns


class DrawingCopyTests(unittest.TestCase):
    def setUp(self):
        smoke.HEADLESS=True
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.home=self.root/'pc-one'
        self.env=patch.dict(os.environ,{});self.env.start()
        self.info=patch.object(cloud.messagebox,'showinfo');self.info.start()
        self.warning=patch.object(cloud.messagebox,'showwarning');self.warning.start()
        self.server=smoke.Server();self.app,self.c=smoke.make_app(self.home,self.server)
        self.key=smoke.new_drawing(self.app,self.c,'원본 도면')
        s=self.app.store;a=s.add_node('끝 A',0,0);h=s.add_node('함체',200,0);b=s.add_node('끝 B',400,0)
        left=s.add_cable(a,h,'A','12C','기설');right=s.add_cable(h,b,'B','12C','기설')
        s.update_core(left,1,('123','원본 내역','normal','','on'));s.connect(h,(left,1),(right,1));s.set_node_locked(h,True)
        s.backup_to(self.app.scenario_path('gis'));s.backup_to(self.app.scenario_path('before'))
        s.add_node('후도면 표시',600,0);s.backup_to(self.app.scenario_path('after'))
        self.c.sync_now();smoke.pump(self.app,self.c)

    def tearDown(self):
        if not self.c.closing:self.c.finish_close()
        self.warning.stop();self.info.stop();self.env.stop();self.temp.cleanup()

    def duplicate(self,name='복사본',row=None):
        before=set(self.c.index['docs'])
        with patch.object(cloud.simpledialog,'askstring',return_value=name):self.c.copy_drawing(row or self.server.rows[self.key])
        smoke.pump(self.app,self.c)
        return set(self.c.index['docs'])-before

    def test_full_copy_retains_original_and_all_snapshots_history_locks_then_edits_independently(self):
        original=copy.deepcopy(self.server.rows[self.key]);before=cloud.cloud_bundle(self.app.store,self.app.scenario_folder())
        path=self.app.store.path;history=self.app.store.history_rows();current=self.c.current
        ids=self.duplicate('복사 / 별도안');self.assertEqual(len(ids),1);new=ids.pop()
        self.assertEqual(self.c.current,current);self.assertEqual(self.app.store.path,path)
        self.assertEqual(self.server.rows[self.key],original);self.assertEqual(cloud.cloud_bundle(self.app.store,self.app.scenario_folder()),before)
        expected=cloud.cloud_unpack(before);actual=cloud.cloud_unpack(base64.b64decode(self.server.rows[new]['payload']))
        self.assertEqual(expected,actual);self.assertEqual(set(actual),cloud.CLOUD_FILES)
        self.assertNotEqual(self.c.entry(new)['stem'],self.c.entry(self.key)['stem'])
        self.c.open_drawing(self.server.rows[new]);smoke.pump(self.app,self.c)
        self.assertEqual(self.app.store.history_rows(),history)
        self.app.store.add_node('복사본에만 추가',800,0);self.c.sync_now();smoke.pump(self.app,self.c)
        self.assertEqual(self.server.rows[self.key],original)
        self.c.open_drawing(original);smoke.pump(self.app,self.c)
        self.assertNotIn('복사본에만 추가',smoke.names(self.app))

    def test_cancel_invalid_name_busy_and_access_loss_do_not_create_or_switch(self):
        before=copy.deepcopy(self.c.index);current=self.c.current
        for name in (None,' ','가'*121):self.assertEqual(self.duplicate(name),set())
        self.assertEqual(self.c.index,before);self.assertEqual(self.c.current,current)
        self.c.access_lost=True;self.assertEqual(self.duplicate(),set());self.c.access_lost=False
        self.app.pending_drag=True
        self.assertEqual(self.duplicate(),set());self.app.pending_drag=False

    def test_uncaptured_local_work_is_copied_without_overwriting_remote_original(self):
        original=copy.deepcopy(self.server.rows[self.key])
        self.app.store.add_node('미동기화 최신 작업',900,0)
        # Switch away as after a crash: do not capture the source's unsent work.
        other=smoke.new_drawing(self.app,self.c,'다른 도면')
        self.assertEqual(self.c.current,other)
        new=self.duplicate().pop();self.assertEqual(self.c.current,other)
        self.assertEqual(self.server.rows[self.key],original)
        self.c.open_drawing(self.server.rows[new]);smoke.pump(self.app,self.c)
        self.assertIn('미동기화 최신 작업',smoke.names(self.app))

    def test_remote_only_copy_verifies_contents_and_keeps_original_uninstalled(self):
        self.c.finish_close();self.app,self.c=smoke.make_app(self.root/'pc-two',self.server)
        original=copy.deepcopy(self.server.rows[self.key]);new=self.duplicate().pop()
        self.assertIsNone(self.c.current);self.assertNotIn(self.key,self.c.index['docs'])
        self.assertEqual(self.server.rows[self.key],original)
        self.assertEqual(cloud.cloud_unpack(base64.b64decode(self.server.rows[new]['payload'])),cloud.cloud_unpack(base64.b64decode(original['payload'])))
        self.server.rows[self.key]['sha256']='0'*64
        self.assertEqual(self.duplicate(),set())

    def test_clean_inactive_cache_copies_latest_remote_revision(self):
        folder=self.root/'remote';folder.mkdir()
        for name,data in cloud.cloud_unpack(base64.b64decode(self.server.rows[self.key]['payload'])).items():(folder/name).write_bytes(data)
        store=ns['Store'](folder/'working.sqlite3')
        store.add_node('다른 PC의 최신 내용',1000,0);payload=cloud.cloud_bundle(store,folder);store.close()
        self.server.rows[self.key].update(payload=base64.b64encode(payload).decode(),sha256=hashlib.sha256(payload).hexdigest(),revision=3)
        smoke.new_drawing(self.app,self.c,'별도 도면')
        new=self.duplicate().pop()
        self.assertEqual(cloud.cloud_unpack(base64.b64decode(self.server.rows[new]['payload'])),cloud.cloud_unpack(payload))

    def test_network_failure_reopen_and_lost_ack_do_not_duplicate_copies(self):
        self.server.fail='network';new=self.duplicate().pop()
        request=json.loads((self.c.outbox()/(new+'.json')).read_bytes());self.assertNotIn(new,self.server.rows)
        self.c.finish_close();self.app,self.c=smoke.make_app(self.home,self.server)
        self.server.fail='lost_ack';self.c.sync_now();smoke.pump(self.app,self.c)
        self.assertEqual(self.server.rows[new]['operation_id'],request['operation_id']);self.assertTrue((self.c.outbox()/(new+'.json')).exists())
        self.c.sync_now();smoke.pump(self.app,self.c)
        self.assertEqual(self.server.rows[new]['revision'],1);self.assertFalse((self.c.outbox()/(new+'.json')).exists())
        self.assertEqual(len(self.server.rows),2)

    def test_pending_remote_copy_retries_without_an_open_drawing(self):
        self.c.finish_close();self.app,self.c=smoke.make_app(self.root/'pc-two',self.server)
        self.c.save_drawing_copy(base64.b64decode(self.server.rows[self.key]['payload']),'대기 복사본')
        self.server.fail='network';self.c.sync_now();smoke.pump(self.app,self.c)
        self.assertIsNone(self.c.current);self.assertTrue(list(self.c.outbox().glob('*.json')))
        self.server.fail=None;self.c.retry_at=0;self.c.tick();smoke.pump(self.app,self.c)
        self.assertFalse(list(self.c.outbox().glob('*.json')));self.assertEqual(len(self.server.rows),2)

    def test_copy_outbox_write_interruption_recovers_registered_copy_after_restart(self):
        original_json=cloud.cloud_json
        def fail_outbox(path,value):
            if Path(path).parent.name=='cloud_outbox':raise OSError('synthetic outbox interruption')
            return original_json(path,value)
        with patch.object(cloud,'cloud_json',side_effect=fail_outbox):new=self.duplicate().pop()
        op=self.c.entry(new)['copy_pending'];self.assertNotIn(new,self.server.rows)
        self.c.finish_close();self.app,self.c=smoke.make_app(self.home,self.server)
        self.c.sync_now();smoke.pump(self.app,self.c)
        self.assertEqual(self.server.rows[new]['operation_id'],op);self.assertEqual(self.server.rows[new]['revision'],1)
        self.assertNotIn('copy_pending',self.c.entry(new))


def windows_ui():
    if sys.platform!='win32':return
    smoke.HEADLESS=False
    with tempfile.TemporaryDirectory() as temp,patch.object(cloud.messagebox,'showinfo'),patch.object(cloud.messagebox,'showwarning'):
        server=smoke.Server();app,c=smoke.make_app(Path(temp)/'pc',server);errors=[];app.report_callback_exception=lambda *a:errors.append(str(a))
        try:
            key=smoke.new_drawing(app,c,'원본');app.store.add_node('복사할 함체',100,100);c.sync_now();smoke.pump(app,c)
            original=copy.deepcopy(server.rows[key]);app.deiconify();app.update();c.projects();smoke.pump(app,c);app.update()
            def widgets(w):
                for child in w.winfo_children():yield child;yield from widgets(child)
            window=c.dialog;tree=next(w for w in widgets(window) if isinstance(w,cloud.ttk.Treeview))
            button=next(w for w in widgets(window) if isinstance(w,cloud.ttk.Button) and w.cget('text')=='도면 복사')
            assert button.winfo_ismapped() and button.winfo_rootx()+button.winfo_width()<=window.winfo_rootx()+window.winfo_width()
            tree.selection_set(key)
            with patch.object(cloud.simpledialog,'askstring',return_value=None):button.invoke()
            assert len(c.index['docs'])==1 and c.current==key
            with patch.object(cloud.simpledialog,'askstring',return_value='원본 - 복사본'):button.invoke()
            smoke.pump(app,c);app.update();new=next(k for k in c.index['docs'] if k!=key)
            assert tree.selection()==(new,) and c.current==key and window.winfo_exists()
            assert server.rows[key]==original and server.rows[new]['name']=='원본 - 복사본'
            opening=next(w for w in widgets(window) if isinstance(w,cloud.ttk.Button) and w.cget('text')=='열기');opening.invoke();smoke.pump(app,c);app.update()
            assert c.current==new and '복사할 함체' in smoke.names(app)
            assert not errors,errors
        finally:c.finish_close()
    print('PASS Windows My Drawings copy button visible, cancel, new row selection, original retained, independent open')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(DrawingCopyTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
