"""V193: in an after drawing a core ID must not count 연결완료 when a 절단/철거
cable still carries it to an end facility (MDF/가입자/끝단) and the new live
route never reaches that facility (user case 54447717 9번, 9220085)."""
import tempfile
import unittest

from check_after_plan import wf,LocalApp,update

ID='9220085'


class CutTerminalRoute(unittest.TestCase):
    def build(self,replace):
        self.temp=tempfile.TemporaryDirectory();app=LocalApp(self.temp.name);s=self.s=app.store
        office=s.add_node('국사',0,0,'sub');a=s.add_node('함체A',200,0);other=s.add_node('다른끝',200,200,'sub')
        mdf=self.mdf=s.add_node('장량MDF',400,0,'sub')
        feed=s.add_cable(office,a,'FEED','144C','기설');old=self.old=s.add_cable(a,mdf,'54447717','12C','기설')
        update(s,feed,98,dict(core_id=ID,detail='MDF',signal='on'));update(s,old,9,dict(core_id=ID,detail='MDF',signal='on'))
        s.connect(a,(feed,98),(old,9))
        s.backup_to(app.scenario_path('before'))
        s.conn.execute('DELETE FROM splices');s.conn.commit()
        s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(old,));s.conn.commit()
        if replace:
            new=s.add_cable(a,mdf,'NEW','12C','신설');update(s,new,9,dict(core_id=ID,detail='MDF',signal='on'))
        else:
            new=s.add_cable(a,other,'NEW','12C','신설');update(s,new,9,dict(core_id=ID,detail='MDF',signal='on'))
        s.connect(a,(feed,98),(new,9))
        s.conn.commit()
        return feed,old,new

    def tearDown(self):self.s.close();self.temp.cleanup()

    def test_terminal_not_reached(self):
        feed,old,new=self.build(False)
        self.assertEqual(wf.completion_kind(self.s),'after')
        report=wf.completion_report(self.s);entry=report['by_id'][ID]
        self.assertFalse(entry['complete'],entry)
        self.assertIn('unconnected',entry['causes'])
        self.assertEqual(wf.core_completion_brief(self.s,(old,9))[0],'미완료')
        self.assertEqual(wf.core_completion_brief(self.s,(feed,98))[0],'미완료')
        self.assertIn('장량MDF',wf.core_completion_locations(self.s,(feed,98)))
        self.assertLess(report['done'],report['total'])
        print('PASS cut cable end facility not reached is incomplete')

    def test_replaced_route_complete(self):
        feed,old,new=self.build(True)
        # V197 (user choice): the old 절단 slot still ON and unspliced at 함체A
        # keeps the core 미완료 until it is reconnected or turned OFF.
        entry=wf.completion_report(self.s)['by_id'][ID]
        self.assertFalse(entry['complete'],entry)
        self.assertEqual(wf.core_completion_brief(self.s,(old,9))[0],'미완료')
        update(self.s,old,9,dict(signal='off'));self.s.conn.commit()
        entry=wf.completion_report(self.s)['by_id'][ID]
        self.assertTrue(entry['complete'],entry)
        print('PASS rerouted core is complete once the old cut slot is OFF')

    def test_cut_slot_unspliced_middle(self):
        # V197: a 절단 slot spliced on one side but open at a middle 함체.
        self.temp=tempfile.TemporaryDirectory();app=LocalApp(self.temp.name);s=self.s=app.store
        o=s.add_node('국사',0,0,'sub');a=s.add_node('A',100,0);b=s.add_node('B',200,0);m=s.add_node('MDF',300,0,'sub');z=s.add_node('Z',100,100)
        c1=s.add_cable(o,a,'C1','12C','기설');cut=s.add_cable(a,b,'CUT','12C','기설');c3=s.add_cable(a,m,'C3','12C','신설');c4=s.add_cable(b,z,'C4','12C','기설')
        for c in (c1,cut,c3):update(s,c,1,dict(core_id='77',detail='d',signal='on'))
        s.backup_to(app.scenario_path('before'))
        s.connect(a,(c1,1),(c3,1));s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(cut,));s.conn.commit()
        entry=wf.completion_report(s)['by_id']['77']
        self.assertFalse(entry['complete'],entry)
        self.assertEqual(wf.core_completion_brief(s,(cut,1))[0],'미완료')
        print('PASS cut slot open at both enclosures is incomplete')

    def test_cut_piece_spliced_to_route(self):
        # V195 (user 54303403 5/6/7/10/12): a cut slot still spliced to the
        # finished route is part of it, even if both enclosures are 끝단.
        self.temp=tempfile.TemporaryDirectory();app=LocalApp(self.temp.name);s=self.s=app.store
        hub=s.add_node('1744W742#3',0,0);s1=s.add_node('S1',100,-100);x=s.add_node('X513',200,0);w=s.add_node('W643',-200,0)
        cut=s.add_cable(hub,s1,'54303403','12C','기설');f=s.add_cable(hub,x,'144','144C','기설');s.add_cable(w,hub,'144b','144C','기설')
        update(s,cut,5,dict(core_id='10083276',detail='d',signal='on'));update(s,f,93,dict(core_id='10083276',detail='d',signal='on'))
        s.connect(hub,(cut,5),(f,93));s.backup_to(app.scenario_path('before'))
        s.conn.execute("UPDATE cables SET status='절단' WHERE id=?",(cut,))
        s.conn.execute("UPDATE nodes SET extra_json='{\"terminal\": true}' WHERE id IN (?,?)",(hub,s1));s.conn.commit()
        entry=wf.completion_report(self.s)['by_id']['10083276']
        self.assertTrue(entry['complete'],entry)
        self.assertEqual(wf.core_completion_brief(self.s,(cut,5))[0],'연결완료')
        print('PASS cut slot spliced to the finished route stays complete')


if __name__=='__main__':
    import sys
    import io
    stream=io.TextIOWrapper(sys.stderr.buffer,encoding='ascii',errors='backslashreplace',line_buffering=True)
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CutTerminalRoute))
    for test,trace in result.failures+result.errors:print('::error::'+ascii(str(test)+' '+trace.strip().splitlines()[-1]))
    sys.exit(0 if result.wasSuccessful() else 1)
