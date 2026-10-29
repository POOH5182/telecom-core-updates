"""V179: typing 임시코어N on a real core uses exactly that number."""
from pathlib import Path
import sys
import tempfile
import unittest

from check_field_survey import code,wf


class TemporaryTypedIdTests(unittest.TestCase):
    def make(self,kind,field):
        self.temp=tempfile.TemporaryDirectory();s=self.s=code['Store'](Path(self.temp.name)/'x.sqlite3')
        s.conn.execute("INSERT INTO meta VALUES('active_scenario',?)",(kind,))
        if field:s.conn.execute("INSERT OR REPLACE INTO meta VALUES('field_identity_policy',?)",(wf.FIELD_SLOT_POLICY,))
        s.conn.commit()
        self.nodes=[s.add_node(name,i*240,0) for i,name in enumerate(('A','B','C'))]
        self.cables=[s.add_cable(self.nodes[i],self.nodes[i+1],name,'6C','기설') for i,name in enumerate(('P','Q'))]
        for cable in self.cables:s.update_core(cable,1,('1231444','회선','normal','',''))
        s.connect(self.nodes[1],(self.cables[0],1),(self.cables[1],1))
        s.update_core(self.cables[0],3,('임시-5','','normal','',''))
        return s
    def tearDown(self):
        if hasattr(self,"s"):self.s.close();self.temp.cleanup();del self.s

    def ids(self):return [str(self.s.core(c,1)['core_id']) for c in self.cables]

    def test_normalize_keeps_typed_number(self):
        norm=code['normalize_core_id_input']
        for typed in ('임시코어123','임시코어 123','임시 코어123','임시123','임시-123',' 임시코어123 '):
            self.assertEqual(norm(typed),'임시-123',typed)
        self.assertEqual(norm('1231444'),'1231444');self.assertEqual(norm('임시코어'),'임시코어')
        self.assertEqual(wf.rn_identity_value('임시 코어 77'),'임시-77');self.assertEqual(wf.rn_identity_value('임시77'),'임시-77')

    def test_real_core_renamed_to_typed_temporary_number(self):
        for kind in ('before','after'):
            with self.subTest(kind=kind):
                s=self.make(kind,False);seq=s.conn.execute("SELECT value FROM meta WHERE key='temp_core_seq'").fetchone()
                applied,unchanged,errors=s.apply_core_identity_changes(self.cables[1],[(1,'임시코어123','회선')])
                self.assertEqual((applied,errors),([1],[]))
                # The connected real route becomes 임시-123; no other number is invented.
                self.assertEqual(self.ids(),['임시-123','임시-123'])
                self.assertEqual(s.conn.execute("SELECT value FROM meta WHERE key='temp_core_seq'").fetchone(),seq)
                self.assertEqual(s.core(self.cables[0],3)['core_id'],'임시-5')
                self.tearDown()
        self.make('before',False)

    def test_field_drawing_changes_only_that_number(self):
        s=self.make('before',True)
        applied,unchanged,errors=s.apply_core_identity_changes(self.cables[1],[(1,'임시 123','')])
        self.assertEqual((applied,errors),([1],[]));self.assertEqual(self.ids(),['1231444','임시-123'])

    def test_existing_temporary_number_is_reported(self):
        s=self.make('after',False)
        self.assertEqual(s.temporary_identity_conflicts(self.cables[1],[(1,'임시코어124')]),[])
        notes=s.temporary_identity_conflicts(self.cables[1],[(1,'임시코어5')])
        self.assertEqual(len(notes),1);self.assertIn('임시코어5',notes[0]);self.assertIn('1곳',notes[0])
        # Still applied when the user says yes: same name = same core.
        s.apply_core_identity_changes(self.cables[1],[(1,'임시코어5','')])
        self.assertEqual(self.ids(),['임시-5','임시-5'])
        self.assertEqual(s.temporary_identity_conflicts(self.cables[1],[(1,'임시코어5')]),[])

    def test_other_real_id_still_refused(self):
        s=self.make('after',False)
        applied,unchanged,errors=s.apply_core_identity_changes(self.cables[1],[(1,'999','')])
        self.assertEqual(applied,[]);self.assertEqual(len(errors),1);self.assertEqual(self.ids(),['1231444','1231444'])

    def test_ui_wires_confirmation(self):
        source=(Path(__file__).resolve().parents[1]/'app'/'telecom_core_app.pyw').read_text(encoding='utf-8')
        self.assertGreaterEqual(source.count('confirm_temporary_identity(self,self.store'),3)
        self.make('before',False)


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=2).result
    for case,trace in result.failures+result.errors:print('::error::'+str(case)+' '+trace.splitlines()[-1])
    if not result.wasSuccessful():sys.exit(1)
    print('PASS check_temporary_typed_id')
