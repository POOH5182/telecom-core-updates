"""V147: a saved (dark blue) number in the core assignment panel can be
unassigned after one confirmation, then assigned again; Ctrl+Z restores it."""
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import wf,LocalApp,update


def drawing(app):
    s=app.store
    a=s.add_node('시작',0,150);b=s.add_node('중간',180,150);c=s.add_node('끝',500,150)
    left=s.add_cable(a,b,'LEFT','12C','기설')
    update(s,left,1,dict(core_id='CORE-1',detail='첫 회선',signal='on'))
    s.backup_to(app.scenario_path('before'))
    direct=s.add_cable(b,c,'DIRECT','12C','신설')
    return dict(a=a,b=b,c=c,left=left,direct=direct)


class UnassignTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store;self.ids=drawing(self.app)
        self.source=(self.ids['left'],1)
        service=wf.IncrementalCoreAllocator(self.app,self.source)
        service.apply(service.preview({**service.existing,self.ids['direct']:5}))
        self.service=wf.RNIncrementalCoreAllocator(self.app,self.source)
    def tearDown(self):self.s.close();self.temp.cleanup()
    def links(self,slot):return [r for r in self.s.conn.execute('SELECT * FROM splices') if (r['cable1_id'],r['core1_index'])==slot or (r['cable2_id'],r['core2_index'])==slot]

    def test_unassign_clears_number_and_its_splices_then_reassign_and_undo(self):
        slot=(self.ids['direct'],5);self.assertEqual(self.service.existing.get(self.ids['direct']),5)
        self.assertTrue(self.links(slot))
        before=wf.plan_snapshot(self.s.conn)
        backup=self.service.unassign(slot);self.assertTrue(backup.exists())
        self.assertEqual(self.s.core(*slot)['core_id'],'');self.assertEqual(self.links(slot),[])
        self.assertEqual(self.s.core(*self.source)['core_id'],'CORE-1')
        self.service.load();self.assertNotIn(self.ids['direct'],self.service.existing)
        self.assertTrue(self.service.availability(*slot)[0])
        after=wf.plan_snapshot(self.s.conn);self.s.undo();self.assertEqual(wf.plan_snapshot(self.s.conn),before)
        self.s.redo();self.assertEqual(wf.plan_snapshot(self.s.conn),after)
        self.service.load();self.service.apply(self.service.preview({**self.service.existing,self.ids['direct']:8}))
        self.assertEqual(self.s.core(self.ids['direct'],8)['core_id'],'CORE-1')

    def test_source_unsaved_and_locked_numbers_are_refused(self):
        cores=lambda:(wf.plan_snapshot(self.s.conn)['cores'],wf.plan_snapshot(self.s.conn)['splices'])
        original=cores()
        with self.assertRaisesRegex(ValueError,'출발'):self.service.unassign(self.source)
        with self.assertRaisesRegex(ValueError,'저장된 배정'):self.service.unassign((self.ids['direct'],6))
        self.s.set_node_locked(self.ids['c'],True);self.service.load()
        with self.assertRaisesRegex(ValueError,'잠금'):self.service.unassign((self.ids['direct'],5))
        self.assertEqual(cores(),original)

    def test_panel_click_asks_and_no_keeps_everything(self):
        class Panel(wf.ManualAllocationActions):
            def __init__(s,app,service):
                s.app=app;s.service=service;s.selected=dict(service.existing);s.columns=list(s.selected);s.msg=''
                s.message=type('M',(),{'set':lambda _,v:setattr(s,'msg',v)})()
            def render(s):pass
            def winfo_toplevel(s):return None
            def reload(s):s.service.load();s.selected=dict(s.service.existing);s.columns=list(s.selected)
        self.app.refresh=lambda:None
        panel=Panel(self.app,self.service);original=wf.plan_snapshot(self.s.conn)
        with patch.object(wf.messagebox,'askyesno',return_value=False):self.assertTrue(panel.offer_unassign(self.ids['direct'],5))
        self.assertEqual(wf.plan_snapshot(self.s.conn),original);self.assertIn('유지',panel.msg)
        with patch.object(wf.messagebox,'askyesno',return_value=True):self.assertTrue(panel.offer_unassign(self.ids['direct'],5))
        self.assertEqual(self.s.core(self.ids['direct'],5)['core_id'],'')
        self.assertIn(self.ids['direct'],panel.columns);self.assertNotIn(self.ids['direct'],panel.selected)
        self.assertIn('미배정',panel.msg)
        self.assertFalse(panel.offer_unassign(*self.source))


if __name__=='__main__':unittest.main(verbosity=2)
