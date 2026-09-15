"""Shared desktop presentation. No drawing, state, or workflow mutations."""
from tkinter import font as tkfont


DESKTOP_COLORS = {
    'ink':'#192b46', 'muted':'#64748b', 'navy':'#14243d',
    'accent':'#315eac', 'hover':'#254b8c', 'soft':'#edf3fc',
    'surface':'#ffffff', 'page':'#f3f6fa', 'line':'#dbe3ed',
    'success':'#16734b', 'danger':'#c62828',
}


def install_desktop_theme(root):
    """Install per-Tk-interpreter styles before constructing any controls."""
    if getattr(root,'_desktop_theme_ready',False):return
    root._desktop_theme_ready=True
    colors=DESKTOP_COLORS
    family='Malgun Gothic' if os.name=='nt' else 'Noto Sans CJK KR'
    root._desktop_font=family
    for name in ('TkDefaultFont','TkTextFont','TkMenuFont','TkHeadingFont'):
        tkfont.nametofont(name,root=root).configure(family=family,size=9)
    root.configure(background=colors['page'])
    root.option_add('*Font',(family,9))
    for pattern,value in {
        '*Toplevel.background':colors['surface'], '*Frame.background':colors['surface'],
        '*Label.background':colors['surface'], '*Label.foreground':colors['ink'],
        '*Entry.background':colors['surface'], '*Entry.foreground':colors['ink'],
        '*Entry.selectBackground':colors['soft'], '*Entry.selectForeground':colors['ink'],
        '*Text.background':colors['surface'], '*Text.foreground':colors['ink'],
        '*Text.selectBackground':colors['soft'], '*Text.selectForeground':colors['ink'],
        '*Text.relief':'flat', '*Text.borderWidth':1,
        '*Text.highlightBackground':colors['line'], '*Text.highlightColor':colors['accent'],
        '*Menu.background':colors['surface'], '*Menu.foreground':colors['ink'],
        '*Menu.activeBackground':colors['soft'], '*Menu.activeForeground':colors['accent'],
        '*Menu.relief':'flat', '*Menu.borderWidth':1,
    }.items():root.option_add(pattern,value)
    style=ttk.Style(root);style.theme_use('clam')
    style.configure('.',font=(family,9),background=colors['surface'],foreground=colors['ink'],
                    bordercolor=colors['line'],lightcolor=colors['surface'],darkcolor=colors['line'])
    style.configure('TFrame',background=colors['surface'])
    style.configure('Page.TFrame',background=colors['page'])
    style.configure('TLabel',background=colors['surface'],foreground=colors['ink'])
    style.configure('Muted.TLabel',foreground=colors['muted'])
    style.configure('Title.TLabel',font=(family,16,'bold'))
    style.configure('Section.TLabel',font=(family,10,'bold'))
    style.configure('TLabelframe',background=colors['surface'],borderwidth=1,relief='solid')
    style.configure('TLabelframe.Label',font=(family,9,'bold'),foreground=colors['muted'],padding=(0,3))
    style.configure('TButton',padding=(10,6),relief='flat',borderwidth=1,background=colors['surface'],
                    foreground=colors['ink'],focuscolor=colors['accent'],focusthickness=1)
    style.map('TButton',background=[('disabled','#f4f6f9'),('pressed','#dfe8f5'),('active','#f0f4fa')],
              foreground=[('disabled','#8b98ab')],bordercolor=[('focus',colors['accent']),('active','#b6c7df')])
    for name,bg,fg in [('Primary.TButton',colors['accent'],'#ffffff'),
                       ('Active.Tool.TButton',colors['soft'],colors['accent']),
                       ('Header.TButton','#294468','#ffffff')]:
        style.configure(name,background=bg,foreground=fg,bordercolor=bg,font=(family,9,'bold'))
        style.map(name,background=[('disabled','#e7ebf1'),('pressed',colors['hover']),('active',colors['accent'])],
                  foreground=[('disabled','#8794a6'),('pressed','#ffffff'),('active','#ffffff')])
    style.configure('Danger.TButton',foreground=colors['danger'])
    style.configure('Tool.TButton',padding=(9,5))
    style.configure('TMenubutton',padding=(10,6),relief='flat',arrowsize=10)
    style.map('TMenubutton',background=[('active',colors['soft'])])
    for name in ('TEntry','TCombobox','TSpinbox'):
        style.configure(name,padding=(6,5),fieldbackground=colors['surface'],borderwidth=1,
                        foreground=colors['ink'],selectbackground=colors['soft'],selectforeground=colors['ink'])
        style.map(name,bordercolor=[('focus',colors['accent'])],
                  fieldbackground=[('readonly','#f6f8fc'),('disabled','#f0f3f8')],
                  foreground=[('disabled','#7d8da2'),('readonly',colors['ink'])])
    for name in ('TCheckbutton','TRadiobutton'):
        style.configure(name,padding=(2,4),indicatorcolor=colors['surface'])
        style.map(name,background=[('active',colors['surface'])],indicatorcolor=[('selected',colors['accent'])])
    style.configure('TNotebook',background=colors['surface'],borderwidth=0,tabmargins=(0,0,0,0))
    style.configure('TNotebook.Tab',padding=(16,8),background=colors['page'],foreground=colors['muted'])
    style.map('TNotebook.Tab',background=[('selected',colors['soft']),('active','#f5f8fd')],
              foreground=[('selected',colors['accent'])],font=[('selected',(family,9,'bold'))])
    style.configure('Treeview',rowheight=27,font=(family,9),background=colors['surface'],
                    fieldbackground=colors['surface'],borderwidth=1,relief='solid')
    # Keep semantic row foreground tags visible when selected (ON, errors, etc.).
    style.map('Treeview',background=[('selected','#dfeafb')],foreground=[('disabled','#8b98ab')])
    style.configure('Treeview.Heading',padding=(8,8),background='#f1f5fa',foreground='#435773',
                    font=(family,9,'bold'),relief='flat',borderwidth=1)
    style.map('Treeview.Heading',background=[('active','#e7eef8')])
    for name in ('Horizontal.TScrollbar','Vertical.TScrollbar'):
        style.configure(name,background='#c5d0df',troughcolor='#f4f7fb',borderwidth=0,arrowsize=11)
        style.map(name,background=[('active','#9babc1'),('pressed','#8599b3')])
    style.configure('TSeparator',background=colors['line'])
    style.configure('Completion.Horizontal.TProgressbar',background=colors['accent'],troughcolor='#eaf0f7',
                    borderwidth=0,lightcolor=colors['accent'],darkcolor=colors['accent'],thickness=6)
    style.configure('Complete.Horizontal.TProgressbar',background=colors['success'],troughcolor='#e9f3ee',
                    borderwidth=0,lightcolor=colors['success'],darkcolor=colors['success'],thickness=6)


class FlowToolbar(ttk.Frame):
    """Wrap existing native controls without removing keyboard or pointer access."""
    def __init__(self,parent,**kwargs):
        super().__init__(parent,**kwargs)
        self.controls=[];self._layout_job=None;self._layout_stamp=None
        self.bind('<Configure>',self.schedule,add='+')
        self.bind('<Destroy>',self.cleanup,add='+')
    def add(self,control):
        self.controls.append(control);self._layout_stamp=None;self.schedule();return control
    def schedule(self,event=None):
        if event is not None and event.widget is not self:return
        if self._layout_job is None:self._layout_job=self.after_idle(self.reflow)
    def reflow(self):
        self._layout_job=None
        if not self.winfo_exists():return
        width=max(300,self.winfo_width());sizes=[(w.winfo_reqwidth(),w.winfo_reqheight()) for w in self.controls]
        stamp=(width,tuple(sizes))
        if self._layout_stamp==stamp:return
        self._layout_stamp=stamp;x=12;y=5;row_height=0
        for control,(w,h) in zip(self.controls,sizes):
            if x>12 and x+w>width-12:y+=row_height+5;x=12;row_height=0
            control.place(x=x,y=y,width=min(w,width-24),height=h)
            x+=w+6;row_height=max(row_height,h)
        self.configure(height=y+row_height+5)
    def cleanup(self,event=None):
        if event is not None and event.widget is not self:return
        if self._layout_job is not None:
            try:self.after_cancel(self._layout_job)
            except tk.TclError:pass
            self._layout_job=None


def desktop_dialog_heading(parent,title,subtitle=''):
    box=ttk.Frame(parent,padding=(18,14,18,10));box.pack(fill='x')
    ttk.Label(box,text=title,style='Title.TLabel').pack(anchor='w')
    if subtitle:ttk.Label(box,text=subtitle,style='Muted.TLabel').pack(anchor='w',pady=(3,0))
    ttk.Separator(parent).pack(fill='x',padx=18)
    return box


def desktop_lock_image(parent,locked):
    """A crisp native padlock icon, independent of emoji font availability."""
    photo=tk.PhotoImage(master=parent,width=24,height=24)
    ink='#192b46'
    for y in range(12,22):
        left,right=(5,19) if y in (12,21) else (4,20)
        photo.put(ink,to=(left,y,right,y+1))
    if locked:
        for x,y,w,h in ((7,6,2,7),(15,6,2,7),(9,3,6,2),(7,5,3,2),(14,5,3,2)):
            photo.put(ink,to=(x,y,x+w,y+h))
    else:
        for x,y,w,h in ((15,5,2,9),(7,4,2,4),(9,2,6,2),(14,3,2,3)):
            photo.put(ink,to=(x,y,x+w,y+h))
    photo.put('#ffffff',to=(11,15,13,19))
    return photo


def desktop_popup_menu(button,menu):
    try:menu.tk_popup(button.winfo_rootx(),button.winfo_rooty()+button.winfo_height())
    finally:menu.grab_release()


def polish_dialog_actions(window):
    if not window.winfo_exists():return
    pending=[window]
    primary={'저장','저장 (Space)','수정하기','현장 선번 적용','확인한 현장 선번 적용','도면 복사'}
    while pending:
        widget=pending.pop();pending.extend(widget.winfo_children())
        if isinstance(widget,ttk.Button) and not widget.cget('style'):
            text=str(widget.cget('text'))
            if text in primary:widget.configure(style='Primary.TButton')
            elif '삭제' in text:widget.configure(style='Danger.TButton')
