"""V194: in an after drawing, deleting a number marks its splice partners
「자동접속 제외」. Once the edit history no longer holds that deletion (reopen,
import, 100+ edits) re-assigning the number left the route split
(user case 3062483833: 62 / 111 / 10번, 함체 배정필요 2 · 연결대기 2).
Re-assigning must rejoin the deletion-marked partners, never an explicit
disconnect."""
import json
import tempfile
import unittest

from check_after_plan import wf,LocalApp,update

ID='3062483833'


class ReassignRejoin(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=app=LocalApp(self.temp.name);s=self.s=app.store
        a=s.add_node('JB742',0,0);h1=s.add_node('W562',100,0);self.h2=h2=s.add_node('W643#2',200,0)
        self.h3=h3=s.add_node('W742#3',300,0);b=s.add_node('W742#4',300,100)
        self.L1=s.add_cable(a,h1,'L1','144C','신설');self.L2=s.add_cable(h1,h2,'L2','144C','신설')
        self.M=s.add_cable(h2,h3,'M','144C','신설');self.R=s.add_cable(h3,b,'R','72C','기설')
        for c,i in ((self.L1,62),(self.L2,62),(self.M,111),(self.R,10)):update(s,c,i,dict(core_id=ID,signal='on'))
        s.connect(h1,(self.L1,62),(self.L2,62));s.connect(h2,(self.L2,62),(self.M,111));s.connect(h3,(self.M,111),(self.R,10))
        wf.after_auto_activate(s)
        self.assertTrue(self.complete())
    def tearDown(self):self.s.close();self.temp.cleanup()
    def complete(self):return wf.completion_report(self.s)['by_id'][ID]['complete']
    def splices(self):return self.s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0]
    def forget_history(self):
        self.s.conn.execute('DELETE FROM history_events');self.s.conn.execute('DELETE FROM history_groups');self.s.conn.commit()
    def delete_middle(self):
        self.s.delete_core_assignment(self.M,111);self.assertEqual(self.splices(),1);self.forget_history()
        self.assertFalse(self.complete())
        self.assertTrue(self.s.node_assignment_needs(self.h2))
    def extra(self,nid):return json.loads(self.s.node(nid)['extra_json'] or '{}')

    def test_typed_id_rejoins_after_history_is_gone(self):
        self.delete_middle()
        self.assertIn(f'{self.L2}::62',self.extra(self.h2)['autoSameNumberDeleted'])
        update(self.s,self.M,111,dict(core_id=ID,signal='on'))
        self.assertEqual(self.splices(),3);self.assertTrue(self.complete())
        self.assertEqual(self.s.node_assignment_needs(self.h2),{});self.assertEqual(self.s.node_assignment_needs(self.h3),{})
        for nid in (self.h2,self.h3):self.assertNotIn('autoSameNumberExcluded',self.extra(nid))
        self.s.undo();self.assertEqual(self.splices(),1)
        self.assertIn(f'{self.R}::10',self.extra(self.h3)['autoSameNumberExcluded'])
        print('PASS typed re-assignment rejoins deletion-marked partners (undo restores)')

    def test_core_assignment_rejoins_after_history_is_gone(self):
        self.delete_middle()
        service=wf.IncrementalCoreAllocator(self.app,(self.L2,62));p=service.preview({self.M:111})
        self.assertEqual(len(p['added']),2);service.apply(p)
        self.assertEqual(self.splices(),3);self.assertTrue(self.complete())
        for nid in (self.h2,self.h3):self.assertFalse(self.extra(nid).get('autoSameNumberExcluded'))
        print('PASS cable core assignment rejoins deletion-marked partners')

    def test_explicit_partner_disconnect_stays_protected(self):
        s=self.s;s.disconnect(self.h3,self.R,10)
        self.assertNotIn(f'{self.R}::10',self.extra(self.h3).get('autoSameNumberDeleted',()))
        self.delete_middle()
        self.assertNotIn(f'{self.R}::10',self.extra(self.h3).get('autoSameNumberDeleted',()))
        update(s,self.M,111,dict(core_id=ID,signal='on'))
        self.assertIsNotNone(s.splice_for(self.h2,self.M,111));self.assertIsNone(s.splice_for(self.h3,self.M,111))
        self.assertIn(f'{self.R}::10',self.extra(self.h3)['autoSameNumberExcluded'])
        print('PASS an explicit disconnect on the partner is never released')

    def test_locked_facility_keeps_records(self):
        self.delete_middle()
        extra=self.extra(self.h3);extra['editLocked']=True
        self.s.conn.execute('UPDATE nodes SET extra_json=? WHERE id=?',(json.dumps(extra),self.h3));self.s.conn.commit()
        self.assertTrue(wf.node_locked(self.s,self.h3))
        released=wf.after_reassign_release(self.s,(self.M,111),ID)
        self.assertIn(f'{self.R}::10',self.extra(self.h3)['autoSameNumberExcluded'])
        self.assertEqual(released,2);self.assertNotIn('autoSameNumberExcluded',self.extra(self.h2))
        print('PASS locked facility keeps its exclusion records')


if __name__=='__main__':
    import sys
    import io
    stream=io.TextIOWrapper(sys.stderr.buffer,encoding='ascii',errors='backslashreplace',line_buffering=True)
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReassignRejoin))
    for test,trace in result.failures+result.errors:print('::error::'+ascii(str(test)+' '+trace.strip().splitlines()[-1]))
    sys.exit(0 if result.wasSuccessful() else 1)
