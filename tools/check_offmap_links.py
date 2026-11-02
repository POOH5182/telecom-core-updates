"""V187: 「도면 밖 연결」 marks two free ends of one core ID in an after drawing
as really joined through an undrawn section. The core then counts as one
route, but the mark is re-checked: a different core ID, OFF/error, a removed
number or a new splice at a marked end brings back 「도면 밖 연결 불일치」."""
from pathlib import Path
import tempfile
import unittest

from check_after_plan import wf,LocalApp,update

CID='3061686251'


def drawing(app):
    s=app.store
    n=[s.add_node('함체 '+str(i),i*200,100) for i in range(4)]
    s.backup_to(app.scenario_path('before'))
    # n1..n2 is the part that is not drawn.
    c=[s.add_cable(n[0],n[1],'NEW1','144C','신설'),s.add_cable(n[2],n[3],'NEW1','144C','신설')]
    for i in (1,2):s.add_cable(n[i],s.add_node('옆 '+str(i),i*200,300),'X'+str(i),'12C','기설')
    for cable in c:update(s,cable,81,dict(core_id=CID,detail='81 테스트',signal='on'))
    return n,c


class OffmapLinks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store
        self.n,self.c=drawing(self.app);self.first=(self.c[0],81)
    def tearDown(self):self.s.close();self.temp.cleanup()

    def entry(self):return wf.completion_report(self.s)['by_id'][CID]

    def incomplete(self):
        warn=self.s.cable_core_warning_summary()
        return [x for x in self.c if 81 in warn[x]['incomplete_indices'] or warn[x]['unassigned']]

    def mark(self):
        ends=wf.offmap_free_ends(self.s,CID)
        self.assertEqual(sorted(e['node'] for e in ends),sorted([self.n[1],self.n[2]]),ends)
        wf.offmap_add(self.s,CID,ends[0],ends[1],'MDF 내부 미작도')

    def test_mark_completes_and_rechecks(self):
        self.assertFalse(self.entry()['complete'])
        self.assertIn('split',self.entry()['causes'])
        self.assertTrue(self.incomplete())
        self.mark()
        self.assertTrue(self.entry()['complete'],self.entry()['reason'])
        status,reason=wf.core_completion_brief(self.s,self.first)
        self.assertEqual(status,'연결완료');self.assertIn('도면 밖 연결',reason)
        self.assertIn('도면 밖 연결',wf.core_completion_locations(self.s,self.first))
        self.assertEqual(self.incomplete(),[])
        self.assertEqual(wf.offmap_free_ends(self.s,CID),[])
        self.assertEqual(len(wf.offmap_map_lines(self.s)),1)
        print('PASS offmap mark joins the two drawn pieces')

        # One side changed by mistake -> warned again, not silently excluded.
        update(self.s,self.c[1],81,dict(core_id='3061686999'))
        item=wf.offmap_evaluate(self.s)[0]
        self.assertEqual(item['state'],'problem');self.assertIn('코어ID 다름',item['reason'])
        self.assertFalse(self.entry()['complete'])
        self.assertIn('offmap',self.entry()['causes']);self.assertIn(wf.OFFMAP_NOTE,self.entry()['reason'])
        status,reason=wf.core_completion_brief(self.s,self.first)
        self.assertEqual(status,'미완료');self.assertIn('도면 밖 연결 불일치',reason)
        self.assertTrue(self.incomplete())
        self.s.undo()
        self.assertTrue(self.entry()['complete'],self.entry()['reason'])
        print('PASS offmap mismatch warns again')

        update(self.s,self.c[1],81,dict(signal='off'))
        self.assertIn('신호 OFF',wf.offmap_evaluate(self.s)[0]['reason'])
        self.s.undo()
        update(self.s,self.c[1],81,dict(status1='error'))
        self.assertEqual(wf.offmap_evaluate(self.s)[0]['state'],'problem')
        self.s.undo()
        self.assertEqual(wf.offmap_evaluate(self.s)[0]['state'],'ok')

        wf.offmap_remove(self.s,[0])
        self.assertFalse(self.entry()['complete'])
        self.s.undo()
        self.assertTrue(self.entry()['complete'])
        self.s.undo() # undo the mark itself
        self.assertEqual(wf.offmap_links(self.s),[]);self.assertFalse(self.entry()['complete'])
        print('PASS offmap OFF/error/remove/undo')

    def test_same_node_refused_and_before_drawing_ignored(self):
        ends=wf.offmap_free_ends(self.s,CID)
        with self.assertRaises(ValueError):wf.offmap_add(self.s,CID,ends[0],dict(ends[1],node=ends[0]['node']))
        self.mark()
        self.s.conn.execute("UPDATE meta SET value='before' WHERE key='active_scenario'");self.s.conn.commit()
        self.assertEqual(wf.offmap_evaluate(self.s),[])
        print('PASS offmap only in after drawings')

    def test_dialog_opens_and_marks(self):
        import tkinter as tk
        from unittest.mock import patch
        try:root=tk.Tk()
        except tk.TclError:self.skipTest('no display');return
        root.withdraw()
        try:
            with patch.object(wf,'top_app',return_value=None):
                dialog=wf.OffmapLinksDialog(root,self.s,CID)
            self.assertEqual(len(dialog.ends),2);self.assertEqual(len(dialog.end_tree.selection()),2)
            self.assertEqual(str(dialog.add_button['state']),'normal')
            with patch.object(wf.messagebox,'askyesno',return_value=True):dialog.add()
            self.assertEqual(len(wf.offmap_links(self.s)),1);self.assertEqual(len(dialog.items),1)
            self.assertTrue(self.entry()['complete'])
            dialog.tree.selection_set(dialog.tree.get_children())
            with patch.object(wf.messagebox,'askyesno',return_value=True):dialog.remove()
            self.assertEqual(wf.offmap_links(self.s),[])
            dialog.destroy();listing=wf.open_offmap_links(root,self.s);listing.destroy()
        finally:root.destroy()
        print('PASS offmap dialog marks and removes')


if __name__=='__main__':unittest.main(verbosity=2)
