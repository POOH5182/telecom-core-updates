"""V146: an excluded core (e.g. a temporary core without signal) can still be
assigned on the map after one explicit yes; refusing keeps everything unchanged."""
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import wf,LocalApp,update


def drawing(app):
    s=app.store
    a=s.add_node('시작',0,150);b=s.add_node('왼쪽 끊김',180,150);c=s.add_node('오른쪽 끊김',500,150);d=s.add_node('끝',680,150)
    left=s.add_cable(a,b,'LEFT','12C','기설');cut=s.add_cable(b,c,'OLD-CUT','12C','기설');right=s.add_cable(c,d,'RIGHT','12C','기설')
    update(s,left,1,dict(core_id='임시-900',detail='임시 회선',signal=''))
    s.connect(b,(left,1),(cut,1));s.connect(c,(cut,1),(right,1))
    s.backup_to(app.scenario_path('before'))
    with s.action('후도면 절단 시험'):s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(cut,))
    direct=s.add_cable(b,c,'DIRECT','12C','신설')
    return dict(left=left,right=right,direct=direct)


class ExcludedAllocationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store;self.ids=drawing(self.app)
        self.source=(self.ids['left'],1)
    def tearDown(self):self.s.close();self.temp.cleanup()

    def report(self):
        r=wf.completion_report(self.s,'after');return r['excluded'],sorted(x['core_id'] for x in r['rows'])

    def test_excluded_core_asks_instead_of_blocking(self):
        for cls in (wf.ManualCoreAllocator,wf.IncrementalCoreAllocator,wf.RNIncrementalCoreAllocator):
            with self.subTest(cls=cls.__name__):
                with self.assertRaises(wf.ExcludedAllocationCore) as caught:cls(self.app,self.source)
                self.assertIsInstance(caught.exception,ValueError)
                self.assertIn('임시',caught.exception.reason)

    def test_refusing_opens_nothing_and_yes_opens_with_permission(self):
        calls=[]
        def factory(allow):
            calls.append(allow)
            return wf.IncrementalCoreAllocator(self.app,self.source,allow_excluded=allow)
        with patch.object(wf.messagebox,'askyesno',return_value=False) as ask:
            self.assertIsNone(wf.open_allowing_excluded(None,'도면에서 코어배정',factory))
        self.assertIn('그래도 이 코어를 배정할까요?',ask.call_args[0][1]);self.assertEqual(calls,[False])
        calls.clear()
        with patch.object(wf.messagebox,'askyesno',return_value=True):
            service=wf.open_allowing_excluded(None,'도면에서 코어배정',factory)
        self.assertEqual(calls,[False,True]);self.assertEqual(service.core_id,'임시-900')

    def test_incremental_assignment_of_excluded_core_keeps_counts(self):
        before=self.report()
        service=wf.IncrementalCoreAllocator(self.app,self.source,allow_excluded=True)
        self.assertEqual(service.existing.get(self.ids['left']),1)
        p=service.preview({**service.existing,self.ids['direct']:5});service.apply(p)
        self.assertEqual(self.s.core(self.ids['direct'],5)['core_id'],'임시-900')
        self.assertEqual(self.report(),before)
        self.assertNotIn(service.key,wf.AfterRoutePlanner(self.app).context()['entries'])

    def test_manual_route_assignment_of_excluded_core(self):
        service=wf.ManualCoreAllocator(self.app,self.source,allow_excluded=True)
        p=service.preview({**service.existing,self.ids['direct']:7});service.apply(p)
        self.assertEqual(self.s.core(self.ids['direct'],7)['core_id'],'임시-900')
        self.assertEqual(wf.plan_settings(self.s)['route_step']['decisions'][service.key]['state'],'ok')

    def test_normal_target_core_is_unchanged(self):
        update(self.s,self.ids['left'],1,dict(core_id='CORE-1',signal='on'))
        service=wf.IncrementalCoreAllocator(self.app,self.source)
        self.assertFalse(service.allow_excluded);self.assertEqual(service.core_id,'CORE-1')


if __name__=='__main__':unittest.main(verbosity=2)
