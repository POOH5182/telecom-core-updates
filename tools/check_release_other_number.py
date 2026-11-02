"""V188: in core assignment, a gray number another core uses (사용 중) can be
emptied after one yes/no, then becomes this core's draft number. Only that
number and its splices change; the other core keeps its other numbers.
Ctrl+Z restores everything."""
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import wf,LocalApp,update


def drawing(app):
    s=app.store
    a=s.add_node('start',0,150);b=s.add_node('mid',180,150);c=s.add_node('end',500,150)
    left=s.add_cable(a,b,'LEFT','12C','기설')
    update(s,left,1,dict(core_id='CORE-1',detail='first',signal='on'))
    update(s,left,5,dict(core_id='OTHER-9',detail='other line',signal='on'))
    s.backup_to(app.scenario_path('before'))
    direct=s.add_cable(b,c,'DIRECT','12C','신설')
    update(s,direct,5,dict(core_id='OTHER-9',detail='other line',signal='on'))
    update(s,direct,7,dict(core_id='',detail='memo only',signal=''))
    s.connect(b,(left,5),(direct,5))
    return dict(a=a,b=b,c=c,left=left,direct=direct)


class ReleaseOtherTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store;self.ids=drawing(self.app)
        self.source=(self.ids['left'],1)
        self.service=wf.RNIncrementalCoreAllocator(self.app,self.source)
    def tearDown(self):self.s.close();self.temp.cleanup()
    def links(self,slot):return [r for r in self.s.conn.execute('SELECT * FROM splices') if (r['cable1_id'],r['core1_index'])==slot or (r['cable2_id'],r['core2_index'])==slot]

    def test_release_empties_one_number_then_assign_and_undo(self):
        slot=(self.ids['direct'],5)
        allowed,reason=self.service.availability(*slot);self.assertFalse(allowed);self.assertEqual(reason,'기존 접속 사용 중')
        p=self.service.release_other_preview(slot);self.assertEqual(p['other_id'],'OTHER-9');self.assertTrue(p['peers'])
        before=wf.plan_snapshot(self.s.conn)
        backup=self.service.release_other(slot);self.assertTrue(backup.exists())
        self.assertEqual(self.s.core(*slot)['core_id'],'');self.assertEqual(self.links(slot),[])
        self.assertEqual(self.s.core(self.ids['left'],5)['core_id'],'OTHER-9')
        self.assertEqual(self.s.core(*self.source)['core_id'],'CORE-1')
        self.service.load();self.assertTrue(self.service.availability(*slot)[0])
        after=wf.plan_snapshot(self.s.conn);self.s.undo();self.assertEqual(wf.plan_snapshot(self.s.conn),before)
        self.s.redo();self.assertEqual(wf.plan_snapshot(self.s.conn),after)
        self.service.load();self.service.apply(self.service.preview({**self.service.existing,self.ids['direct']:5}))
        self.assertEqual(self.s.core(*slot)['core_id'],'CORE-1')

    def test_detail_only_number_released(self):
        slot=(self.ids['direct'],7)
        self.assertEqual(self.service.availability(*slot)[1],'기존 코어ID·내역·신호·상태 사용 중')
        self.service.release_other(slot);self.assertEqual(self.s.core(*slot)['detail'],'')

    def test_refusals_change_nothing(self):
        state=lambda:(wf.plan_snapshot(self.s.conn)['cores'],wf.plan_snapshot(self.s.conn)['splices'])
        original=state()
        with self.assertRaisesRegex(ValueError,'기존 선번'):self.service.release_other((self.ids['left'],5))
        with self.assertRaisesRegex(ValueError,'빈 번호'):self.service.release_other((self.ids['direct'],3))
        self.s.set_node_locked(self.ids['c'],True);self.service.load()
        with self.assertRaisesRegex(ValueError,'잠금'):self.service.release_other((self.ids['direct'],5))
        self.assertEqual(state(),original)

    def test_panel_click_asks_no_keeps_yes_drafts(self):
        class Panel(wf.ManualAllocationActions):
            def __init__(s,app,service):
                s.app=app;s.service=service;s.selected=dict(service.existing);s.columns=list(s.selected);s.msg=''
                s.message=type('M',(),{'set':lambda _,v:setattr(s,'msg',v)})()
            def render(s):pass
            def winfo_toplevel(s):return None
            def reload(s):s.service.load();s.selected=dict(s.service.existing);s.columns=list(s.selected)
        self.app.refresh=lambda:None
        direct=self.ids['direct'];panel=Panel(self.app,self.service);panel.columns.append(direct)
        original=wf.plan_snapshot(self.s.conn)
        with patch.object(wf.messagebox,'askyesno',return_value=False):self.assertTrue(panel.offer_release(direct,5))
        self.assertEqual(wf.plan_snapshot(self.s.conn),original);self.assertIn('OTHER-9',panel.msg)
        self.assertFalse(panel.offer_release(direct,3))
        self.assertFalse(panel.offer_release(self.ids['left'],5))
        with patch.object(wf.messagebox,'askyesno',return_value=True):self.assertTrue(panel.offer_release(direct,5))
        self.assertEqual(self.s.core(direct,5)['core_id'],'')
        self.assertIn(direct,panel.columns);self.assertEqual(panel.selected.get(direct),5)
        print('PASS release other number')


if __name__=='__main__':unittest.main(verbosity=2)
