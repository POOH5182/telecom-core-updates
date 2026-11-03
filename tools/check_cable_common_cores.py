"""V203: Ctrl+click two cables -> list the cores both cables carry (same core
ID), with each cable's own number side by side, plus an Excel copy."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_field_survey import code,wf
from check_field_slots import ScenarioHarness


class FakeDialog:
    made=[]
    def __init__(self,parent,store,a,b):
        self.store=store;self.alive=True;FakeDialog.made.append(self);self.show(a,b)
    def show(self,a,b):self.pair=(a,b);self.model=wf.cable_common_cores(self.store,a,b)
    def winfo_exists(self):return self.alive
    def lift(self):pass


class CableCommonCores(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();s=self.s=code['Store'](Path(self.temp.name)/'w.sqlite3')
        a=s.add_node('MDF',0,0);j=s.add_node('함체 J',240,0);x=s.add_node('함체 X',480,0)
        self.f=s.add_cable(a,j,'F','24C','기설');self.d=s.add_cable(j,x,'D','12C','기설');self.e=s.add_cable(j,x,'E','12C','기설')
        for i,cid in ((12,'CORE-1'),(3,'CORE-2'),(5,'CORE-3'),(7,'임시-1'),(8,'ONLY-F')):
            s.update_core(self.f,i,(cid,'F내역','normal','','on'))
        for i,cid in ((5,'CORE-1'),(3,'core-2'),(9,'CORE-3'),(2,'임시-2'),(4,'임시-1'),(6,'ONLY-D')):
            s.update_core(self.d,i,(cid,'D내역','normal','','on'))
    def tearDown(self):self.s.close();self.temp.cleanup()

    def test_common_rows_show_both_numbers(self):
        before=self.s.data_revision()
        m=wf.cable_common_cores(self.s,self.f,self.d)
        got=[(r['core_id'],r['a_number'],r['b_number']) for r in m['rows']]
        self.assertEqual(got,[('CORE-2',3,3),('CORE-3',5,9),('임시-1',7,4),('CORE-1',12,5)],got)
        self.assertEqual(m['count'],4);self.assertIn('겹치는 코어 4개',m['summary']);self.assertIn('같은 번호 1개',m['summary'])
        self.assertEqual(m['rows'][0]['a_detail'],'F내역');self.assertEqual(m['rows'][0]['b_detail'],'D내역')
        self.assertTrue(m['label_a'].startswith('F'),m['label_a']);self.assertIn('MDF',m['label_a'])
        self.assertEqual(self.s.data_revision(),before)
        empty=wf.cable_common_cores(self.s,self.f,self.e)
        self.assertEqual(empty['rows'],[]);self.assertEqual(empty['count'],0)
        print('PASS common cores list both cable numbers')

    def test_ctrl_click_pair_opens_and_reuses_window(self):
        app=ScenarioHarness(self.s);FakeDialog.made=[]
        with patch.dict(code['App'].open_common_cores.__globals__,{'CommonCoresDialog':FakeDialog}):
            app.selected={self.f};self.assertIsNone(app.open_common_cores())
            app.selected={self.f,self.d};app._active_cable=self.d
            dialog=app.open_common_cores()
            self.assertEqual(dialog.pair,(self.f,self.d))
            self.assertEqual(len(dialog.model['rows']),4)
            app.selected={self.f,self.e,self.d};self.assertIsNone(app.open_common_cores())
            app.selected={self.d,self.e};app._active_cable=self.e
            again=app.open_common_cores()
            self.assertIs(again,dialog);self.assertEqual(again.pair,(self.d,self.e));self.assertEqual(len(FakeDialog.made),1)
        names=code['App'].click.__code__.co_names
        self.assertIn('open_common_cores',names)
        import inspect
        self.assertIn('self.open_common_cores(pair)',inspect.getsource(code['App'].show_status_menu))
        print('PASS ctrl+click two cables opens one reused common-cores window')

    def test_dialog_copy_text(self):
        source=code['CommonCoresDialog'].copy_rows.__code__.co_consts
        self.assertTrue(any('A 번호' in str(c) for c in source))
        print('PASS common cores dialog copies an Excel table')


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=1).result
    if not result.wasSuccessful():print('::error::cable common cores check failed');raise SystemExit(1)
