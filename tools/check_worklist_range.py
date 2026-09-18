"""Real Windows gestures and clipboard round trips for work-list range copy."""
import csv
import ctypes
import faulthandler
import io
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from check_core_worklist import code,wf,fixture


def excel_clipboard():
    """Read CF_UNICODETEXT as Excel does, outside Tk's STRING chunk decoder."""
    user32=ctypes.WinDLL('user32',use_last_error=True)
    kernel32=ctypes.WinDLL('kernel32',use_last_error=True)
    user32.GetClipboardData.argtypes=[ctypes.c_uint];user32.GetClipboardData.restype=ctypes.c_void_p
    kernel32.GlobalLock.argtypes=[ctypes.c_void_p];kernel32.GlobalLock.restype=ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes=[ctypes.c_void_p]
    if not user32.OpenClipboard(None):raise ctypes.WinError(ctypes.get_last_error())
    try:
        handle=user32.GetClipboardData(13)
        if not handle:raise ctypes.WinError(ctypes.get_last_error())
        pointer=kernel32.GlobalLock(handle)
        if not pointer:raise ctypes.WinError(ctypes.get_last_error())
        try:return ctypes.wstring_at(pointer).replace('\r\n','\n')
        finally:kernel32.GlobalUnlock(handle)
    finally:user32.CloseClipboard()


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(120,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showwarning'), \
         patch.object(code['messagebox'],'showerror') as error:
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;nodes,cables,rn=fixture(s)
            cable=s.add_cable(nodes[0],nodes[3],'SYNTH-RANGE','144C','기설')
            with s.action('Synthetic range-copy rows'):
                for i in range(1,91):
                    name='합성 코어 '+str(i)
                    if i==2:name='탭\t포함'
                    if i==3:name='줄바꿈\n포함 "인용"'
                    s.conn.execute('UPDATE cores SET core_id=?,detail=?,signal=? WHERE cable_id=? AND core_index=?',
                                   (f'RANGE-{i:03}',name,'on',cable,i))
            s.backup_to(app.scenario_path('before'));app.refresh();app.update()
            dialog=code['CoreCheckDialog'](app,s);dialog.kind.set('신호있음');dialog.reload()
            dialog.geometry('1150x700+0+0');dialog.lift();app.update()
            tree=dialog.tree;copy=dialog.copy_actions;tree.focus_force();app.update()
            baseline=(wf.plan_snapshot(s.conn),s.history_rows(),s.data_revision())
            stamp=1000
            def point(iid,column):
                box=tree.bbox(iid,column);assert box,(iid,column)
                x,y,w,h=box;return x+min(15,w//2),y+h//2
            def send(sequence,xy,state=0):
                nonlocal stamp
                x,y=xy
                target=tree.winfo_containing(tree.winfo_rootx()+x,tree.winfo_rooty()+y)
                if target not in copy._labels:target=tree
                tx=x+tree.winfo_rootx()-target.winfo_rootx();ty=y+tree.winfo_rooty()-target.winfo_rooty()
                stamp+=1000
                target.event_generate(sequence,x=tx,y=ty,state=state,time=stamp)
                app.update()
            def drag(a,b):
                send('<ButtonPress-1>',a);send('<B1-Motion>',b,256);send('<ButtonRelease-1>',b)
            def click(xy,shift=False):
                send('<ButtonPress-1>',xy,1 if shift else 0);send('<ButtonRelease-1>',xy,1 if shift else 0)
            def mode(value):
                row=copy.bar.winfo_children()[1]
                next(w for w in row.winfo_children() if str(w.winfo_class())=='TRadiobutton' and str(w.cget('value'))==value).invoke();app.update()
            def copied():
                tree.focus_force();app.update();tree.event_generate('<Control-c>');app.update()
                return list(csv.reader(io.StringIO(excel_clipboard()),delimiter='\t'))
            def values(rows,columns):return [[tree.set(i,c) for c in columns] for i in rows]
            def assert_copy(rows,columns):
                actual=copied();expected=values(rows,columns)
                assert actual==expected,dict(differences=[(i,a,b) for i,(a,b) in enumerate(zip(actual,expected)) if a!=b][:5],sizes=(len(actual),len(expected)),
                                            selected=(copy.selected_rows[:5],copy.selected_columns),notice=copy.notice.get(),errors=errors)
            rows=tree.get_children();cols=tuple(tree['columns']);assert len(rows)>80
            print('RANGE: rectangles, reverse drag, actual overlay clicks, Shift and TSV escaping',flush=True)
            drag(point(rows[0],'id'),point(rows[3],'detail'));assert_copy(rows[:4],('id','detail'))
            assert len([w for w in copy._labels if w.winfo_ismapped()])==8
            drag(point(rows[3],'detail'),point(rows[1],'id'));assert_copy(rows[1:4],('id','detail'))
            click(point(rows[5],'category'),shift=True);assert_copy(rows[3:6],('detail','category'))
            # Shift+arrows extend a single-cell selection without touching any source value.
            click(point(rows[0],'id'));tree.event_generate('<Shift-Right>');tree.event_generate('<Shift-Down>');app.update()
            assert_copy(rows[:2],('id','detail'))
            # Include displayed values containing literal tab/newline/quotes.
            escaped=[i for i in rows if tree.set(i,'id') in ('RANGE-002','RANGE-003')]
            assert len(escaped)==2
            tree.see(escaped[0]);app.update();drag(point(escaped[0],'id'),point(escaped[-1],'detail'))
            assert_copy(escaped,('id','detail'))
            for iid in escaped:
                click(point(iid,'detail'));assert_copy((iid,),('detail',))
            print('RANGE: whole rows, whole columns, heading gestures and all selection',flush=True)
            tree.yview_moveto(0);app.update();mode('rows')
            drag(point(rows[1],'id'),point(rows[4],'detail'));assert_copy(rows[1:5],cols)
            mode('columns');drag(point(rows[2],'id'),point(rows[4],'detail'));assert_copy(rows,('id','detail'))
            x1=point(rows[0],'id')[0];x2=point(rows[0],'category')[0]
            drag((x1,copy.body_top()//2),(x2,copy.body_top()//2));assert_copy(rows,('id','detail','category'))
            assert tree.sort_column is None
            tree.focus_force();app.update();tree.event_generate('<Control-a>');app.update()
            assert copy.selected_rows==rows and copy.selected_columns==cols,(copy.selected_columns,errors)
            assert_copy(rows,cols)
            copy.copy(all_rows=True)
            assert list(csv.reader(io.StringIO(excel_clipboard()),delimiter='\t'))==[[tree.heading_text(c) for c in cols]]+values(rows,cols)
            print('RANGE: scroll edges, offscreen rows, horizontal scrolling and menu retention',flush=True)
            mode('cells');tree.yview_moveto(0);tree.xview_moveto(0);app.update()
            start=rows[0];send('<ButtonPress-1>',point(start,'id'))
            edge=(point(start,'detail')[0],tree.winfo_height()+8)
            send('<B1-Motion>',edge,256)
            for _ in range(8):copy.stop_scroll();copy.auto_scroll();app.update()
            assert tree.yview()[0]>0 and len(copy.selected_rows)>15,(tree.yview(),len(copy.selected_rows))
            send('<ButtonRelease-1>',edge);assert copy._scroll_job is None
            expected=copy.selected_rows;assert_copy(expected,('id','detail'))
            # Horizontal scroll brings the final column into the range.
            tree.yview_moveto(0);tree.xview_moveto(0);app.update()
            send('<ButtonPress-1>',point(rows[0],'detail'));edge=(tree.winfo_width()+8,point(rows[1],'detail')[1])
            send('<B1-Motion>',edge,256)
            for _ in range(15):copy.stop_scroll();copy.auto_scroll();app.update()
            send('<ButtonRelease-1>',edge);assert tree.xview()[0]>0 and copy.selected_columns[-1]=='route'
            assert_copy(rows[:2],('detail','category','note','route'))
            # Right-click within the highlight retains the rectangle.
            x,y=point(rows[1],'route');event=type('Event',(),dict(x=x,y=y,x_root=tree.winfo_rootx()+x,y_root=tree.winfo_rooty()+y))()
            with patch.object(copy.menu,'tk_popup') as popup:copy.context_menu(event);popup.assert_called_once()
            assert_copy(rows[:2],('detail','category','note','route'))
            print('RANGE: input drafts, Entry Ctrl+C, sort/filter reset and locked copy',flush=True)
            tree.xview_moveto(0);tree.yview_moveto(0);app.update()
            first=rows[0];tree.selection_set(first);dialog.pick_name();app.update()
            dialog.name_var.set('보존할 이름 초안');edit_core=dialog._edit_core
            drag(point(rows[3],'id'),point(rows[5],'detail'));assert_copy(rows[3:6],('id','detail'))
            assert dialog.name_var.get()=='보존할 이름 초안' and dialog._edit_core==edit_core
            assert tree.selection()==(first,)
            dialog.name_entry.focus_force();dialog.name_entry.selection_range(0,'end');app.update()
            dialog.name_entry.event_generate('<Control-c>');app.update();assert dialog.clipboard_get()=='보존할 이름 초안'
            dialog.name_var.set(dialog._name_original);tree.focus_force();app.update()
            click((point(rows[0],'id')[0],copy.body_top()//2));assert tree.sort_column=='id' and not copy.selected_rows
            sorted_rows=tree.get_children();drag(point(sorted_rows[0],'id'),point(sorted_rows[3],'detail'))
            assert_copy(sorted_rows[:4],('id','detail'))
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True);screenshot(dialog,Path('dist')/'v113-worklist-range.png')
            dialog.kind.set('신호없음');dialog.reload();app.update();assert not copy.selected_rows
            tree.selection_remove(*tree.selection());dialog.clipboard_clear();dialog.clipboard_append('keep')
            copy.copy();assert dialog.clipboard_get()=='keep' and '선택' in copy.notice.get()
            assert (wf.plan_snapshot(s.conn),s.history_rows(),s.data_revision())==baseline
            s.set_node_locked(nodes[0],True);app.refresh();app.update()
            dialog.kind.set('신호있음');dialog.reload();app.update();rows=tree.get_children()
            baseline=(wf.plan_snapshot(s.conn),s.history_rows(),s.data_revision())
            mode('rows');drag(point(rows[0],'id'),point(rows[2],'detail'));assert_copy(rows[:3],cols)
            assert (wf.plan_snapshot(s.conn),s.history_rows(),s.data_revision())==baseline
            dialog.geometry('950x650');app.update()
            for row in copy.bar.winfo_children():
                for widget in row.winfo_children():
                    assert widget.winfo_rootx()+widget.winfo_width()<=dialog.winfo_rootx()+dialog.winfo_width(),widget
            # Closing during edge dragging cancels both paint and scrolling callbacks.
            mode('cells');send('<ButtonPress-1>',point(rows[0],'id'));send('<B1-Motion>',(200,tree.winfo_height()+8),256)
            dialog.destroy();app.update();assert copy._scroll_job is None and copy._paint_job is None
            assert not errors,errors
            assert not error.called,error.call_args
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows range/reverse/Shift/row/column/header/keyboard copy, quoted TSV, autoscroll, sort/filter, drafts, locks, narrow layout and cleanup')


if __name__=='__main__':windows_ui()
