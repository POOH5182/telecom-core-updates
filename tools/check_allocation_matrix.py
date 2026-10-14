"""Reviewed multi-cable capacity, display-only ordering and editor-window transition."""
import faulthandler
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from check_after_plan import code,wf,LocalApp,update


def fixture(s):
    a=s.add_node('출발 RN',120,160,node_type='rn');h=s.add_node('함체 1',380,160);j=s.add_node('함체 2',650,160);b=s.add_node('도착 RN',910,160,node_type='rn')
    cables=[s.add_cable(x,y,name,'12C','기설') for x,y,name in ((a,h,'A'),(h,j,'B'),(j,b,'C'))]
    for owner,index,name in (('PORT:'+a,1,'출발 내역'),('PORT:'+b,1,'도착 내역'),(cables[0],1,'회선 내역')):
        update(s,owner,index,dict(core_id='ROUTE-1',detail=name,signal='on'))
    s.connect(a,('PORT:'+a,1),(cables[0],1))
    # Capacity distinctions: used, reserved and the shared free numbers.
    update(s,cables[1],4,dict(core_id='OTHER',detail='타 회선',signal='on'))
    x=s.add_node('외딴 1',300,420);y=s.add_node('외딴 2',650,420)
    detached=s.add_cable(x,y,'분리 케이블','12C','기설')
    return a,b,cables,detached


class MatrixTests(unittest.TestCase):
    def test_order_reverse_branch_disconnected_and_no_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            app=LocalApp(temp);s=app.store
            try:
                a,b,(A,B,C),D=fixture(s);net=wf.Network(s.conn);snapshot=wf.plan_snapshot(s.conn);history=s.history_rows()
                for click_order in ([C,A,B],[B,C,A],[A,B,C]):
                    self.assertEqual(wf.allocation_display_order(net,click_order,A)[0],[A,B,C])
                    self.assertEqual(wf.allocation_display_order(net,click_order,C)[0],[C,B,A])
                order,labels=wf.allocation_display_order(net,[D,B,A,C],A)
                self.assertEqual(order,[A,B,C,D]);self.assertIn('미연결',labels[D])
                order,labels=wf.allocation_display_order(net,[A,B,C],B)
                self.assertEqual(order[0],B);self.assertIn('후보',labels[A]);self.assertIn('후보',labels[C])
                self.assertEqual(wf.plan_snapshot(s.conn),snapshot);self.assertEqual(s.history_rows(),history)
            finally:s.close()

    def test_saved_ends_preserved_and_completed_only_after_actual_join(self):
        with tempfile.TemporaryDirectory() as temp:
            app=LocalApp(temp);s=app.store
            try:
                a,b,(A,B,C),D=fixture(s);service=wf.RNIncrementalCoreAllocator(app,(A,1));original=wf.plan_snapshot(s.conn)
                p=service.preview({B:2,C:3});self.assertEqual(wf.plan_snapshot(s.conn),original)
                service.apply(p)
                self.assertTrue(wf.completion_report(s)['by_id']['ROUTE-1']['complete'])
                self.assertEqual(wf.plan_snapshot(s.conn)['ports'],original['ports'])
                self.assertEqual([r for r in wf.plan_snapshot(s.conn)['cores'] if r['cable_id']==A],[r for r in original['cores'] if r['cable_id']==A])
                for c in (A,C):self.assertFalse(s.cable_core_warning_summary()[c]['incomplete'])
                self.assertTrue(s.cable_core_warning_summary()[B]['incomplete']) # Unrelated OTHER remains actionable.
                s.undo();self.assertEqual(wf.plan_snapshot(s.conn),original)
            finally:s.close()


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(100,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp),patch.object(code['messagebox'],'showwarning') as warning,patch.object(code['messagebox'],'showerror') as error,patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'askyesno',return_value=True):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','after')");s.conn.commit()
            a,b,(A,B,C),D=fixture(s);wf.AfterPlanner(app).set_fixed(slots=[(C,4)],reason='예비')
            app.geometry('1100x800+0+0');app.update_title();app.refresh();app.update();app.fit_view();app.update()
            original=wf.plan_snapshot(s.conn);editor=code['open_detail_dialog'](app,s,'cable',A);editor.focus_core(1);app.update()
            editor.geometry('1100x720+20+30');app.update();position=wf.popup_outer_geometry(editor);canvas_size=(app.canvas.winfo_width(),app.canvas.winfo_height())
            editor.map_allocation_button.invoke();app.update();panel=app._map_allocation_panel
            assert editor.state()=='withdrawn' and panel.winfo_manager()=='wm'
            assert panel.grab_current() is None
            assert (app.canvas.winfo_width(),app.canvas.winfo_height())==canvas_size
            actual=wf.popup_outer_geometry(panel);assert abs(actual[0]-position[0])<5 and abs(actual[1]-position[1])<5,(position,actual)
            assert abs(panel.winfo_width()-1100)<5 and abs(panel.winfo_height()-720)<5
            assert panel.capacity_tabs.select()==str(panel.matrix_frame)
            def map_click(cid):
                for item,key in list(app.item_to_cable.items()):
                    if key!=cid:continue
                    box=app.canvas.bbox(item)
                    if not box:continue
                    l,t,r,bt=box
                    for fx in (.5,.25,.75):
                        for fy in (.5,.25,.75):
                            x=int(l+(r-l)*fx-app.canvas.canvasx(0));y=int(t+(bt-t)*fy-app.canvas.canvasy(0))
                            if 0<x<app.canvas.winfo_width() and 0<y<app.canvas.winfo_height() and app.target(SimpleNamespace(x=x,y=y))==('cable',cid):
                                app.canvas.event_generate('<Button-1>',x=x,y=y);app.canvas.event_generate('<ButtonRelease-1>',x=x,y=y);app.update();return
                raise AssertionError(('no target',cid))
            def reveal(cid):
                panel.matrix_scroll('moveto',panel.columns.index(cid)/len(panel.columns));app.update()
            def header(kind,cid):
                reveal(cid);box=panel.matrix_headers.bbox(kind+':'+cid);assert box
                panel.matrix_headers.event_generate('<Button-1>',x=int((box[0]+box[2])/2-panel.matrix_headers.canvasx(0)),y=int((box[1]+box[3])/2));app.update()
            def cell(cid,index):
                reveal(cid);box=panel.matrix.bbox('matrix:'+cid+':'+str(index));assert box
                panel.matrix.yview_moveto(max(0,box[1])/(len(panel.matrix_numbers)*panel.MATRIX_H));app.update()
                panel.matrix.event_generate('<Button-1>',x=int((box[0]+box[2])/2-panel.matrix.canvasx(0)),y=int((box[1]+box[3])/2-panel.matrix.canvasy(0)));app.update()
            map_click(C);map_click(B);map_click(A)
            assert len(panel.columns)==len(set(panel.columns))
            assert [c for c in panel.columns if c in (A,B,C)]==[A,B,C]
            assert 2 in panel.common_numbers and 4 not in panel.common_numbers
            cell(B,4);assert B not in panel.selected # Used is inspection only.
            cell(C,4);assert C not in panel.selected # Reserved is inspection only.
            cell(B,2);cell(C,3);chosen=dict(panel.selected)
            header('start',C);assert [c for c in panel.columns if c in (A,B,C)]==[C,B,A] and panel.selected==chosen
            assert app.highlight_core_labels[C].startswith('[1]')
            map_click(D);assert '미연결' in panel.order_groups[D];cell(D,6);header('remove',D);assert D not in panel.columns and D not in panel.selected
            # Existing end removal is display-only, and source is protected.
            header('remove','PORT:'+b);assert panel.selected['PORT:'+b]==1 and s.core('PORT:'+b,1)['core_id']=='ROUTE-1'
            panel.remove_cable(A);assert A in panel.columns
            assert wf.plan_snapshot(s.conn)==original
            panel.matrix_scroll('moveto',0);panel.matrix.yview_moveto(0);panel.lift();app.update()
            from check_desktop_design import screenshot
            screenshot(panel,Path(temp)/'v137-multi-cable-allocation.png')
            def ctrl_w(widget):
                widget.focus_force();app.update();widget.event_generate('<Control-KeyPress-w>');widget.event_generate('<Control-KeyRelease-w>');app.update()
            with patch.object(code['messagebox'],'askyesno',return_value=False):ctrl_w(panel.matrix)
            assert panel.winfo_exists() and panel.selected==chosen
            def answer(yes):
                review=next((w for w in app.winfo_children() if isinstance(w,wf.ManualAllocationReview)),None)
                if review is None:app.after(20,lambda:answer(yes));return
                if yes:review.confirm()
                else:ctrl_w(review)
            app.after(30,lambda:answer(False));panel.apply_button.invoke();app.update();assert wf.plan_snapshot(s.conn)==original
            app.after(30,lambda:answer(True));panel.apply_button.invoke();app.update()
            assert wf.completion_report(s)['by_id']['ROUTE-1']['complete']
            assert wf.plan_snapshot(s.conn)['ports']==original['ports']
            ctrl_w(panel.matrix);assert not panel.winfo_exists() and editor.state()=='normal'
            assert editor.tree.selection()==('1',)
            # Entry input must not be changed by Tk Ctrl+W class bindings on cancel.
            popup=code['tk'].Toplevel(app);entry=code['ttk'].Entry(popup);entry.pack();entry.insert(0,'preserve draft');app.update()
            calls=[];popup.protocol('WM_DELETE_WINDOW',lambda:calls.append('close'))
            ctrl_w(entry);assert calls==['close'] and entry.get()=='preserve draft' and popup.winfo_exists()
            popup.protocol('WM_DELETE_WINDOW',popup.destroy);ctrl_w(entry);assert not popup.winfo_exists() and app.winfo_exists()
            s.undo();app.refresh();app.update();assert wf.plan_snapshot(s.conn)==original
            assert not errors and not warning.called and not error.called,(errors,warning.call_args,error.call_args)
            print('PASS Windows matrix map clicks, CBA ordering, protected ends, remove, common free capacity, exact editor position, cancel/apply, completion, undo and Ctrl+W')
        finally:app.on_close();faulthandler.cancel_dump_traceback_later()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(MatrixTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
