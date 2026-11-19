"""Shared desktop presentation. No drawing, state, or workflow mutations."""
from tkinter import font as tkfont


DESKTOP_COLORS = {
    # V206 정밀 계기판(instrument panel) 톤: 깊은 남색 머리, 맑은 회백 바탕,
    # 하나의 코발트 강조색. 버튼은 얇은 테두리로 '누를 수 있음'이 보이게 한다.
    'ink':'#16233a', 'muted':'#5b6b82', 'navy':'#101d33',
    'accent':'#2f5fc4', 'hover':'#244c9e', 'soft':'#e9f0fc',
    'surface':'#ffffff', 'page':'#f2f4f8', 'line':'#d5dde8',
    'success':'#16734b', 'danger':'#c62828',
    'field':'#f7f9fc', 'border':'#c2cddc', 'header_raise':'#1e3354',
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
    for pattern,value in {
        '*Toplevel.background':colors['surface'], '*Frame.background':colors['surface'],
        '*Label.background':colors['surface'], '*Label.foreground':colors['ink'],
        '*Entry.background':colors['surface'], '*Entry.foreground':colors['ink'],
        '*Entry.selectBackground':colors['soft'], '*Entry.selectForeground':colors['ink'],
        '*Text.background':colors['surface'], '*Text.foreground':colors['ink'],
        '*Text.selectBackground':colors['soft'], '*Text.selectForeground':colors['ink'],
        '*Text.relief':'flat', '*Text.borderWidth':1,
        '*Text.highlightBackground':colors['border'], '*Text.highlightColor':colors['accent'],
        '*Menu.background':colors['surface'], '*Menu.foreground':colors['ink'],
        '*Menu.activeBackground':colors['soft'], '*Menu.activeForeground':colors['accent'],
        '*Menu.relief':'flat', '*Menu.borderWidth':1,
        '*Listbox.background':colors['surface'], '*Listbox.foreground':colors['ink'],
        '*Listbox.selectBackground':'#dbe7fb', '*Listbox.selectForeground':colors['ink'],
        '*Listbox.highlightBackground':colors['border'], '*Listbox.highlightColor':colors['accent'],
    }.items():root.option_add(pattern,value)
    style=ttk.Style(root);style.theme_use('clam')
    style.configure('.',font=(family,9),background=colors['surface'],foreground=colors['ink'],
                    bordercolor=colors['line'],lightcolor=colors['surface'],darkcolor=colors['line'],
                    troughcolor=colors['page'],selectbackground='#dbe7fb',selectforeground=colors['ink'])
    style.configure('TFrame',background=colors['surface'])
    style.configure('Page.TFrame',background=colors['page'])
    style.configure('TLabel',background=colors['surface'],foreground=colors['ink'])
    style.configure('Muted.TLabel',foreground=colors['muted'])
    style.configure('Title.TLabel',font=(family,16,'bold'),foreground=colors['navy'])
    style.configure('Section.TLabel',font=(family,10,'bold'),foreground=colors['navy'])
    style.configure('TLabelframe',background=colors['surface'],borderwidth=1,relief='solid',
                    bordercolor=colors['line'],lightcolor=colors['line'],darkcolor=colors['line'])
    style.configure('TLabelframe.Label',font=(family,9,'bold'),foreground=colors['accent'],padding=(0,3))
    # 기본 버튼: 옅은 바탕 + 얇은 테두리. 예전엔 테두리가 거의 안 보여 글자처럼 보였다.
    style.configure('TButton',padding=(10,6),relief='solid',borderwidth=1,background=colors['field'],
                    foreground=colors['ink'],bordercolor=colors['border'],lightcolor=colors['field'],
                    darkcolor=colors['field'],focuscolor=colors['accent'],focusthickness=1)
    style.map('TButton',background=[('disabled','#f3f5f8'),('pressed','#dce6f6'),('active',colors['soft'])],
              foreground=[('disabled','#97a3b4'),('active',colors['hover'])],
              bordercolor=[('disabled',colors['line']),('focus',colors['accent']),('active','#8fa8d4')],
              lightcolor=[('pressed','#dce6f6'),('active',colors['soft'])],
              darkcolor=[('pressed','#dce6f6'),('active',colors['soft'])])
    for name,bg,fg,edge,hover in [('Primary.TButton',colors['accent'],'#ffffff',colors['hover'],colors['hover']),
                                  ('Active.Tool.TButton',colors['accent'],'#ffffff',colors['hover'],colors['hover']),
                                  ('Header.TButton','#22395c','#ffffff','#35517c','#2c4a76')]:
        style.configure(name,background=bg,foreground=fg,bordercolor=edge,lightcolor=bg,darkcolor=bg,
                        font=(family,9,'bold'))
        style.map(name,background=[('disabled','#e7ebf1'),('pressed',colors['hover']),('active',hover)],
                  foreground=[('disabled','#8794a6'),('pressed','#ffffff'),('active',fg)],
                  bordercolor=[('focus',colors['accent'] if name!='Header.TButton' else '#7ba7f2'),('active',edge)],
                  lightcolor=[('pressed',colors['hover']),('active',hover)],
                  darkcolor=[('pressed',colors['hover']),('active',hover)])
    style.configure('Danger.TButton',foreground=colors['danger'],background=colors['surface'],bordercolor='#efc9c9',
                    lightcolor=colors['surface'],darkcolor=colors['surface'])
    style.map('Danger.TButton',foreground=[('disabled','#c9a3a3'),('active','#a61b1b')],
              background=[('pressed','#f9dede'),('active','#fdeeee')],bordercolor=[('active','#e3a4a4')],
              lightcolor=[('active','#fdeeee')],darkcolor=[('active','#fdeeee')])
    # 도구줄의 '선택 삭제': 빨간 글자만, 테두리 없이(다른 도구 버튼과 같은 무게).
    style.configure('Danger.Tool.TButton',padding=(9,5),relief='flat',foreground=colors['danger'],background=colors['surface'],
                    bordercolor=colors['surface'],lightcolor=colors['surface'],darkcolor=colors['surface'])
    style.map('Danger.Tool.TButton',foreground=[('disabled','#c9a3a3'),('active','#a61b1b')],
              background=[('pressed','#f9dede'),('active','#fdeeee')],bordercolor=[('active','#fdeeee')],
              lightcolor=[('active','#fdeeee')],darkcolor=[('active','#fdeeee')])
    # 도구줄 버튼: 평소엔 바탕과 같은 색(조용하게), 마우스를 올리면 옅게 드러난다.
    style.configure('Tool.TButton',padding=(9,5),relief='flat',background=colors['surface'],bordercolor=colors['surface'],
                    lightcolor=colors['surface'],darkcolor=colors['surface'])
    style.configure('TMenubutton',padding=(10,6),relief='flat',arrowsize=10,background=colors['field'],
                    bordercolor=colors['border'],lightcolor=colors['field'],darkcolor=colors['field'])
    style.map('TMenubutton',background=[('active',colors['soft'])])
    for name in ('TEntry','TCombobox','TSpinbox'):
        style.configure(name,padding=(6,5),fieldbackground=colors['surface'],borderwidth=1,
                        bordercolor=colors['border'],lightcolor=colors['surface'],darkcolor=colors['surface'],
                        foreground=colors['ink'],selectbackground='#dbe7fb',selectforeground=colors['ink'],
                        arrowcolor=colors['muted'])
        style.map(name,bordercolor=[('focus',colors['accent']),('hover','#9fb2cf')],
                  lightcolor=[('focus','#c9d9f5')],
                  fieldbackground=[('readonly',colors['field']),('disabled','#f0f3f8')],
                  foreground=[('disabled','#7d8da2'),('readonly',colors['ink'])],
                  arrowcolor=[('active',colors['accent'])])
    for name in ('TCheckbutton','TRadiobutton'):
        style.configure(name,padding=(2,4),indicatorcolor=colors['surface'],indicatorbackground=colors['surface'],
                        upperbordercolor=colors['border'],lowerbordercolor=colors['border'])
        style.map(name,background=[('active',colors['surface'])],foreground=[('active',colors['hover'])],
                  indicatorcolor=[('selected',colors['accent']),('pressed',colors['soft'])])
    style.configure('TNotebook',background=colors['surface'],borderwidth=0,tabmargins=(0,0,0,0),
                    bordercolor=colors['line'],lightcolor=colors['surface'],darkcolor=colors['line'])
    style.configure('TNotebook.Tab',padding=(16,8),background=colors['page'],foreground=colors['muted'],
                    bordercolor=colors['line'],lightcolor=colors['page'],darkcolor=colors['page'])
    style.map('TNotebook.Tab',background=[('selected',colors['accent']),('active','#e2e9f5')],
              foreground=[('selected','#ffffff'),('active',colors['ink'])],
              bordercolor=[('selected',colors['accent'])],
              lightcolor=[('selected',colors['accent'])],darkcolor=[('selected',colors['accent'])],
              font=[('selected',(family,9,'bold'))])
    style.configure('Treeview',rowheight=27,font=(family,9),background=colors['surface'],
                    fieldbackground=colors['surface'],borderwidth=1,relief='solid',bordercolor=colors['line'],
                    lightcolor=colors['line'],darkcolor=colors['line'])
    # Keep semantic row foreground tags visible when selected (ON, errors, etc.).
    style.map('Treeview',background=[('selected','#dbe7fb')],foreground=[('disabled','#8b98ab')])
    # 표 머리: 진한 남색 띠 + 흰 글자 (모든 코어표에서 머리와 내용이 바로 구분된다)
    style.configure('Treeview.Heading',padding=(8,8),background='#1c3150',foreground='#ffffff',
                    font=(family,9,'bold'),relief='flat',borderwidth=1,bordercolor='#2c4569',
                    lightcolor='#1c3150',darkcolor='#2c4569')
    style.map('Treeview.Heading',background=[('active','#2a4670')],foreground=[('active','#ffffff')],
              lightcolor=[('active','#2a4670')])
    for name in ('Horizontal.TScrollbar','Vertical.TScrollbar'):
        style.configure(name,background='#cbd5e2',troughcolor='#f3f6fa',borderwidth=0,arrowsize=11,
                        bordercolor='#f3f6fa',lightcolor='#cbd5e2',darkcolor='#cbd5e2',arrowcolor=colors['muted'],gripcount=0)
        style.map(name,background=[('active','#9fb0c7'),('pressed','#8599b3')],
                  lightcolor=[('active','#9fb0c7')],darkcolor=[('active','#9fb0c7')])
    style.configure('TSeparator',background=colors['line'])
    style.configure('Hero.TFrame',background=colors['navy'])
    style.configure('Hero.Title.TLabel',background=colors['navy'],foreground='#ffffff',font=(family,16,'bold'))
    style.configure('Hero.Muted.TLabel',background=colors['navy'],foreground='#a9bcd8')
    style.configure('Accent.TFrame',background=colors['accent'])
    style.configure('Status.TFrame',background=colors['navy'])
    style.configure('Status.TLabel',background=colors['navy'],foreground='#c9d6ea')
    style.configure('Status.Muted.TLabel',background=colors['navy'],foreground='#8ea3c2')
    style.configure('Completion.Horizontal.TProgressbar',background=colors['accent'],troughcolor='#e7edf6',
                    borderwidth=0,lightcolor=colors['accent'],darkcolor=colors['accent'],bordercolor='#e7edf6',thickness=6)
    style.configure('Complete.Horizontal.TProgressbar',background=colors['success'],troughcolor='#e7f2ec',
                    borderwidth=0,lightcolor=colors['success'],darkcolor=colors['success'],bordercolor='#e7f2ec',thickness=6)


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


class ScrollableActions(ttk.Frame):
    """A bounded native control panel; wheel/focus scrolling stays inside it."""
    def __init__(self,parent):
        super().__init__(parent)
        self.columnconfigure(0,weight=1);self.rowconfigure(0,weight=1)
        self.canvas=tk.Canvas(self,highlightthickness=0,background=DESKTOP_COLORS['surface'],width=235)
        self.canvas.grid(row=0,column=0,sticky='nsew')
        self.bar=ttk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.bar.grid(row=0,column=1,sticky='ns');self.canvas.configure(yscrollcommand=self.bar.set)
        self.content=ttk.Frame(self.canvas);self.item=self.canvas.create_window(0,0,anchor='nw',window=self.content)
        self.content.bind('<Configure>',self.update_region)
        self.canvas.bind('<Configure>',self.update_width)
        self.canvas.bind('<MouseWheel>',self.wheel)
        self.content.bind('<MouseWheel>',self.wheel)
    def update_region(self,event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox(self.item))
        for child in self.content.winfo_children():
            if getattr(child,'_actions_scroll_bound',False):continue
            child._actions_scroll_bound=True
            child.bind('<MouseWheel>',self.wheel,add='+')
            child.bind('<FocusIn>',lambda e:self.reveal(e.widget),add='+')
    def update_width(self,event):self.canvas.itemconfigure(self.item,width=event.width)
    def wheel(self,event):
        if self.content.winfo_height()>self.canvas.winfo_height():
            self.canvas.yview_scroll(-1 if event.delta>0 else 1,'units')
        return 'break'
    def reveal(self,widget):
        top=self.canvas.canvasy(0);height=self.canvas.winfo_height();y=widget.winfo_y()
        bottom=y+widget.winfo_height();total=max(1,self.content.winfo_height())
        if y<top:self.canvas.yview_moveto(y/total)
        elif bottom>top+height:self.canvas.yview_moveto((bottom-height)/total)


def desktop_dialog_heading(parent,title,subtitle=''):
    # V206: 창 제목을 남색 띠 + 코발트 밑줄로. 높이는 예전(여백+구분선)과 같게 유지한다.
    box=ttk.Frame(parent,padding=(18,14,18,10),style='Hero.TFrame');box.pack(fill='x')
    ttk.Label(box,text=title,style='Hero.Title.TLabel').pack(anchor='w')
    if subtitle:ttk.Label(box,text=subtitle,style='Hero.Muted.TLabel').pack(anchor='w',pady=(3,0))
    ttk.Frame(parent,height=2,style='Accent.TFrame').pack(fill='x')
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
