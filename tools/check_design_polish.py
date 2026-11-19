"""V206: whole-app visual polish. Theme-only: secondary buttons get a light
fill and a visible thin border, toolbar buttons stay quiet (flat), the toolbar
delete keeps red text without a box, the cable dialog choice buttons are flat
(no 3D bevel) and the header uses the refined navy. Meanings are unchanged:
stage colors, ON/OFF/error colors and the selected-choice blue."""
import os
import sys
import tempfile
from unittest.mock import patch

from check_field_survey import code, wf


def styles():
    tk=code['tk'];ttk=code['ttk']
    root=tk.Tk();root.withdraw()
    try:
        wf.install_desktop_theme(root);style=ttk.Style(root)
        colors=wf.DESKTOP_COLORS
        assert style.theme_use()=='clam'
        assert style.lookup('TButton','bordercolor')==colors['border'],style.lookup('TButton','bordercolor')
        assert style.lookup('TButton','background')==colors['field']
        assert style.lookup('TButton','relief')=='solid'
        assert style.lookup('Tool.TButton','relief')=='flat'
        assert style.lookup('Tool.TButton','bordercolor')==colors['surface']
        assert style.lookup('Danger.Tool.TButton','foreground')==colors['danger']
        assert style.lookup('Danger.Tool.TButton','relief')=='flat'
        assert style.lookup('Danger.TButton','foreground')==colors['danger']
        assert style.lookup('Primary.TButton','background')==colors['accent']
        assert style.lookup('Treeview','rowheight') in (27,'27')
        assert style.lookup('Treeview.Heading','background')=='#1c3150'
        assert style.lookup('Treeview.Heading','foreground')=='#ffffff'
        assert style.lookup('Active.Tool.TButton','background')==colors['accent']
        assert style.lookup('Hero.TFrame','background')==colors['navy']
        assert style.lookup('Status.TFrame','background')==colors['navy']
        # semantic colors kept
        assert wf.STAGE_WINDOW_COLORS=={'gis':'#2563eb','before':'#15803d','after':'#c2410c'}
        assert code['CHOICE_ON'][1]=='#ffffff' and code['CHOICE_ON'][0]!=code['CHOICE_OFF'][0]
    finally:root.destroy()


def ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    import faulthandler
    faulthandler.dump_traceback_later(120,exit=True)
    mb=code['messagebox']
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'TELECOM_APP_HOME':temp}), \
         patch.object(mb,'showinfo'),patch.object(mb,'askyesno',return_value=True), \
         patch.object(mb,'askyesnocancel',return_value=True),patch.object(mb,'showerror'):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(str(a))
        try:
            app.deiconify();app.update()
            assert app.desktop_header.cget('bg')=='#101d33'
            delete=app.drawing_tools.buttons.get('delete')
            if delete is not None:assert delete.cget('style')=='Danger.Tool.TButton'
            app.update_workflow_stage();kind=app.scenario_kind()
            active=app.workflow_buttons[kind]
            assert active.cget('bg')=='#ffffff' and active.cget('fg')==wf.STAGE_WINDOW_COLORS[kind]
            assert app.workflow_strips[kind].cget('bg')==wf.STAGE_WINDOW_COLORS[kind]
            assert all(app.workflow_strips[k].cget('bg')=='#22395c' for k in app.workflow_strips if k!=kind)
            assert app.desktop_statusbar.cget('style')=='Status.TFrame'
            a=app.store.add_node('A',0,0);b=app.store.add_node('B',200,0)
            cable=app.store.add_cable(a,b,'C1','12C','기설')
            dialog=code['CableDialog'](app,app.store,cable);app.update()
            flats=[w for w in dialog.winfo_children()]
            pending=list(flats);buttons=[]
            while pending:
                w=pending.pop();pending.extend(w.winfo_children())
                if isinstance(w,code['tk'].Button) and w.cget('text') in ('기설','신설','12C'):buttons.append(w)
            assert buttons and all(w.cget('relief')=='flat' for w in buttons)
            assert any(w.cget('bg')==code['CHOICE_ON'][0] for w in buttons if w.cget('text')=='기설')
            dialog.destroy();app.update()
            assert not errors,errors
        finally:app.on_close()


if __name__=='__main__':
    styles();ui()
    print('PASS V206 design polish: navy dialog headings and table headers, filled active tool and tab, stage strips, visible buttons, semantic colors kept')
