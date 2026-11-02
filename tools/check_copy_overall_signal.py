"""V198: 「코어내역 전체복사」 writes each core's overall signal (any ON on the
same core ID / 임시코어 elsewhere -> ON). Copy output only: stored signals stay."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from check_field_survey import code,wf


class CopyOverallSignalTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();s=self.s=code['Store'](Path(self.temp.name)/'w.sqlite3')
        self.nodes=[s.add_node(n,i*200,0) for i,n in enumerate(('A','B','C'))]
        self.cables=[s.add_cable(self.nodes[i],self.nodes[i+1],n,'6C','기설') for i,n in enumerate(('X','Y'))]
        x,y=self.cables
        s.update_core(x,1,('CORE-ON','내역1','normal','','unknown'));s.update_core(y,1,('CORE-ON','내역1','normal','','on'))
        s.update_core(x,2,('임시-7','','normal','','unknown'));s.update_core(y,2,('임시-7','','normal','','on'))
        s.update_core(x,3,('CORE-OFF','','normal','','unknown'));s.update_core(y,3,('CORE-OFF','','normal','','off'))
        s.update_core(x,4,('CORE-UNK','','normal','','unknown'))
        s.update_core(x,5,('CORE-MIX','','normal','','exception'));s.update_core(y,5,('CORE-MIX','','normal','','off'))
        s.update_core(x,6,('','','','','off'))
        # Stored signals per position (a same-ID edit would copy one signal to all).
        for cable,index,signal in ((x,1,'unknown'),(y,1,'on'),(x,2,'unknown'),(y,2,'on'),(x,3,'unknown'),(y,3,'off'),(x,4,'unknown'),(x,5,'exception'),(y,5,'off')):
            s.conn.execute('UPDATE cores SET signal=? WHERE cable_id=? AND core_index=?',(signal,cable,index))
        s.conn.commit()
    def tearDown(self):self.s.close();self.temp.cleanup()

    def labels(self):
        x=self.cables[0];return {int(r['core_index']):wf.core_copy_signal_label(self.s,r) for r in self.s.cores(x)}

    def test_overall_signal_any_on_wins(self):
        before=[tuple(r) for r in self.s.conn.execute('SELECT cable_id,core_index,signal FROM cores ORDER BY 1,2')]
        got=self.labels()
        self.assertEqual(got[1],'ON');self.assertEqual(got[2],'ON')
        self.assertEqual(got[3],'OFF');self.assertEqual(got[4],'확인필요')
        self.assertEqual(got[5],'예외');self.assertEqual(got[6],'OFF')
        after=[tuple(r) for r in self.s.conn.execute('SELECT cable_id,core_index,signal FROM cores ORDER BY 1,2')]
        self.assertEqual(before,after)

    def test_both_copy_buttons_use_overall_signal(self):
        for name in ('CableDialog','_LegacyCableDialog'):
            fake=Mock();fake.store=self.s;fake.cable_key=self.cables[0];fake.status_annotation=lambda r:'';clip=[]
            fake.clipboard_append=clip.append
            code[name].__dict__['copy_details'](fake)
            lines=clip[0].split('\n');row1=lines[1].split('\t');row2=lines[2].split('\t')
            self.assertEqual(row1[2],'ON',name);self.assertEqual(row2[2],'ON',name)
            self.assertEqual(self.s.core(self.cables[0],1)['signal'],'unknown')


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=1).result
    if result.failures or result.errors:print('::error::check_copy_overall_signal failed');raise SystemExit(1)
    print('PASS copy overall signal')
