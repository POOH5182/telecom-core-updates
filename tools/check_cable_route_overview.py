"""V199: a plain click on a cable blinks the routes of all its cores and
shows, at each route end, only how many of its cores arrive there.
Selecting one core in the cable window still shows only that core."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_field_survey import code,wf
from check_field_slots import ScenarioHarness


class OverviewHarness(ScenarioHarness):
    def stop_highlight_blink(self,clear=False):
        self.highlight_owner=None
        if clear:
            self._cable_overview=None;self.highlight_cables=set();self.highlight_cable_colors={}
            self.highlight_connection_model={};self._highlight_seeds=();self._highlight_stamp=None


class CableRouteOverview(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();s=self.s=code['Store'](Path(self.temp.name)/'w.sqlite3')
        self.mdf=s.add_node('MDF',0,0);self.j=s.add_node('함체 J',240,0)
        self.s1=s.add_node('가입자1',480,-120,'sub');self.s2=s.add_node('가입자2',480,0,'sub')
        self.x=s.add_node('함체 X',480,120);self.y=s.add_node('함체 Y',720,120)
        self.f=s.add_cable(self.mdf,self.j,'F','12C','기설')
        self.d1=s.add_cable(self.j,self.s1,'D1','4C','기설');self.d2=s.add_cable(self.j,self.s2,'D2','4C','기설')
        self.d3=s.add_cable(self.j,self.x,'D3','4C','기설');self.d4=s.add_cable(self.x,self.y,'D4','4C','기설')
        for i,(cable,index) in enumerate(((self.d1,1),(self.d2,1),(self.d1,2),(self.d3,1)),start=1):
            cid=f'CORE-{i}'
            s.update_core(self.f,i,(cid,'내역','normal','','on'));s.update_core(cable,index,(cid,'내역','normal','','on'))
            s.connect(self.j,(self.f,i),(cable,index))
    def tearDown(self):self.s.close();self.temp.cleanup()

    def ends(self,cable):
        model=wf.cable_route_overview(self.s,cable)
        return model,{e['name']:(e['arrive'],e['stop']) for e in model['ends']}

    def test_counts_only_route_ends(self):
        before=self.s.data_revision()
        model,ends=self.ends(self.f)
        self.assertEqual(model['seed_count'],4)
        self.assertEqual(ends,{'MDF':(4,0),'가입자1':(2,0),'가입자2':(1,0),'함체 X':(0,1)},ends)
        self.assertNotIn('함체 J',ends)
        self.assertEqual(set(model['colors']),{self.f,self.d1,self.d2,self.d3})
        x=next(e for e in model['ends'] if e['name']=='함체 X')
        self.assertIn('미접속 1코어',x['text']);self.assertEqual(x['color'],wf.CABLE_OVERVIEW_STOP_COLOR)
        self.assertIn('4코어 도착',next(e['text'] for e in model['ends'] if e['name']=='MDF'))
        self.assertEqual(self.s.data_revision(),before)
        s1=next(e for e in model['ends'] if e['name']=='가입자1')
        self.assertEqual([(c['number'],c['core_id'],c['state']) for c in s1['cores']],[(1,'CORE-1','도착'),(3,'CORE-3','도착')])
        self.assertTrue(all('D1' in c['end'] for c in s1['cores']),s1['cores'])
        self.assertEqual([(c['number'],c['state']) for c in x['cores']],[(4,'미접속')])
        print('PASS end lists which cores arrive (V201)')
        model,ends=self.ends(self.d1)
        self.assertEqual(ends,{'MDF':(2,0),'가입자1':(2,0)},ends)
        self.assertEqual(set(model['colors']),{self.f,self.d1})
        empty=wf.cable_route_overview(self.s,self.d4)
        self.assertEqual(empty['seed_count'],0);self.assertEqual(empty['ends'],[])
        print('PASS cable overview counts cores at each route end')

    def test_app_overview_follows_edits_and_core_selection_replaces_it(self):
        app=OverviewHarness(self.s);app.highlight_owner=None
        app._cable_overview=self.f;app.highlight_owner='cable_overview'
        app.refresh_connection_highlight(force=True)
        model=app.highlight_connection_model['cable_overview']
        self.assertEqual(app.highlight_cables,{self.f,self.d1,self.d2,self.d3})
        self.assertEqual(app.highlight_core_labels,{})
        self.assertEqual(sum(e['arrive'] for e in model['ends'] if e['name']=='MDF'),4)
        # Joining D3 onward at X: that core now arrives at Y.
        self.s.update_core(self.d4,1,('CORE-4','내역','normal','','on'));self.s.connect(self.x,(self.d3,1),(self.d4,1))
        app.refresh_connection_highlight()
        ends={e['name']:(e['arrive'],e['stop']) for e in app.highlight_connection_model['cable_overview']['ends']}
        self.assertEqual(ends.get('함체 Y'),(1,0),ends);self.assertNotIn('함체 X',ends)
        # The cable window's one-core path takes over (start_highlight_blink resets it).
        source=code['App'].start_highlight_blink.__code__.co_names
        self.assertIn('_cable_overview',source)
        app.clear_cable_overview();self.assertIsNone(app._cable_overview)
        self.assertEqual(app.highlight_cables,set())
        print('PASS app cable overview refreshes and clears')


def windows_ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    import faulthandler
    faulthandler.dump_traceback_later(120,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;mdf=s.add_node('OV MDF',300,200);j=s.add_node('OV J',600,200)
            s1=s.add_node('OV S1',900,100,'sub');s2=s.add_node('OV S2',900,300,'sub')
            f=s.add_cable(mdf,j,'OVF','12C','기설');d1=s.add_cable(j,s1,'OVD1','4C','기설');d2=s.add_cable(j,s2,'OVD2','4C','기설')
            for i,(cable,index) in enumerate(((d1,1),(d2,1),(d1,2)),start=1):
                s.update_core(f,i,(f'OV-{i}','내역','normal','','on'));s.update_core(cable,index,(f'OV-{i}','내역','normal','','on'))
                s.connect(j,(f,i),(cable,index))
            app.refresh();app.update()
            class E:x=5;y=5;state=0
            with patch.object(app,'target',return_value=('cable',f)):app.click(E())
            app.drop(E());app.update()
            assert app.highlight_owner=='cable_overview',app.highlight_owner
            assert app.highlight_cables=={f,d1,d2},app.highlight_cables
            texts=[app.canvas.itemcget(i,'text') for i in app.canvas.find_withtag('core_path_port') if app.canvas.type(i)=='text']
            assert any('OV MDF' in t and '3' in t for t in texts),texts
            assert any('OV S1' in t and '2' in t for t in texts),texts
            assert not app.canvas.find_withtag('core_path_number'),'per-core labels must not be drawn'
            assert '3' in app.status.get(),app.status.get()
            # V201: clicking the 「N코어 도착」 label lists the arrived cores.
            item=next(i for i in app.canvas.find_withtag('cable_overview_end') if app.canvas.type(i)=='text' and 'OV S1' in app.canvas.itemcget(i,'text'))
            bx=app.canvas.bbox(item);app.canvas.xview_moveto(0);app.canvas.yview_moveto(0);app.update()
            class L:state=0
            L.x=int((bx[0]+bx[2])/2-app.canvas.canvasx(0));L.y=int((bx[1]+bx[3])/2-app.canvas.canvasy(0))
            assert app.click(L())=='break'
            found=[w for w in app.winfo_children() if isinstance(w,code['OverviewEndCoresDialog'])]
            assert len(found)==1,found
            values=[found[0].tree.item(i,'values') for i in found[0].tree.get_children()]
            assert [(v[0],v[1],v[4]) for v in values]==[('1','OV-1','도착'),('3','OV-3','도착')],values
            assert app.highlight_owner=='cable_overview','label click keeps the overview'
            found[0].copy_rows();assert 'OV-3' in app.clipboard_get()
            found[0].destroy();app.update()
            # Inside the cable window, one core row shows only that core again.
            dialog=code['CableDialog'](app,s,cable_id=d2);app.update()
            dialog.notebook.select(dialog.identity_tab);app.update()
            dialog.identity_tree.selection_set('1');dialog.run_core_trace();app.update()
            assert app.highlight_owner is dialog,app.highlight_owner
            assert app.highlight_cables=={f,d2},app.highlight_cables
            assert not app.highlight_connection_model.get('cable_overview')
            dialog.destroy();app.update()
            # Clicking a cable again, then empty canvas, clears the overview.
            with patch.object(app,'target',return_value=('cable',d1)):app.click(E())
            app.drop(E());assert app.highlight_cables=={f,d1},app.highlight_cables
            with patch.object(app,'target',return_value=(None,None)):app.click(E())
            app.drop(E());app.update()
            assert not app.highlight_cables and app.__dict__.get('_cable_overview') is None
            assert not errors,errors
            print('PASS windows cable click shows all core routes and end counts')
        finally:app.on_close()


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=2).result
    if not result.wasSuccessful():
        print('::error::check_cable_route_overview unit tests failed');sys.exit(1)
    try:windows_ui()
    except Exception:
        import traceback;print('::error::'+traceback.format_exc().replace('\n','%0A'));raise
    print('PASS check_cable_route_overview')
