"""V178: a 임시 core with no ON signal may stop at any enclosure without NOT OK."""
from pathlib import Path
import sys
import tempfile
import unittest

from check_field_survey import code,wf


class TemporaryNotOkTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();home=Path(self.temp.name)
        s=self.s=code['Store'](home/'field.sqlite3')
        s.conn.execute("INSERT INTO meta VALUES('active_scenario','before')")
        s.conn.execute("INSERT OR REPLACE INTO meta VALUES('field_identity_policy',?)",(wf.FIELD_SLOT_POLICY,));s.conn.commit()
        self.nodes=[s.add_node(name,i*240,0) for i,name in enumerate(('끝 A','함체 1','함체 2','끝 B'))]
        self.cables=[s.add_cable(self.nodes[i],self.nodes[i+1],name,'6C','기설') for i,name in enumerate(('A','B','C'))]
        # 임시 core passes 함체 1 only and stops (free) inside 함체 2.
        for cable in self.cables[:2]:s.update_core(cable,1,('임시-7','','normal','',''))
        s.connect(self.nodes[1],(self.cables[0],1),(self.cables[1],1))
        self.assertTrue(wf.field_slot_mode(s))
    def tearDown(self):self.s.close();self.temp.cleanup()

    def local(self,node):
        self.s._field_display_cache={};return wf.field_local_summary(self.s,self.nodes[node])

    def test_unconfirmed_temporary_free_end_is_not_not_ok(self):
        self.assertEqual(self.local(2)['not_ok'],0)
        self.assertEqual(self.local(1)['not_ok'],0)
        self.assertNotIn('NOT OK',set(wf.field_local_slots(self.s,self.nodes[2]).values()))
        for signal in ('unknown','확인필요'):
            self.s.conn.execute('UPDATE cores SET signal=? WHERE cable_id=? AND core_index=1',(signal,self.cables[1]));self.s.conn.commit()
            self.assertEqual(self.local(2)['not_ok'],0,signal)

    def test_on_signal_or_real_id_still_reports_not_ok(self):
        self.s.conn.execute("UPDATE cores SET signal='on' WHERE core_index=1 AND cable_id IN (?,?)",tuple(self.cables[:2]));self.s.conn.commit()
        self.assertEqual(self.local(2)['not_ok'],1)
        self.s.conn.execute("UPDATE cores SET signal='',core_id='REAL-1' WHERE core_index=1 AND cable_id IN (?,?)",tuple(self.cables[:2]));self.s.conn.commit()
        self.assertEqual(self.local(2)['not_ok'],1)

    def test_badge_hides_zero_not_ok(self):
        rows=code['node_badge_rows']({'count':0,'field_local':{'ok':3,'not_ok':0,'total':3}})
        self.assertEqual([r[0] for r in rows],['OK 3'])
        rows=code['node_badge_rows']({'count':0,'field_local':{'ok':3,'not_ok':2,'total':5}})
        self.assertEqual([r[0] for r in rows],['OK 3','NOT OK 2'])


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=2).result
    for case,trace in result.failures+result.errors:print('::error::'+str(case)+' '+trace.splitlines()[-1])
    if not result.wasSuccessful():sys.exit(1)
    print('PASS check_temporary_not_ok')
