"""V181: a cable newly drawn in 후도면 but left in 「절단」 status is a retired
work marker, so its cores that share IDs with live cables are not counted on
the map's 미완료코어/미배정코어 badge. The cable window now explains why and
tells the user to switch it to 「신설」; as 신설 the badge appears."""
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

    def test_cut_cable_explained(self):
        new=self.build('절단')
        self.assertEqual(wf.completion_kind(self.s),'after')
        status,_=wf.core_completion_brief(self.s,(new,1))
        self.assertEqual(status,'미완료')
        self.assertEqual(self.badge(new),0)
        note=wf.after_cut_cable_note(self.s,new)
        self.assertIn('절단',note);self.assertIn('신설',note)
        print('PASS cut cable in after drawing explains missing badge')

    def test_new_cable_counts(self):
        new=self.build('신설')
        self.assertEqual(wf.after_cut_cable_note(self.s,new),'')
        self.assertGreater(self.badge(new),0)
        print('PASS 신설 cable in after drawing shows badge')


if __name__=='__main__':
    import sys
    import io
    stream=io.TextIOWrapper(sys.stderr.buffer,encoding='ascii',errors='backslashreplace',line_buffering=True)
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AfterCutCableNote))
    for test,trace in result.failures+result.errors:print('::error::'+ascii(str(test)+' '+trace.strip().splitlines()[-1]))
    sys.exit(0 if result.wasSuccessful() else 1)
