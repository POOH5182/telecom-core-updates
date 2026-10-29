"""V174: a 임시코어 assigned cable by cable in 도면에서 코어배정 becomes one joined
core (no separate 구간 1/구간 4 pieces); earlier unjoined pieces join on a plain
save (the save question itself is V173, check_save_confirm.py)."""
import tempfile
import unittest

from check_after_plan import wf,LocalApp,update


def drawing(app):
    s=app.store
    n=[s.add_node('함체 '+str(i),i*200,100) for i in range(5)]
    s.backup_to(app.scenario_path('before'))
    c=[s.add_cable(n[i],n[i+1],'NEW'+str(i+1),'72C','신설') for i in range(4)]
    update(s,c[0],5,dict(core_id='임시-78',detail='임시 회선',signal='on'))
    return n,c


def splice_count(s):return s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0]


class TemporaryAllocationJoin(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store
        self.n,self.c=drawing(self.app)
    def tearDown(self):self.s.close();self.temp.cleanup()

    def service(self):return wf.IncrementalCoreAllocator(self.app,(self.c[0],5),allow_excluded=True)

    def one_route(self):
        model=wf.core_connection_highlight(self.s,[(self.c[0],5)])
        self.assertEqual(len(model['groups']),1,[g['slots'] for g in model['groups']])
        self.assertFalse([b for b in model['boundaries'] if b['kind'] in ('pair','ambiguous')])

    def test_piece_by_piece_assignment_joins(self):
        numbers=(5,37,37)
        for cable,number in zip(self.c[1:],numbers):
            service=self.service();p=service.preview({**service.existing,cable:number})
            self.assertTrue(p['added'],cable);service.apply(p)
        self.assertEqual(splice_count(self.s),3)
        self.one_route()

    def test_existing_separate_pieces_join_on_plain_save(self):
        # Pieces saved by an older version: same 임시 ID, no splice between them.
        for cable,number in zip(self.c[1:],(5,37,37)):update(self.s,cable,number,dict(core_id='임시-78',detail='임시 회선',signal='on'))
        model=wf.core_connection_highlight(self.s,[(self.c[0],5)])
        self.assertEqual(len(model['groups']),4)
        self.assertTrue([b for b in model['boundaries'] if b['kind']=='pair'])
        service=self.service();p=service.preview(dict(service.existing))
        self.assertFalse(p['new']);self.assertEqual(len(p['added']),3)
        service.apply(p);self.one_route()
        with self.assertRaises(ValueError):self.service().preview(dict(self.service().existing))

    def test_other_temporary_ids_are_not_joined(self):
        update(self.s,self.c[1],5,dict(core_id='임시-90',detail='다른 임시',signal='on'))
        update(self.s,self.c[2],5,dict(core_id='임시-90',detail='다른 임시',signal='on'))
        service=self.service();p=service.preview({**service.existing,self.c[1]:6})
        self.assertEqual(p['added'],{wf.allocation_pair(self.n[1],(self.c[0],5),(self.c[1],6))})
        service.apply(p)
        self.assertEqual(splice_count(self.s),1)
        # Plain after-drawing auto join still ignores 임시 IDs.
        self.assertFalse(wf.after_auto_pairs(self.s))

    def test_real_id_behaviour_unchanged(self):
        update(self.s,self.c[0],5,dict(core_id='CORE-1',signal='on'))
        update(self.s,self.c[1],5,dict(core_id='CORE-1',signal='on'))
        service=wf.IncrementalCoreAllocator(self.app,(self.c[0],5))
        with self.assertRaises(ValueError):service.preview(dict(service.existing))



if __name__=='__main__':unittest.main(verbosity=2)
