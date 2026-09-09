"""ID search and read-only drawing navigation, including disconnected core paths."""


def drawing_search(store,query,category='전체'):
    query=str(query or '').strip().casefold()
    if not query:return []
    results=[];nodes={n['id']:dict(n) for n in store.nodes()};cables={c['id']:dict(c) for c in store.cables()}
    def add(kind,identifier,title,location,values,**target):
        if category not in ('전체',kind) and not (category=='시설명' and 'node_id' in target):return
        candidates=[str(v or '').strip().casefold() for v in values]
        if not any(query in value for value in candidates):return
        rank=0 if query in candidates else 1 if any(v.startswith(query) for v in candidates) else 2
        results.append(dict(kind=kind,identifier=identifier,title=title,location=location,rank=rank,**target))
    if category in ('전체','코어ID'):
        grouped={}
        for row in store.all_core_rows():
            cid=str(row['core_id'] or '').strip()
            if cid:grouped.setdefault(cid,[]).append(row)
        for cid,rows in grouped.items():
            aliases=[cid,'임시코어 '+cid[3:],'임시코어'+cid[3:]] if cid.startswith('임시-') else [cid]
            add('코어ID',cid,' / '.join(dict.fromkeys(r['detail'] for r in rows if r['detail'])),f'{len(rows)}곳 · 끊어진 구간 포함 전체 경로',aliases,core_id=cid)
    for nid,node in nodes.items():
        try:extra=json.loads(node['extra_json'] or '{}')
        except (ValueError,TypeError):extra={}
        kind={'hamche':'함체ID','rn':'RNID','sub':'가입자'}.get(node['type'],'시설명')
        identifier=str(extra.get('hamcheId' if node['type']=='hamche' else 'rnId') or '') if node['type'] in ('hamche','rn') else ''
        computer=str(extra.get('rnComputerNo') or '')
        title=node['name'];location=('전산화번호 '+computer) if computer else node['type']
        add(kind,identifier or '(ID 없음)',title,location,[node['name']] if category=='시설명' else [identifier,node['name'],computer],node_id=nid)
    for cid,cable in cables.items():
        a=nodes.get(cable['n1id'],{}).get('name','?');b=nodes.get(cable['n2id'],{}).get('name','?')
        add('케이블ID',cable['cable_id'],cable['spec'] or str(cable['size'])+'C',a+' ↔ '+b,[cable['cable_id']],cable_id=cid)
    return sorted(results,key=lambda r:(r['rank'],r['identifier'].casefold(),r['kind'],r['title'],str(r.get('node_id') or r.get('cable_id') or '')))


def reveal_search_result(app,result,owner=None):
    """Select exact objects and fit the requested core's complete set of routes."""
    store=app.store;namespace=type(app).__init__.__globals__;trace=None
    if result.get('core_id'):
        trace=store.trace_core_paths(result['core_id']);selection=set(trace['highlight'])
        selection.update(r['cable_id'][5:] for r in trace['rows'] if r['cable_id'].startswith('PORT:'))
        if not trace['rows']:return None
    elif result.get('node_id'):
        if not store.node(result['node_id']):return None
        selection={result['node_id']}
    else:
        if not store.cable(result.get('cable_id')):return None
        selection={result['cable_id']}
    points=[]
    for key in selection:
        node=store.node(key);cable=store.cable(key)
        members=[node] if node else [store.node(cable['n1id']),store.node(cable['n2id'])] if cable else []
        points.extend((n['x'],n['y']) for n in members if n)
    if not points:return None
    app.cancel_left_pan();app.mode='select';app.cable_start=None;app.selected=selection
    app.stop_highlight_blink(clear=True);app.update_idletasks()
    minx=min(p[0] for p in points)-100;maxx=max(p[0] for p in points)+100
    miny=min(p[1] for p in points)-100;maxy=max(p[1] for p in points)+100
    width=max(1,app.canvas.winfo_width());height=max(1,app.canvas.winfo_height())
    app.view_scale=max(0.02,min(1.5,width/max(360,maxx-minx),height/max(300,maxy-miny)))
    app.refresh();app.update_idletasks();scale=app.view_scale
    # Include negative coordinates when a drawing has been moved beyond the origin.
    x0=min(0,minx*scale);y0=min(0,miny*scale);x1=max(app.world_w*scale,maxx*scale);y1=max(app.world_h*scale,maxy*scale)
    app.canvas.configure(scrollregion=(x0,y0,x1,y1))
    cx=(minx+maxx)*scale/2;cy=(miny+maxy)*scale/2
    app.canvas.xview_moveto(max(0,(cx-width/2-x0)/max(1,x1-x0)));app.canvas.yview_moveto(max(0,(cy-height/2-y0)/max(1,y1-y0)))
    app.refresh_minimap_viewport()
    if trace:
        view=namespace['combined_trace_view']([trace],colors=('#ff7a00',))
        app.start_highlight_blink(view['cable_colors'],owner=owner,core_labels=namespace['core_path_number_labels'](trace['rows']))
    elif result.get('cable_id'):app.start_highlight_blink({result['cable_id']:'#ff7a00'},owner=owner)
    app.status.set('찾기 · '+result['kind']+' '+result['identifier']+' · '+('전체 코어 경로 선택' if trace else '위치 이동·선택 완료'))
    return trace if trace is not None else {'groups':[]}


class DrawingFindDialog(RememberedToplevel):
    def __init__(self,app,parent=None):
        super().__init__(parent or app);self.app=app;self.store=app.store;self.generation=getattr(self.store,'_view_generation',0)
        self.title('통합 찾기 · Ctrl+F');self.geometry('1120x740');self.minsize(850,560)
        self._previous_grab=self.grab_current();self.transient(parent or app);self.grab_set();self.results=[];self.revision=self.store.data_revision()
        bar=ttk.Frame(self,padding=8);bar.pack(fill='x')
        self.category=tk.StringVar(value='전체');scope=ttk.Combobox(bar,textvariable=self.category,values=('전체','코어ID','함체ID','케이블ID','RNID','시설명'),state='readonly',width=12);scope.pack(side='left')
        self.query=tk.StringVar();self.entry=ttk.Entry(bar,textvariable=self.query,width=48);self.entry.pack(side='left',fill='x',expand=True,padx=6)
        self.entry.bind('<Return>',self.search);scope.bind('<<ComboboxSelected>>',self.search)
        ttk.Button(bar,text='찾기',command=self.search).pack(side='left')
        ttk.Button(bar,text='도면 보기 / 닫기',command=self.destroy).pack(side='right',padx=6)
        ttk.Label(self,text='ID 또는 이름 일부를 입력하고 Enter · 결과를 클릭하면 이동·선택 · 코어ID는 서로 끊어진 구간도 모두 표시합니다.',padding=(8,0,8,6)).pack(fill='x')
        frame=ttk.Frame(self);frame.pack(fill='both',expand=True,padx=8)
        self.tree=SortableTreeview(frame,columns=('kind','id','title','location'),show='headings',height=8)
        for key,label,width in zip(('kind','id','title','location'),('구분','ID','이름·코어내역','위치 / 경로'),(100,180,260,440)):
            self.tree.heading(key,text=label);self.tree.column(key,width=width,minwidth=70)
        self.tree.grid(row=0,column=0,sticky='nsew');frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        sy=ttk.Scrollbar(frame,orient='vertical',command=self.tree.yview);sy.grid(row=0,column=1,sticky='ns')
        sx=ttk.Scrollbar(frame,orient='horizontal',command=self.tree.xview);sx.grid(row=1,column=0,sticky='ew');self.tree.configure(xscrollcommand=sx.set,yscrollcommand=sy.set)
        self.tree.bind('<<TreeviewSelect>>',self.reveal);self.tree.bind('<Return>',self.reveal)
        self.info=tk.StringVar(value='현재 열려 있는 도면에서 검색합니다.');ttk.Label(self,textvariable=self.info,padding=8,wraplength=1060).pack(fill='x')
        frame=ttk.Frame(self);frame.pack(fill='both',expand=True,padx=8,pady=(0,8))
        self.diagram=tk.Canvas(frame,bg='white',height=260,highlightthickness=0);self.diagram.grid(row=0,column=0,sticky='nsew')
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        sy=ttk.Scrollbar(frame,orient='vertical',command=self.diagram.yview);sy.grid(row=0,column=1,sticky='ns')
        sx=ttk.Scrollbar(frame,orient='horizontal',command=self.diagram.xview);sx.grid(row=1,column=0,sticky='ew');self.diagram.configure(xscrollcommand=sx.set,yscrollcommand=sy.set)
        self.bind('<Escape>',lambda e:self.destroy());self.protocol('WM_DELETE_WINDOW',self.destroy);self.after_idle(self.focus_query)

    def focus_query(self):self.lift();self.entry.focus_force();self.entry.selection_range(0,'end')

    def current(self):return self.app.store is self.store and getattr(self.store,'_view_generation',0)==self.generation

    def search(self,event=None,auto=True):
        if not self.current():self.info.set('도면이 바뀌었습니다. Ctrl+F로 찾기를 다시 여세요.');return 'break'
        self.results=drawing_search(self.store,self.query.get(),self.category.get());self.revision=self.store.data_revision()
        self.tree.delete(*self.tree.get_children());self.diagram.delete('all')
        for i,row in enumerate(self.results):self.tree.insert('','end',iid=str(i),values=(row['kind'],row['identifier'],row['title'],row['location']))
        self.info.set(f'검색 결과 {len(self.results)}개 · 클릭하면 해당 위치로 이동합니다.' if self.results else '일치하는 항목이 없습니다. ID 또는 이름을 확인하세요.' if self.query.get().strip() else '찾을 ID 또는 이름을 입력하세요.')
        exact=[i for i,r in enumerate(self.results) if r['rank']==0]
        if auto and (len(exact)==1 or len(self.results)==1):
            iid=str(exact[0] if len(exact)==1 else 0);self.tree.selection_set(iid);self.tree.focus(iid);self.tree.see(iid)
        return 'break'

    def reveal(self,event=None):
        selected=self.tree.selection()
        if not selected:return 'break'
        if not self.current():self.info.set('도면이 바뀌었습니다. Ctrl+F로 찾기를 다시 여세요.');return 'break'
        if self.revision!=self.store.data_revision():
            self.search(auto=False);self.info.set('도면이 수정되어 검색 결과를 갱신했습니다. 결과를 다시 선택하세요.');return 'break'
        row=self.results[int(selected[0])];trace=reveal_search_result(self.app,row,owner=self)
        if trace is None:self.info.set('해당 항목이 없어졌습니다. 다시 검색하세요.');return 'break'
        namespace=type(self.app).__init__.__globals__;namespace['draw_trace_diagram'](self.diagram,trace)
        if row.get('core_id'):
            self.info.set(f"코어ID {row['core_id']} · 경로 {len(trace['groups'])}개 전체 표시 · 케이블 {len(trace['highlight'])}개 선택 · 주황색 코어번호 표시"+(' · '+' / '.join(trace['issues']) if trace['issues'] else ''))
        else:self.info.set(row['kind']+' '+row['identifier']+' · 위치 이동·선택 완료. 도면 보기 / 닫기를 누르면 선택 상태로 작업할 수 있습니다.')
        return 'break'

    def destroy(self):
        # Preserve the chosen objects and trace when returning to the drawing.
        if getattr(self.app,'highlight_owner',None) is self:self.app.highlight_owner=None
        previous=self._previous_grab;super().destroy()
        try:
            if previous is not None and previous.winfo_exists():previous.grab_set()
            else:self.app.lift();self.app.canvas.focus_set()
        except tk.TclError:pass
