"""V190: 함체 코어내역 V2 - connected cores at one enclosure shown as two-line
pairs (A 방향 / B 방향 = enclosure on the other side), V191: one line per
direction, blank line between pairs, copied to Excel as tab separated text."""
import tempfile
import tkinter as tk
import unittest

from check_after_plan import LocalApp,update,code


class NodePairSummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);s=self.s=self.app.store
        a=s.add_node('A',0,0);self.h=s.add_node('H',100,0);b=s.add_node('B',200,0);c=s.add_node('C',100,100);d=s.add_node('D',0,100)
        self.x559=s.add_cable(a,self.h,'1123x559','48C','기설');self.d772=s.add_cable(self.h,b,'1123d772','48C','기설')
        self.x992=s.add_cable(c,self.h,'1123x992','48C','기설');self.d333=s.add_cable(self.h,d,'1123d333','48C','기설')
        for i,(l,r) in enumerate(zip((1,2,3,4,5,6,7),(7,8,9,10,11,12,13))):
            update(s,self.x559,l,dict(core_id=f'P{i}'));update(s,self.d772,r,dict(core_id=f'P{i}'))
            s.connect(self.h,(self.d772,r),(self.x559,l))   # reversed order on purpose
        for i,(l,r) in enumerate(zip((13,14,17,16,22,23),(1,2,3,4,5,6))):
            update(s,self.x992,l,dict(core_id=f'Q{i}'));update(s,self.d333,r,dict(core_id=f'Q{i}'))
            s.connect(self.h,(self.x992,l),(self.d333,r))
    def tearDown(self):self.s.close();self.temp.cleanup()

    def test_groups_and_grid(self):
        groups=code['node_pair_groups'](self.s,self.h)
        # V191: direction = the enclosure on the other side, not the cable ID
        self.assertEqual([(g['a_label'],g['b_label']) for g in groups],[('A','B'),('C','D')])
        self.assertEqual(groups[0]['pairs'],[(1,7),(2,8),(3,9),(4,10),(5,11),(6,12),(7,13)])
        cells=[c for _,c in code['node_pair_grid'](groups)]
        # V191: one direction on one line, its name only once
        self.assertEqual(cells[0],['A 방향',1,2,3,4,5,6,7]);self.assertEqual(cells[1],['B 방향',7,8,9,10,11,12,13])
        self.assertEqual(cells[2],[]);self.assertEqual(len(cells),5)
        self.assertEqual(cells[3],['C 방향',13,14,16,17,22,23]);self.assertEqual(cells[4],['D 방향',1,2,4,3,5,6])
        self.assertEqual(sum(1 for c in cells if c and c[0]=='A 방향'),1)
        key=groups[1]['key']
        cells=[c for _,c in code['node_pair_grid'](groups,sort_bottom={key})]
        self.assertEqual(cells[3],['C 방향',13,14,17,16,22,23]);self.assertEqual(cells[4],['D 방향',1,2,3,4,5,6])
        cells=[c for _,c in code['node_pair_grid'](groups,swapped={key})]
        self.assertEqual(cells[3],['D 방향',1,2,3,4,5,6]);self.assertEqual(cells[4],['C 방향',13,14,17,16,22,23])
        tsv=code['node_pair_tsv'](code['node_pair_grid'](groups))
        lines=tsv.split('\n')
        self.assertEqual(lines[0],'A 방향\t1\t2\t3\t4\t5\t6\t7');self.assertEqual(lines[2],'');self.assertEqual(lines[3],'C 방향\t13\t14\t16\t17\t22\t23')
        self.assertEqual(code['node_pair_grid']([]),[])

    def test_dialog(self):
        try:root=tk.Tk()
        except tk.TclError:self.skipTest('no display');return
        root.withdraw()
        try:
            class Parent(tk.Toplevel):
                def reload_all(self):pass
            parent=Parent(root);parent.parent=type('P',(),{'refresh':lambda _:None})()
            dialog=code['NodePairSummaryDialog'](parent,self.s,self.h)
            kids=dialog.tree.get_children()
            self.assertEqual(len(kids),5);self.assertEqual(len(dialog.tree['columns']),8)
            self.assertEqual(dialog.tree.item(kids[0],'values')[:3],('A 방향','1','2'))
            dialog.copy_all();text=dialog.clipboard_get()
            self.assertTrue(text.startswith('A 방향\t1\t2\t3\t4\t5\t6\t7\nB 방향\t7'),text)
            dialog.tree.selection_set(kids[3]);dialog.copy_selected()
            self.assertTrue(dialog.clipboard_get().startswith('C 방향\t13'))
            dialog.destroy();parent.destroy()
        finally:root.destroy()


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=1).result
    if result.wasSuccessful():print('PASS node pair summary V2 (V191)')
    else:print('::error::node pair summary V2 check failed');raise SystemExit(1)
