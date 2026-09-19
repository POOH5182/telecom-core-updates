"""Familiar, modeless telecom ledgers backed only by a reference snapshot."""


REFERENCE_DETAIL_COLUMNS=('state','signal','number','core_id','detail','cable','start','end')
REFERENCE_DETAIL_HEADINGS=('상태·메모','신호','번호','코어ID','코어내역','케이블 / 포트','시작측 접속','끝측 접속')


def reference_detail_rows(store,kind,key):
    """A route follows physical splices, including mismatched and blank IDs."""
    if kind=='route':
        slots=store.component(tuple(key))
        return [row for row in reference_core_rows(store,'all',None) if row['slot'] in slots]
    return reference_core_rows(store,kind,key)


def close_reference_details(view):
    for dialog in list(getattr(view,'_reference_details',{}).values()):
        try:dialog.destroy()
        except tk.TclError:pass
    view._reference_details={}


def reference_detail_shortcuts(dialog):
    # These widgets live under the same Tcl root as the working drawing. Never
    # let a read-only popup's save/delete/undo reach the main bind_all handlers.
    for sequence in ('<Control-s>','<Control-S>','<Control-z>','<Control-Z>',
                     '<Control-y>','<Control-Y>','<Delete>'):
        dialog.bind(sequence,lambda e:'break')


class ReferenceDetailDialog(RememberedToplevel):
    def __init__(self,view,kind,key,parent=None):
        self._stage_kind=view.source_kind;self._stage_reference=True;self.reference_context=True
        super().__init__(parent or view,position_family='ReferenceDetail:'+kind)
        self.view=view;self.app=view.app;self.store=view.store;self.source_kind=view.source_kind
        self.kind=kind;self.key=key;self._closed=False;self._find_signature=None;self._find_index=-1;self._find_job=None
        self.rows=reference_detail_rows(self.store,kind,key);self.trees=[];self.row_map={};self.active_tree=None
        self.find_text=tk.StringVar();self.notice=tk.StringVar();self.selection_text=tk.StringVar(value='코어를 선택하면 실제 접속 상대를 확인할 수 있습니다.')
        self.geometry('1200x760' if kind=='node' else '1100x730');self.minsize(760,480)
        self._set_heading()
        # Pack persistent actions before the expanding table to keep them
        # available on a short monitor or when a user reduces this window.
        footer=ttk.Frame(self,padding=(10,6));footer.pack(side='bottom',fill='x')
        self.selection_label=ttk.Label(footer,textvariable=self.selection_text,wraplength=1000,justify='left')
        self.selection_label.pack(fill='x',pady=(0,4))
        self.selection_label.bind('<Configure>',lambda e:self.selection_label.configure(wraplength=max(220,e.width-12)))
        buttons=FlowToolbar(footer);buttons.pack(fill='x')
        for text,command in (
            ('선택 행 복사',self.copy_selected),('코어ID 복사',lambda:self.copy_selected(column='core_id')),
            ('코어내역 복사',lambda:self.copy_selected(column='detail')),
            ('실제 연결 경로',self.open_route),('도면에서 보기',self.show_on_drawing)):
            buttons.add(ttk.Button(buttons,text=text,command=command))
        buttons.add(ttk.Button(buttons,text='닫기',command=self.destroy))
        ttk.Label(footer,textvariable=self.notice,foreground='#475569').pack(fill='x',pady=(4,0))
        search=ttk.Frame(self,padding=(10,5));search.pack(fill='x')
        ttk.Label(search,text='코어ID 찾기').pack(side='left')
        self.find_entry=ttk.Entry(search,textvariable=self.find_text,width=28);self.find_entry.pack(side='left',fill='x',expand=True,padx=6)
        self.find_entry.bind('<Return>',self.find_next)
        self.find_entry.bind('<Shift-Return>',lambda e:self.find_next(direction=-1))
        self._find_trace=self.find_text.trace_add('write',self.queue_find)
        ttk.Button(search,text='찾기 / 다음',command=self.find_next).pack(side='left')
        ttk.Button(search,text='목록 전체 복사',command=lambda:self.copy_selected(all_rows=True)).pack(side='left',padx=(6,0))
        if kind=='node':self._build_node()
        else:
            self.tree=self._make_tree(self);self.tree.master.pack(fill='both',expand=True,padx=10,pady=4)
            self._fill_tree(self.tree,self.rows)
        reference_detail_shortcuts(self)
        for sequence in ('<Control-f>','<Control-F>'):self.bind(sequence,self.focus_find)
        self.bind('<Escape>',self.close_key);self.protocol('WM_DELETE_WINDOW',self.destroy)
        self.notice.set(f'{len(self.rows)}개 선번 · Ctrl+F 찾기 · Ctrl/Shift로 여러 행 선택 · Ctrl+C 복사')

    def _set_heading(self):
        store=self.store;kind=self.kind;key=self.key
        if kind=='node':
            row=dict(store.node(key));extra=self._extra(row)
            label={'hamche':'함체','rn':'RN','sub':'가입자'}.get(row.get('type'),'시설')
            self.title(label+' '+str(row.get('name') or '')+' 내역')
            fields=[(label+'명',row.get('name',''))]
            if row.get('type')=='hamche':fields.extend((('함체규격',extra.get('hamcheSpec','')),('함체ID',extra.get('hamcheId',''))))
            if row.get('type')=='rn':fields.extend((('RN ID',extra.get('rnId','')),('전산화번호',extra.get('rnComputerNo',''))))
        elif kind=='cable':
            row=dict(store.cable(key));extra=self._extra(row);self.title('케이블 '+str(row.get('cable_id') or row.get('spec') or '')+' 내역')
            fields=[('케이블ID',row.get('cable_id','')),('규격 / 상태',str(row.get('spec') or '')+' / '+str(row.get('status') or '')),('LOT NO.',extra.get('lotNo',''))]
            names=[store.node(row[n]) for n in ('n1id','n2id')]
            fields.append(('연결구간',' ↔ '.join(str(n['name']) if n else '?' for n in names)))
        elif kind=='route':
            self.title('코어 실제 연결 경로');fields=[('선택 선번',store._slot_title(*key)),('실제 접속',f'{len(self.rows)}개 선번')]
        else:
            self.title('코어 '+str(key)+' 내역');fields=[('코어ID',key),('배정 위치',f'{len(self.rows)}개 선번')]
        header=ttk.Frame(self,padding=(10,8));header.pack(fill='x')
        self.header_entries=[]
        for index,(label,value) in enumerate(fields):
            line=ttk.Frame(header);line.pack(fill='x',pady=2)
            ttk.Label(line,text=label,width=13).pack(side='left')
            entry=ttk.Entry(line);entry.insert(0,'' if value is None else str(value));entry.configure(state='readonly')
            entry.pack(side='left',fill='x',expand=True);self.header_entries.append(entry)
        if kind=='node':
            ttk.Button(header,text='코어 연결도',command=self.open_node_diagram).pack(anchor='w',pady=(5,0))

    @staticmethod
    def _extra(row):
        try:value=json.loads(row.get('extra_json') or '{}')
        except (TypeError,ValueError):return {}
        return value if isinstance(value,dict) else {}

    def _build_node(self):
        self.by_label={};seen=set()
        for row in self.rows:
            owner=row['slot'][0]
            if owner in seen:continue
            seen.add(owner)
            if owner.startswith('PORT:'):label=row['values'][0]
            else:
                cable=dict(self.store.cable(owner));remote=cable['n2id'] if cable['n1id']==self.key else cable['n1id'];node=self.store.node(remote)
                label=str(cable.get('cable_id') or '(ID 없음)')+' · '+str(cable.get('spec') or '')+' → '+str(node['name'] if node else '?')
            original=label;number=2
            while label in self.by_label:label=original+f' ({number})';number+=1
            self.by_label[label]=owner
        self.left_var=tk.StringVar();self.right_var=tk.StringVar()
        panes=ttk.Panedwindow(self,orient='horizontal');panes.pack(fill='both',expand=True,padx=10,pady=4)
        for side,var in (('left',self.left_var),('right',self.right_var)):
            panel=ttk.Frame(panes);panes.add(panel,weight=1)
            selector=ttk.Frame(panel,padding=(0,0,4,6));selector.pack(fill='x')
            combo=ttk.Combobox(selector,textvariable=var,values=tuple(self.by_label),state='readonly',width=20)
            combo.pack(fill='x',expand=True);combo.bind('<<ComboboxSelected>>',lambda e,s=side:self.reload_side(s))
            tree=self._make_tree(panel);tree.master.pack(fill='both',expand=True)
            tree.configure(displaycolumns=('state','signal','number','core_id','detail','start'))
            tree.heading('start',text='이 함체 접속')
            setattr(self,side+'_tree',tree);setattr(self,side+'_combo',combo)
        labels=list(self.by_label)
        if labels:self.left_var.set(labels[0]);self.right_var.set(labels[min(1,len(labels)-1)])
        self.reload_side('left');self.reload_side('right')
        self.active_tree=self.left_tree

    def _make_tree(self,parent):
        frame=ttk.Frame(parent);frame.columnconfigure(0,weight=1);frame.rowconfigure(0,weight=1)
        tree=SortableTreeview(frame,columns=REFERENCE_DETAIL_COLUMNS,show='headings',selectmode='extended')
        for name,label,width in zip(REFERENCE_DETAIL_COLUMNS,REFERENCE_DETAIL_HEADINGS,(110,58,52,130,230,165,250,250)):
            tree.heading(name,text=label);tree.column(name,width=width,minwidth=40,stretch=name=='detail')
        tree.grid(row=0,column=0,sticky='nsew')
        vs=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);vs.grid(row=0,column=1,sticky='ns')
        hs=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview);hs.grid(row=1,column=0,sticky='ew')
        tree.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
        tree.bind('<<TreeviewSelect>>',lambda e,t=tree:self.selected(t))
        tree.bind('<FocusIn>',lambda e,t=tree:self._activate_tree(t))
        tree.bind('<Double-Button-1>',lambda e:self.open_route())
        for sequence in ('<Control-c>','<Control-C>'):tree.bind(sequence,self.copy_selected)
        for sequence in ('<Control-a>','<Control-A>'):tree.bind(sequence,lambda e,t=tree:self.select_all(t))
        tree.tag_configure('cancel',foreground='#777777');tree.tag_configure('error',foreground='#b91c1c')
        tree.tag_configure('on',background='#ecfdf5')
        self.trees.append(tree);self.row_map[tree]={}
        if self.active_tree is None:self.active_tree=tree
        return tree

    def _fill_tree(self,tree,rows):
        tree.delete(*tree.get_children());mapping=self.row_map[tree]={}
        for index,row in enumerate(rows):
            cable,number,core_id,detail,signal,state,start,end=row['values'];iid=str(index)
            if self.kind=='node':
                owner=row['slot'][0]
                if not owner.startswith('PORT:') and self.store.cable(owner)['n2id']==self.key:start,end=end,start
            values=(state,signal,number,core_id,detail,cable,start,end)
            tags=('cancel',) if '해지' in state and '해지예상' not in state else ('error',) if '오류' in state else ('on',) if signal=='ON' else ()
            tree.insert('','end',iid=iid,values=values,tags=tags);mapping[iid]=row

    def reload_side(self,side):
        owner=self.by_label.get(getattr(self,side+'_var').get());tree=getattr(self,side+'_tree')
        self._fill_tree(tree,[r for r in self.rows if r['slot'][0]==owner]);self._find_signature=None

    def _activate_tree(self,tree):self.active_tree=tree

    def selected(self,tree):
        self.active_tree=tree;selected=tree.selection()
        if not selected:return
        row=self.row_map[tree].get(selected[0])
        if row:
            v=row['values'];self.selection_text.set(v[0]+' / '+v[1]+' · '+(v[2] or '(ID 없음)')+'\n'+v[6]+('  ↔  '+v[7] if v[7] else ''))

    def select_all(self,tree):
        self.active_tree=tree;tree.selection_set(tree.get_children());return 'break'

    def focus_find(self,event=None):
        self.find_entry.focus_set();self.find_entry.selection_range(0,'end');return 'break'

    def queue_find(self,*args):
        if self._find_job is not None:self.after_cancel(self._find_job)
        self._find_job=self.after(180,lambda:self.find_next(direction=0))

    def find_next(self,event=None,direction=1):
        if self._find_job is not None:self.after_cancel(self._find_job);self._find_job=None
        query=self.find_text.get().strip().casefold()
        matches=[row for row in self.rows if query and query in str(row['values'][2]).casefold()]
        if not matches:self.notice.set('일치하는 코어ID가 없습니다.' if query else '찾을 코어ID를 입력하세요.');return 'break'
        signature=(query,tuple(row['slot'] for row in matches))
        self._find_index=(self._find_index+direction)%len(matches) if signature==self._find_signature else 0
        self._find_signature=signature;wanted=matches[self._find_index]
        tree=self.active_tree or self.trees[0]
        if self.kind=='node':
            side='right' if tree is self.right_tree else 'left';var=getattr(self,side+'_var')
            label=next(label for label,owner in self.by_label.items() if owner==wanted['slot'][0])
            if var.get()!=label:var.set(label);self.reload_side(side);self._find_signature=signature
        for iid,row in self.row_map[tree].items():
            if row['slot']==wanted['slot']:
                tree.selection_set(iid);tree.focus(iid);tree.see(iid);tree.xview_moveto(0);self.selected(tree);break
        self.notice.set(f'{self._find_index+1}/{len(matches)} · '+wanted['values'][0]+' / '+wanted['values'][1]);return 'break'

    def copy_selected(self,event=None,column=None,all_rows=False):
        tree=getattr(event,'widget',None) if event else None
        if tree not in self.trees:tree=self.active_tree
        if tree is None:return 'break'
        rows=tree.get_children() if all_rows else [iid for iid in tree.get_children() if iid in tree.selection()]
        if not rows:self.notice.set('복사할 코어 행을 선택하세요.');return 'break'
        columns=(column,) if column else REFERENCE_DETAIL_COLUMNS
        text=worklist_clipboard([[tree.set(iid,c) for c in columns] for iid in rows],
                                [tree.heading_text(c) for c in columns] if all_rows else None)
        if column and len(rows)==1:text=text.removesuffix('\n')
        self.clipboard_clear();self.clipboard_append(text);self.notice.set(f'{len(rows)}개 행 복사 완료');return 'break'

    def _selected_row(self):
        tree=self.active_tree
        if tree is not None and tree.selection():return self.row_map[tree].get(tree.selection()[0])
        self.notice.set('코어를 먼저 선택하세요.');return None

    def open_route(self):
        row=self._selected_row()
        if row:return open_reference_detail(self.view,'route',row['slot'],parent=self)

    def show_on_drawing(self):
        row=self._selected_row()
        if not row:return
        owner=row['slot'][0];kind='node' if owner.startswith('PORT:') else 'cable';key=owner[5:] if kind=='node' else owner
        self.view.select_item(kind,key,center=True);self.view.lift()

    def open_node_diagram(self):
        token=('diagram',self.key);registry=self.view._reference_details;existing=registry.get(token)
        if existing is not None and existing.winfo_exists():existing.deiconify();existing.lift();return existing
        diagram=NodeConnectionDiagramDialog(self,self.store,self.key)
        # The established connection diagram is read-only. Its parent must be
        # a pinned detail/viewer, never the live App, for validity checks.
        reference_detail_shortcuts(diagram)
        for sequence in ('<Control-f>','<Control-F>'):diagram.bind(sequence,lambda e:self.focus_find())
        diagram.bind('<Escape>',lambda e:(diagram.show_all(),'break')[1])
        registry[token]=diagram
        diagram.bind('<Destroy>',lambda e:registry.pop(token,None) if e.widget is diagram else None,add='+')
        return diagram

    def close_key(self,event=None):self.destroy();return 'break'

    def destroy(self):
        if self._closed:return
        self._closed=True;registry=getattr(self.view,'_reference_details',{})
        if self._find_job is not None:self.after_cancel(self._find_job);self._find_job=None
        self.find_text.trace_remove('write',self._find_trace)
        if registry.get((self.kind,self.key)) is self:registry.pop((self.kind,self.key),None)
        super().destroy()


def open_reference_detail(view,kind,key,parent=None):
    if view.store is None:return None
    if kind=='node' and view.store.node(key) is None:return None
    if kind=='cable' and view.store.cable(key) is None:return None
    if kind=='route':key=tuple(key)
    if kind not in ('node','cable','core','route'):return None
    registry=getattr(view,'_reference_details',None)
    if registry is None:registry=view._reference_details={}
    existing=registry.get((kind,key))
    if existing is not None and existing.winfo_exists():existing.deiconify();existing.lift();return existing
    dialog=ReferenceDetailDialog(view,kind,key,parent=parent);registry[(kind,key)]=dialog
    return dialog
