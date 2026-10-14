"""RN internal ports participate in reviewed incremental main-map allocation."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from check_after_plan import code,wf,LocalApp


def fixture(s,port_source=True):
    a=s.add_node('출발 RN',150,240,node_type='rn');b=s.add_node('도착 RN',650,240,node_type='rn')
    s.ensure_ports(a,{'mp':4,'sp':5,'p':4});sp5=next(r['core_index'] for r in s.cores('PORT:'+a) if r['label']=='SP5')
    c=s.add_cable(a,b,'SYNTH-RN','12C','기설')
    source=('PORT:'+a,sp5) if port_source else (c,5)
    s.update_core(*source,('RN-SERVICE','RN 간 합성 회선','normal','','on'))
    return a,b,c,source


class RNAllocationTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store
    def tearDown(self):self.s.close();self.temp.cleanup()
    def snap(self):return wf.plan_snapshot(self.s.conn),self.s.history_rows()
    def test_port_source_cable5_then_target_in_complete_history_and_reopen(self):
        a,b,c,source=fixture(self.s);service=wf.RNIncrementalCoreAllocator(self.app,source)
        before=self.snap();p=service.preview({c:5});self.assertEqual(self.snap(),before)
        self.assertEqual(len(p['added']),1);service.apply(p)
        self.assertFalse(wf.completion_report(self.s)['by_id']['RN-SERVICE']['complete'])
        service.load();mid=self.snap();p=service.preview({'PORT:'+b:1});self.assertEqual(len(p['added']),1)
        service.apply(p);after=wf.plan_snapshot(self.s.conn)
        self.assertTrue(wf.completion_report(self.s)['by_id']['RN-SERVICE']['complete'])
        self.assertEqual(self.s.core('PORT:'+b,1)['core_id'],'RN-SERVICE')
        self.assertEqual(len(after['splices']),2)
        self.s.undo();self.assertEqual(wf.plan_snapshot(self.s.conn),mid[0]);self.s.redo();self.assertEqual(wf.plan_snapshot(self.s.conn),after)
        path=self.s.path;self.s.close();self.s=code['Store'](path);self.app.store=self.s
        self.assertTrue(wf.completion_report(self.s)['by_id']['RN-SERVICE']['complete'])
    def test_cable_source_can_assign_both_rn_ports_in_one_atomic_batch(self):
        a,b,c,source=fixture(self.s,False);service=wf.RNIncrementalCoreAllocator(self.app,source)
        before=wf.plan_snapshot(self.s.conn);p=service.preview({'PORT:'+a:1,'PORT:'+b:1});service.apply(p)
        self.assertTrue(wf.completion_report(self.s)['by_id']['RN-SERVICE']['complete']);self.assertEqual(len(p['added']),2)
        self.assertEqual(wf.plan_snapshot(self.s.conn)['cores'],before['cores'])
        self.s.undo();self.assertEqual(wf.plan_snapshot(self.s.conn),before)
    def test_used_reserved_stale_tampered_and_failure_protect_ports(self):
        a,b,c,source=fixture(self.s,False)
        self.s.update_core('PORT:'+b,2,('OTHER','기존 회선','normal','','unknown'))
        wf.AfterPlanner(self.app).set_fixed(slots=[('PORT:'+b,3)],reason='예비포트')
        service=wf.RNIncrementalCoreAllocator(self.app,source);before=self.snap()
        for index in (2,3,999):
            with self.assertRaises(ValueError):service.preview({'PORT:'+b:index})
        p=service.preview({'PORT:'+a:1,'PORT:'+b:1});original=self.s._write_core
        def fail(owner,index,values):
            if owner=='PORT:'+b:raise ValueError('synthetic second write failure')
            original(owner,index,values)
        with patch.object(self.s,'_write_core',side_effect=fail),self.assertRaises(ValueError):service.apply(p)
        self.assertEqual(self.snap(),before)
        p['selected']['PORT:'+b]=4
        with self.assertRaises(ValueError):service.apply(p)
        service.load();p=service.preview({'PORT:'+b:1});self.s.set_node_details(b,'새 이름')
        with self.assertRaises(ValueError):service.apply(p)
        self.assertFalse(self.s.core('PORT:'+b,1)['core_id'])


def windows_ui():
    if sys.platform!='win32':return
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp),patch.object(code['messagebox'],'showerror') as error,patch.object(code['messagebox'],'showwarning') as warning,patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'askyesno',return_value=True):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            app.geometry('1450x950+0+0');s=app.store;s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','after')");s.conn.commit()
            a,b,c,source=fixture(s);app.refresh();app.update();app.fit_view();app.update()
            node=code['NodeDialog'](app,s,a);app.update();node.rn_identity_button.invoke();app.update();editor=node._rn_identity_dialog
            editor.focus_core(source[1]);app.update();before=wf.plan_snapshot(s.conn)
            editor.detail.set('미저장');editor.allocation_button.invoke();app.update()
            assert not getattr(app,'_map_allocation_panel',None) and editor.detail.get()=='미저장';error.reset_mock()
            editor.detail.set(editor.original[source[1]][1]);editor.allocation_button.invoke();app.update();panel=app._map_allocation_panel
            panel.capacity_tabs.select(0);app.update()
            assert editor.state()=='withdrawn' and panel.service.source==source
            assert panel.capacity_table.item(str(source[1]),'values')[0]=='SP5'
            app.fit_view();app.update()
            # Real pointer clicks on the cable and RN symbol enter their capacities.
            def target_click(kind,key):
                mapping=app.item_to_cable if kind=='cable' else app.item_to_node
                points=[]
                for item,value in mapping.items():
                    if value!=key:continue
                    box=app.canvas.bbox(item)
                    if not box:continue
                    l,t,r,bt=box
                    points.extend((l+(r-l)*fx,t+(bt-t)*fy) for fx in (.5,.25,.75) for fy in (.5,.25,.75))
                for x,y in points:
                    x=int(x-app.canvas.canvasx(0));y=int(y-app.canvas.canvasy(0))
                    if 0<x<app.canvas.winfo_width() and 0<y<app.canvas.winfo_height() and app.target(SimpleNamespace(x=x,y=y))==(kind,key):
                        app.canvas.event_generate('<Button-1>',x=x,y=y);app.canvas.event_generate('<ButtonRelease-1>',x=x,y=y);app.update();return
                raise AssertionError(('No visible target',kind,key))
            def number_click(number):
                box=panel.sheet.bbox('number:'+str(number));assert box
                x=(box[0]+box[2])/2;y=(box[1]+box[3])/2
                panel.sheet.event_generate('<Button-1>',x=int(x-panel.sheet.canvasx(0)),y=int(y-panel.sheet.canvasy(0)));app.update()
            target_click('cable',c);number_click(5);assert panel.selected[c]==5
            target_click('node',b);assert panel.active_cable=='PORT:'+b
            assert panel.capacity_table.item('1','values')[0]=='IN';number_click(1)
            text=panel.review_text(panel.service.preview(panel.selected));assert 'SP5' in text and 'IN' in text
            from check_desktop_design import screenshot
            screenshot(app,Path(temp)/'v132-rn-map-allocation.png')
            def review(confirm):
                for w in app.winfo_children():
                    if isinstance(w,wf.ManualAllocationReview):
                        if confirm:w.confirm()
                        else:w.destroy()
                        return
                app.after(20,lambda:review(confirm))
            app.after(30,lambda:review(False));panel.apply_button.invoke();app.update();assert wf.plan_snapshot(s.conn)==before
            app.after(30,lambda:review(True));panel.apply_button.invoke();app.update()
            assert wf.completion_report(s)['by_id']['RN-SERVICE']['complete']
            assert not s.cable_core_warning_summary()[c]['incomplete']
            assert panel.close_requested();app.update();assert editor.state()=='normal' and editor.active==source[1]
            s.undo();app.refresh();app.update();assert wf.plan_snapshot(s.conn)==before
            s.redo();app.refresh();app.update();assert wf.completion_report(s)['by_id']['RN-SERVICE']['complete']
            assert not errors and not error.called and not warning.called,(errors,error.call_args,warning.call_args)
            print('PASS Windows RN SP5 source button, cable 5 and RN IN pointer selection, labels, reviewed cancel/apply, complete path, editor return and undo/redo')
        finally:
            panel=getattr(app,'_map_allocation_panel',None)
            if panel is not None and panel.winfo_exists():panel.destroy(restore_editor=False)
            app.store.close();app.destroy()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RNAllocationTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
