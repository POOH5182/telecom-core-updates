"""V183: a 절단 cable in 후도면 (e.g. NEW10 drawn there) shows 「미완료코어 N」
on the map for the same rows its cable window marks [미완료코어], even when
the ID also lives on active cables. 신설 cables keep their badge."""
from pathlib import Path
import tempfile
import unittest

from check_after_plan import wf,LocalApp,update

ID='3061838318'


class AfterCutCableNote(unittest.TestCase):
    def build(self,status):
        self.temp=tempfile.TemporaryDirectory();app=LocalApp(self.temp.name);s=self.s=app.store
        n=[s.add_node('함체 '+str(i),i*200,100) for i in range(3)]
        old=s.add_cable(n[0],n[1],'OLD','36C','기설')
        update(s,old,1,dict(core_id=ID,detail='기존',signal='on'))
        s.backup_to(app.scenario_path('before'))
        new=s.add_cable(n[1],n[2],'NEW10','36C',status)
        update(s,new,1,dict(core_id=ID,detail='신규',signal='on'))
        return new

    def tearDown(self):self.s.close();self.temp.cleanup()

    def badge(self,cid):
        w=self.s.cable_core_warning_summary()[cid]
        return w['unassigned']+w['incomplete_badge']

    def test_cut_cable_counts(self):
        new=self.build('절단')
        self.assertEqual(wf.completion_kind(self.s),'after')
        status,_=wf.core_completion_brief(self.s,(new,1))
        self.assertEqual(status,'미완료')
        w=self.s.cable_core_warning_summary()[new]
        self.assertEqual(w['incomplete_badge'],1,w)
        self.assertTrue(any(e.get('slot')==(new,1) for e in self.s._incomplete_entries))
        print('PASS cut cable in after drawing shows its incomplete cores')

    def test_new_cable_counts(self):
        new=self.build('신설')
        self.assertGreater(self.badge(new),0)
        print('PASS new (sinseol) cable in after drawing shows badge')


if __name__=='__main__':
    import sys
    import io
    stream=io.TextIOWrapper(sys.stderr.buffer,encoding='ascii',errors='backslashreplace',line_buffering=True)
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AfterCutCableNote))
    for test,trace in result.failures+result.errors:print('::error::'+ascii(str(test)+' '+trace.strip().splitlines()[-1]))
    sys.exit(0 if result.wasSuccessful() else 1)
