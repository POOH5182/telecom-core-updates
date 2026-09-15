"""Real Windows layout, readable semantic states and synthetic UI previews."""
import base64
import ctypes
from ctypes import wintypes
import faulthandler
import os
from pathlib import Path
import struct
import sys
import tempfile
from unittest.mock import patch
import zlib

from check_field_survey import code,wf


def screenshot(window,path):
    """Capture only this synthetic test window's client area, using Windows GDI."""
    window.update_idletasks();window.lift();window.update()
    user=ctypes.windll.user32;gdi=ctypes.windll.gdi32
    user.GetDC.argtypes=[wintypes.HWND];user.GetDC.restype=wintypes.HDC
    user.ReleaseDC.argtypes=[wintypes.HWND,wintypes.HDC]
    gdi.CreateCompatibleDC.argtypes=[wintypes.HDC];gdi.CreateCompatibleDC.restype=wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes=[wintypes.HDC,ctypes.c_int,ctypes.c_int];gdi.CreateCompatibleBitmap.restype=wintypes.HBITMAP
    gdi.SelectObject.argtypes=[wintypes.HDC,wintypes.HGDIOBJ];gdi.SelectObject.restype=wintypes.HGDIOBJ
    gdi.BitBlt.argtypes=[wintypes.HDC,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.HDC,ctypes.c_int,ctypes.c_int,wintypes.DWORD]
    gdi.GetDIBits.argtypes=[wintypes.HDC,wintypes.HBITMAP,wintypes.UINT,wintypes.UINT,ctypes.c_void_p,ctypes.c_void_p,wintypes.UINT]
    gdi.DeleteObject.argtypes=[wintypes.HGDIOBJ];gdi.DeleteDC.argtypes=[wintypes.HDC]
    hwnd=window.winfo_id();width=window.winfo_width();height=window.winfo_height()
    dc=user.GetDC(hwnd);memory=gdi.CreateCompatibleDC(dc);bitmap=gdi.CreateCompatibleBitmap(dc,width,height);old=gdi.SelectObject(memory,bitmap)
    try:
        assert gdi.BitBlt(memory,0,0,width,height,dc,0,0,0x00CC0020)
        gdi.SelectObject(memory,old)
        header=ctypes.create_string_buffer(struct.pack('<IiiHHIIiiII',40,width,-height,1,32,0,width*height*4,0,0,0,0))
        buffer=ctypes.create_string_buffer(width*height*4)
        assert gdi.GetDIBits(dc,bitmap,0,height,buffer,header,0)==height
        raw=buffer.raw;rgb=bytearray(width*height*3)
        rgb[0::3]=raw[2::4];rgb[1::3]=raw[1::4];rgb[2::3]=raw[0::4]
        scan=b''.join(b'\0'+rgb[y*width*3:(y+1)*width*3] for y in range(height))
        def chunk(tag,data):return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
        png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(scan,9))+chunk(b'IEND',b'')
        path.write_bytes(png)
        if '--emit-screenshots' in sys.argv:
            data=base64.b64encode(png).decode('ascii')
            print('DESKTOP_PREVIEW_BEGIN '+path.name,flush=True)
            for offset in range(0,len(data),12000):print('DESKTOP_PREVIEW_DATA '+data[offset:offset+12000],flush=True)
            print('DESKTOP_PREVIEW_END '+path.name,flush=True)
    finally:
        gdi.DeleteObject(bitmap);gdi.DeleteDC(memory);user.ReleaseDC(hwnd,dc)


def synthetic_drawing(store):
    nodes=[store.add_node(name,x,y) for name,x,y in (
        ('예시 끝단 A',100,170),('샘플 함체 01',330,170),('샘플 함체 02',560,170),('예시 끝단 B',790,170),
        ('예시 끝단 C',330,430),('예시 끝단 D',560,430))]
    cables=[store.add_cable(nodes[a],nodes[b],name,'12C','기설') for a,b,name in (
        (0,1,'SAMPLE-A'),(1,2,'SAMPLE-B'),(2,3,'SAMPLE-C'),(1,4,'SAMPLE-D'),(2,5,'SAMPLE-E'))]
    for index in (1,2,3):
        store.update_core(cables[0],index,('SAMPLE-100'+str(index),'예시 회선 '+str(index),'normal','','on' if index==1 else 'unknown'))
        store.connect(nodes[1],(cables[0],index),(cables[1],index))
        if index!=2:store.connect(nodes[2],(cables[1],index),(cables[2],index))
    store.update_core(cables[0],4,('SAMPLE-OFF','예시 미사용 회선','normal','','off'))
    store.update_core(cables[0],5,('임시-5','예시 임시 코어','normal','','unknown'))
    return nodes,cables


def inspect_layout(app):
    for width,height in ((1450,900),(1000,700)):
        app.geometry(f'{width}x{height}+0+0')
        for _ in range(3):app.update()
        for toolbar in (app.drawing_toolbar,app.utility_toolbar):
            assert toolbar.winfo_width()<=app.winfo_width()
            for control in toolbar.controls:
                assert control.winfo_ismapped()
                assert 0<=control.winfo_x() and control.winfo_x()+control.winfo_width()<=toolbar.winfo_width(),control.cget('text')
                assert control.winfo_y()+control.winfo_height()<=toolbar.winfo_height()
        assert app.canvas.winfo_height()>=400,(width,app.canvas.winfo_height())
        assert app.dashboard_frame.winfo_width()<=370,app.dashboard_frame.winfo_width()
        assert app.dashboard_frame.winfo_x()>=0
        for button in app.workflow_buttons.values():assert button.winfo_width()>=140
        if width==1000:screenshot(app,Path('dist')/'v89-desktop-compact.png')


def main():
    if sys.platform!='win32':
        print('Windows desktop presentation gate runs on the Windows release runner.');return
    faulthandler.dump_traceback_later(120,exit=True)
    Path('dist').mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'TELECOM_APP_HOME':temp}), \
         patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'askyesno',return_value=True), \
         patch.object(code['messagebox'],'askyesnocancel',return_value=True),patch.object(code['messagebox'],'showerror') as error:
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(str(a))
        try:
            print('DESIGN: initial controls',flush=True)
            nodes,cables=synthetic_drawing(app.store);assert app.load_scenario('before');s=app.store
            app.deiconify();app.update();app.fit_view();app.update()
            baseline=(wf.plan_snapshot(s.conn),wf.state(s),s.history_rows())
            assert code['ttk'].Style(app).theme_use()=='clam'
            assert float(app.completion_bar.cget('value'))==wf.completion_report(s)['rate']
            assert app.work_progress_incomplete.cget('fg')=='#c62828'
            inspect_layout(app);app.geometry('1450x900+0+0');app.update();app.fit_view();app.update()
            app.metrics_details_button.invoke();app.update();assert app.work_progress_note.winfo_ismapped()
            app.metrics_details_button.invoke();app.update();assert not app.work_progress_note.winfo_ismapped()
            app.mode_buttons['hamche'].invoke();assert app.mode=='hamche';assert app.mode_buttons['hamche'].cget('style')=='Active.Tool.TButton'
            app.mode_buttons['select'].invoke();assert app.mode=='select'
            app.tools_toggle_button.invoke();app.update();assert app.advanced_tools_frame.winfo_ismapped()
            app.tools_toggle_button.invoke();app.update();assert not app.advanced_tools_frame.winfo_ismapped()
            screenshot(app,Path('dist')/'v89-desktop.png')
            print('DESIGN: cable selection and drafts',flush=True)
            dialog=code['CableDialog'](app,s,cables[0]);app.update()
            dialog.tree.selection_set('2');app.update()
            assert dialog.completion_reason.get()
            dialog.id_var.set('수정 중인 케이블 이름');dialog.lot_var.set('입력 중인 LOT')
            app.refresh();app.update()
            assert dialog.id_var.get()=='수정 중인 케이블 이름' and dialog.lot_var.get()=='입력 중인 LOT'
            assert 'error' in dialog.tree.tag_names() and 'signal_on' in dialog.tree.tag_names()
            assert dialog.tree.tag_configure('signal_on','foreground')=='#d00000'
            dialog.id_var.set('SAMPLE-A');dialog.lot_var.set('')
            screenshot(dialog,Path('dist')/'v89-cable-editor.png');dialog.destroy()
            print('DESIGN: enclosure table and selection',flush=True)
            node=code['NodeDialog'](app,s,nodes[1]);app.update()
            node.left_var.set(next(k for k,v in node.by_label.items() if v==cables[0]))
            node.right_var.set(next(k for k,v in node.by_label.items() if v==cables[1]));node.reload_all();app.update()
            assert node.save_button.cget('style')=='Primary.TButton'
            node.left_tree.selection_set('1');app.update()
            screenshot(node,Path('dist')/'v89-enclosure-editor.png');node.destroy()
            assert (wf.plan_snapshot(s.conn),wf.state(s),s.history_rows())==baseline
            assert not errors and not error.called,(errors,error.call_args)
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows V89 responsive controls, semantic core colors, progress details, editor drafts and non-mutating visual refresh')


if __name__=='__main__':main()
