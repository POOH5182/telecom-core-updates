"""Real Windows main-map allocation, full cable capacity and preserved source editor."""
import faulthandler
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from check_after_plan import code,wf,update
from check_after_routes import drawing
from check_manual_allocation import clear_old_connector


def windows_ui():
    if sys.platform!='win32':
        print('Main-map allocation pointer gate runs on Windows.');return
    faulthandler.dump_traceback_later(100,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showerror') as error,patch.object(code['messagebox'],'showwarning') as warning, \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'askyesno',return_value=True):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            app.geometry('1450x950+0+0');s=app.store
            s.conn.execute("INSERT INTO meta VALUES('active_scenario','after') ON CONFLICT(key) DO UPDATE SET value='after'");s.conn.commit()
            i=drawing(app);clear_old_connector(app,i)
            # A 144-core cable makes compact capacity visible; a used number is inspect-only.
            with s.action('Synthetic 144C'):
                s.conn.execute("UPDATE cables SET size=144,spec='144C' WHERE id=?",(i['direct'],))
                for n in range(13,145):
                    s.conn.execute('INSERT INTO cores(cable_id,core_index) VALUES(?,?)',(i['direct'],n))
            update(s,i['direct'],2,dict(core_id='OCCUPIED',detail='다른 회선',signal='on'))
            s.connect(i['b'],(i['direct'],2),(i['detour1'],2))
            app.refresh();app.update();app.fit_view();app.update()
            editor=code['open_detail_dialog'](app,s,'cable',i['left']);editor.focus_core(1);app.update()
            original=wf.plan_snapshot(s.conn);history=s.history_rows();before=app.scenario_path('before').read_bytes();scale=app.view_scale
            # Draft edits must not be discarded when entering the mode.
            editor.lot_var.set('Unapplied note');editor.map_allocation_button.invoke();app.update()
            assert not getattr(app,'_map_allocation_panel',None) and editor.lot_var.get()=='Unapplied note'
            editor.lot_var.set('');editor.map_allocation_button.invoke();app.update()
            panel=app._map_allocation_panel
            assert isinstance(panel,wf.MapCoreAllocationPanel) and editor.state()=='withdrawn'
            assert app.view_scale==scale and app.highlight_owner is panel
            assert len(panel.service.problem['components'])==2
            print('MAP LAYOUT:',app.winfo_geometry(),panel.winfo_ismapped(),app.canvas.winfo_height(),panel.winfo_height(),panel.sheet.winfo_height(),flush=True)
            assert panel.winfo_ismapped() and app.canvas.winfo_height()>150
            assert not app.dashboard_frame.winfo_ismapped()
            app.fit_view();app.update()

            def click_cable(cid):
                points=[]
                # Text anchors can fall outside glyphs or under a node label.
                for item,cable in app.item_to_cable.items():
                    if cable!=cid:continue
                    box=app.canvas.bbox(item)
                    if box:
                        l,t,r,b=box
                        points.extend((l+(r-l)*fx,t+(b-t)*fy) for fx in (.5,.25,.75) for fy in (.5,.25,.75))
                candidates=[]
                for x,y in points:
                    x=int(x-app.canvas.canvasx(0));y=int(y-app.canvas.canvasy(0))
                    if 0<x<app.canvas.winfo_width() and 0<y<app.canvas.winfo_height() and app.target(SimpleNamespace(x=x,y=y))==('cable',cid):candidates.append((x,y))
                assert candidates,('No exposed cable target',cid,app.canvas.winfo_geometry(),points)
                x,y=candidates[0]
                app.canvas.event_generate('<Button-1>',x=x,y=y);app.canvas.event_generate('<ButtonRelease-1>',x=x,y=y);app.update()

            def click_number(number):
                box=panel.sheet.bbox('number:'+str(number));assert box
                region=list(map(float,panel.sheet.cget('scrollregion').split()))
                panel.sheet.yview_moveto(max(0,box[1])/max(1,region[3]));app.update()
                x=(box[0]+box[2])/2;y=(box[1]+box[3])/2
                panel.sheet.event_generate('<Button-1>',x=int(x-panel.sheet.canvasx(0)),y=int(y-panel.sheet.canvasy(0)));app.update()

            click_cable(i['direct'])
            assert panel.active_cable==i['direct'] and i['direct'] not in panel.selected
            assert '전체 144' in panel.cable_status.get()
            assert all(panel.sheet.find_withtag('number:'+str(n)) for n in range(1,145))
            assert '빈 코어' in panel.sheet.itemcget(panel.sheet.find_withtag('state:144')[0],'text')
            assert '사용 중' in panel.sheet.itemcget(panel.sheet.find_withtag('state:2')[0],'text')
            assert panel.capacity_table.item('2','values')[2:4]==('OCCUPIED','다른 회선')
            click_number(2)
            assert i['direct'] not in panel.selected and i['detour1'] in panel.inspect_cables
            assert '다른 회선' in panel.details.get('1.0','end')
            assert wf.plan_snapshot(s.conn)==original and s.history_rows()==history
            # Filtering must preserve physical numbers, even on the last row.
            panel.capacity_filter.set('빈 코어만');panel.filter_combo.event_generate('<<ComboboxSelected>>');app.update()
            assert not panel.sheet.find_withtag('number:2') and not panel.capacity_table.exists('2')
            click_number(144);assert panel.selected[i['direct']]==144
            click_number(144);assert i['direct'] not in panel.selected
            panel.capacity_filter.set('전체 번호');panel.filter_capacity();app.update()
            panel.capacity_tabs.select(1);app.update();panel.capacity_table.see('2');app.update()
            x,y,w,h=panel.capacity_table.bbox('2')
            panel.capacity_table.event_generate('<Button-1>',x=x+20,y=y+h//2)
            panel.capacity_table.event_generate('<ButtonRelease-1>',x=x+20,y=y+h//2);app.update()
            assert i['direct'] not in panel.selected and i['detour1'] in panel.inspect_cables
            panel.capacity_table.selection_set('7');panel.capacity_table.focus_force()
            panel.capacity_table.event_generate('<Return>');app.update();assert panel.selected[i['direct']]==7
            panel.capacity_table.event_generate('<Return>');app.update();assert i['direct'] not in panel.selected
            panel.capacity_tabs.select(0);app.update()
            click_number(7)
            assert panel.selected[i['direct']]==7
            assert '7번' in app.highlight_core_labels[i['direct']]
            # Node clicks/drags and Delete never move or delete drawing geometry in this mode.
            app.selected={i['b']};app.delete_selected();assert wf.plan_snapshot(s.conn)==original
            # Merely inspect another cable: no forced extra segment in the proposal.
            click_cable(i['detour2']);assert i['detour2'] not in panel.selected
            with patch.object(code['messagebox'],'askyesno',return_value=False):
                app.set_mode('hamche');assert app._map_allocation_panel is panel and app.mode=='select'
            for accept in (False,True):
                def answer(accept=accept):
                    review=next(w for w in app.winfo_children() if isinstance(w,wf.ManualAllocationReview))
                    (review.confirm if accept else review.destroy)()
                app.after(100,answer);panel.apply_button.invoke();app.update()
                if not accept:assert wf.plan_snapshot(s.conn)==original and panel.selected[i['direct']]==7
            assert s.core(i['direct'],7)['core_id']=='CORE-1'
            assert wf.completion_report(s)['by_id']['CORE-1']['complete']
            assert app.scenario_path('before').read_bytes()==before
            panel.sheet.focus_force();panel.sheet.event_generate('<Control-z>');app.update();panel.check_live()
            assert wf.plan_snapshot(s.conn)==original and panel.stale
            assert str(panel.apply_button['state'])=='disabled'
            panel.reload();app.update();click_cable(i['direct'])
            # Save just the first cable of a two-cable gap, then continue in the
            # same panel. Incomplete end-to-end topology must not block saving.
            click_cable(i['detour1']);click_number(8)
            app.after(100,lambda:answer(True));panel.apply_button.invoke();app.update()
            assert s.core(i['detour1'],8)['core_id']=='CORE-1'
            assert not wf.completion_report(s)['by_id']['CORE-1']['complete']
            assert '배정 저장 완료' in panel.message.get() and '미완료' in panel.message.get()
            click_cable(i['detour2']);click_number(11)
            app.after(100,lambda:answer(True));panel.apply_button.invoke();app.update()
            assert s.core(i['detour2'],11)['core_id']=='CORE-1'
            assert wf.completion_report(s)['by_id']['CORE-1']['complete']
            app.undo();app.undo();app.update();panel.reload();app.update();click_cable(i['direct'])
            assert wf.plan_snapshot(s.conn)==original
            # Compact windows retain the map, capacity grid and all actions.
            app.geometry('1000x700');app.update();panel.apply_button.master.reflow();app.update()
            assert app.canvas.winfo_height()>150 and panel.sheet.winfo_height()>65
            assert panel.apply_button.winfo_viewable()
            assert panel.apply_button.winfo_rootx()+panel.apply_button.winfo_width()<=app.winfo_rootx()+app.winfo_width()
            panel.close_requested();app.update()
            assert app._map_allocation_panel is None and editor.state()=='normal' and editor._core_trace_enabled
            assert app.dashboard_frame.winfo_ismapped()
            assert wf.plan_snapshot(s.conn)==original
            # Source changes close the panel without reopening an obsolete editor.
            editor.map_allocation_button.invoke();app.update();panel=app._map_allocation_panel
            app.replace_current_from(app.scenario_path('before'));app.update()
            assert app._map_allocation_panel is None and not panel.winfo_exists()
            assert not errors,errors;assert not error.called,error.call_args_list;assert not warning.called,warning.call_args_list
        finally:app.on_close();faulthandler.cancel_dump_traceback_later()
    print('PASS main-map core button, cable and 144-number clicks, occupied route inspection, draft/cancel/apply, undo, narrow layout and source cleanup')


if __name__=='__main__':windows_ui()
