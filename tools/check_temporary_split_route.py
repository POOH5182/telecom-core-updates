"""V172: a 임시코어 path split by a rebuilt cable shows every piece with the same 임시 ID."""
from pathlib import Path
import tempfile
import unittest
from check_field_survey import code,wf


def fixture(path,field,scenario='before'):
    s=code['Store'](path)
    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario',?)",(scenario,))
    if field:s.conn.execute("INSERT OR REPLACE INTO meta VALUES('field_identity_policy',?)",(wf.FIELD_SLOT_POLICY,))
    s.conn.commit()
    n=[s.add_node('합성 시설 '+str(i),i*180,0) for i in range(5)]
    # A-B are still spliced; C was rebuilt, so node 2 has no splice to it.
    c=[s.add_cable(n[i],n[i+1],chr(65+i),'6C','기설') for i in range(3)]
    other=s.add_cable(n[3],n[4],'D','6C','기설')
    with s.action('합성 끊어진 임시코어'):
        for x in c:s.conn.execute("UPDATE cores SET core_id='임시-15',detail='임시 내역',signal='on' WHERE cable_id=? AND core_index=1",(x,))
        s.conn.execute("UPDATE cores SET core_id='임시-16',detail='다른 임시',signal='on' WHERE cable_id=? AND core_index=1",(other,))
        a,b=sorted(((c[0],1),(c[1],1)));s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(n[1],*a,*b))
    return s,c,other


class TemporarySplitRoute(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
    def tearDown(self):self.s.close();self.temp.cleanup()

    def check_mode(self,field,scenario='before'):
        self.s,c,other=fixture(self.home/(scenario+('f' if field else 'p')+'.sqlite3'),field,scenario)
        splices=self.s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0]
        for seed in ((c[0],1),(c[2],1)):
            model=wf.core_connection_highlight(self.s,[seed])
            self.assertEqual(set(model['colors']),set(c),seed)
            self.assertNotIn(other,model['colors'])
            self.assertEqual(len(model['groups']),2)
            self.assertEqual(sum(g['selected'] for g in model['groups']),1)
            trace=wf.field_core_trace(self.s,'임시-15',slot=seed)
            self.assertEqual({r['cable_id'] for r in trace['rows']},set(c))
        # Display only: nothing is joined or written.
        self.assertEqual(self.s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0],splices)
        model=wf.core_connection_highlight(self.s,[(other,1)])
        self.assertEqual(set(model['colors']),{other})

    def test_field_slot_drawing(self):self.check_mode(True)
    def test_plain_drawing(self):self.check_mode(False)
    def test_after_drawing(self):self.check_mode(False,'after')


if __name__=='__main__':
    unittest.main()
