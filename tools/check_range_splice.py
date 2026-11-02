"""V189: 번호 범위 직결 - in an enclosure, splice only the numbers start..end
of two cables (e.g. 1~30 or 6~30). Numbers already connected here,
해지/끊김 numbers and (optionally) empty numbers are skipped; different real
core IDs are refused; one Ctrl+Z undoes the whole range."""
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import wf,LocalApp,update,code


class RangeSpliceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);s=self.s=self.app.store
        a=s.add_node('A',0,0);self.h=s.add_node('H',100,0);b=s.add_node('B',200,0)
        self.left=s.add_cable(a,self.h,'LEFT','48C','기설');self.right=s.add_cable(self.h,b,'RIGHT','48C','기설')
        update(s,self.left,6,dict(core_id='CORE-6',detail='six'))
        update(s,self.left,7,dict(core_id='CORE-7'));update(s,self.right,7,dict(core_id='OTHER-7'))
        update(s,self.left,8,dict(core_id='CORE-8',status1='cancel'))
        update(s,self.left,9,dict(core_id='CORE-9'));update(s,self.right,10,dict(core_id='CORE-9'))
        s.connect(self.h,(self.left,9),(self.right,10))
        update(s,self.left,12,dict(core_id='CORE-12'));update(s,self.right,12,dict(core_id='CORE-12'))
        s.connect(self.h,(self.left,12),(self.right,12))
    def tearDown(self):self.s.close();self.temp.cleanup()
    def links(self):
        return sorted((r['core1_index'],r['core2_index']) for r in self.s.conn.execute('SELECT * FROM splices WHERE node_id=?',(self.h,)))

    def test_plan_and_skips(self):
        targets,skipped=self.s.range_splice_plan(self.h,self.left,self.right,30,6)
        reasons=dict(skipped)
        self.assertEqual(reasons[8],'해지·끊김 상태');self.assertEqual(reasons[9],'이 함체에서 이미 다른 번호와 연결')
        self.assertEqual(reasons[10],'이 함체에서 이미 다른 번호와 연결');self.assertEqual(reasons[12],'이미 직결됨')
        self.assertEqual(targets[0],6);self.assertEqual(targets[-1],30);self.assertNotIn(5,targets);self.assertNotIn(31,targets)
        used,_=self.s.range_splice_plan(self.h,self.left,self.right,1,30,False)
        self.assertEqual(used,[6,7])
        with self.assertRaisesRegex(ValueError,'1~48'):self.s.range_splice_plan(self.h,self.left,self.right,0,30)
        with self.assertRaisesRegex(ValueError,'1~48'):self.s.range_splice_plan(self.h,self.left,self.right,1,49)

    def test_splice_range_then_undo(self):
        before=self.links()
        ok,errors=self.s.full_splice(self.h,self.left,self.right,False,6,30)
        self.assertEqual(ok,30-6+1-1-4)  # 25 numbers, minus 7 (ID conflict), 8,9,10,12 skipped
        self.assertTrue(any(e.startswith('7번') for e in errors),errors)
        links=self.links()
        for idx in (6,11,13,30):self.assertIn((idx,idx),links)
        for idx in (1,5,7,8,31,48):self.assertNotIn((idx,idx),links)
        self.assertEqual(self.s.core(self.right,6)['core_id'],'CORE-6')
        self.assertTrue(self.s.core(self.left,20)['core_id'].startswith('임시-'))
        self.s.undo();self.assertEqual(self.links(),before)
        self.assertEqual(self.s.core(self.right,6)['core_id'],'')

    def test_dialog_button_flow(self):
        calls={}
        class Fake:
            store=self.s;node_id=self.h;by_label={'L':self.left,'R':self.right}
            left_var=type('V',(),{'get':lambda _:'L'})();right_var=type('V',(),{'get':lambda _:'R'})()
            msg=type('M',(),{'set':lambda _,v:calls.__setitem__('msg',v)})()
            parent=type('P',(),{'refresh':lambda _:None})()
            def ensure_node_editable(s):return True
            def reload_all(s):pass
            def ask_splice_range(s,total):calls['total']=total;return (1,5,True)
        fake=Fake()
        def run_bulk(parent,store,method,args,**kw):return getattr(store,method)(*args)
        with patch.object(wf,'run_bulk',run_bulk),patch.object(code['messagebox'],'askyesno',return_value=True),\
             patch.object(code['messagebox'],'showwarning'),patch.object(code['messagebox'],'showinfo'):
            code['NodeDialog'].full_splice_range(fake)
        self.assertEqual(calls['total'],48);self.assertIn('1~5',calls['msg'])
        for idx in range(1,6):self.assertIn((idx,idx),self.links())
        self.assertNotIn((6,6),self.links())
        with patch.object(code['messagebox'],'askyesno',return_value=False) as ask:
            fake.ask_splice_range=lambda total:(1,5,True)
            with patch.object(code['messagebox'],'showinfo') as info:code['NodeDialog'].full_splice_range(fake)
            info.assert_called_once();ask.assert_not_called()  # 1~5 already done: nothing new


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=1).result
    if result.wasSuccessful():print('PASS range splice (V189)')
    else:print('::error::range splice check failed');raise SystemExit(1)
