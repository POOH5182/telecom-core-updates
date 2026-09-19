"""Independent, modeless viewer of the saved previous drawing stage."""


def reference_kind(kind):return {'before':'gis','after':'before'}.get(kind)


class ReferenceSnapshot:
    """Migrate a private copy only; never open a saved source as a writable Store."""
    def __init__(self,store_type,path):
        self.store=None;self.temp=tempfile.TemporaryDirectory(prefix='telecom_reference_')
        try:
            source=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
            try:
                if source.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('참고 도면 저장본을 읽을 수 없습니다.')
                for table in ('nodes','cables','cores','splices'):
                    source.execute('SELECT * FROM '+table+' LIMIT 1')
                destination=Path(self.temp.name)/'reference.sqlite3'
                copy_conn=sqlite3.connect(destination)
                try:source.backup(copy_conn)
                finally:copy_conn.close()
            finally:source.close()
            self.store=store_type(destination)
            self.store.conn.execute('PRAGMA query_only=ON')
        except Exception:self.close();raise

    def close(self):
        if self.store is not None:self.store.close();self.store=None
        self.temp.cleanup()


REFERENCE_COLUMNS=('cable','number','core_id','detail','signal','state','start','end')
REFERENCE_HEADINGS=('케이블 / 포트','선번','코어ID','코어내역','신호','상태·메모','시작측 접속','끝측 접속')


def reference_core_rows(store,kind,key):
    nodes={r['id']:dict(r) for r in store.nodes()};cables={r['id']:dict(r) for r in store.cables()}
    slots=[dict(r) for r in store.all_core_rows()];by_slot={(r['cable_id'],int(r['core_index'])):r for r in slots}
    peers=defaultdict(list)
    for s in store.conn.execute('SELECT * FROM splices'):
        a=(s['cable1_id'],int(s['core1_index']));b=(s['cable2_id'],int(s['core2_index']))
        peers[(s['node_id'],a)].append(b);peers[(s['node_id'],b)].append(a)
    def owner_name(owner):
        if owner.startswith('PORT:'):return nodes.get(owner[5:],{}).get('name',owner[5:])+' 내부'
        c=cables.get(owner,{})
        return str(c.get('cable_id') or c.get('spec') or owner)
    def number(owner,index):
        r=by_slot.get((owner,index),{})
        return str(r.get('port_label') or r.get('label') or index) if owner.startswith('PORT:') else str(index)+'번'
    def end(nid,slot):
        matches=peers.get((nid,slot),())
        location=nodes.get(nid,{}).get('name',nid)
        return location+' · '+(' / '.join(owner_name(o)+' / '+number(o,i) for o,i in matches) if matches else '미접속')
    output=[]
    for row in slots:
        owner=row['cable_id'];index=int(row['core_index']);c=cables.get(owner,{})
        n1=owner[5:] if owner.startswith('PORT:') else c.get('n1id','');n2=c.get('n2id','')
        if kind=='cable' and owner!=key:continue
        if kind=='node' and key not in (n1,n2):continue
        if kind=='core' and str(row.get('core_id') or '').strip()!=key:continue
        row=annotate(store,row)
        status=annotation_text(store,row) or ' / '.join(STATUS_NAMES.get(str(row.get(k) or ''),str(row.get(k) or '')) for k in ('status1','status2') if row.get(k))
        values=(owner_name(owner),number(owner,index),row.get('core_id') or '',row.get('detail') or '',
                CORE_SIGNAL_NAMES.get(row.get('signal') or 'unknown',row.get('signal') or ''),status,
                end(n1,(owner,index)) if n1 else '',end(n2,(owner,index)) if n2 else '')
        output.append(dict(slot=(owner,index),values=values))
    return sorted(output,key=lambda row:(row['values'][0],row['slot'][0],row['slot'][1]))


class ReferenceDrawingDialog(RememberedToplevel):
    def __init__(self,app):
        super().__init__(app);self.app=app;self.title('참고 도면 · 읽기 전용');self.geometry('1180x820');self.minsize(820,560)
        self.reference_snapshot=None;self.store=None;self.source_kind=None;self.source_path=None
        self._source_token=None;self._selection_token=None;self._poll_job=None;self._fit_job=None;self._closed=False
        self.selected_item=None;self.selected=set();self.view_scale=1.;self.preview_positions={};self.label_fonts={}
        self.display_options=dict(app.display_options);self.item_to_node={};self.item_to_cable={}
        self.cable_line_items={};self.cable_base_styles={};self.highlight_cables=set();self.highlight_blink_on=False
        self.highlight_cable_colors={};self._drag_start=None;self._find_signature=None;self._find_index=-1
        self.source_text=tk.StringVar();self.notice=tk.StringVar();self.detail_text=tk.StringVar(value='함체 또는 케이블을 선택하면 코어내역을 표시합니다.')
        self.find_text=tk.StringVar();self.follow_selection=tk.BooleanVar(value=False)
        header=ttk.Frame(self,padding=(12,10,12,4));header.pack(fill='x')
        ttk.Label(header,textvariable=self.source_text,style='Title.TLabel').pack(side='left')
        ttk.Label(header,text='읽기 전용 · 별도 모니터로 옮겨서 사용',style='Muted.TLabel').pack(side='right')
        tools=ttk.Frame(self,padding=(12,4));tools.pack(fill='x')
        self.find_entry=ttk.Entry(tools,textvariable=self.find_text,width=28);self.find_entry.pack(side='left',fill='x',expand=True)
        self.find_entry.bind('<Return>',self.find_next)
        ttk.Button(tools,text='찾기 / 다음',command=self.find_next).pack(side='left',padx=4)
        ttk.Button(tools,text='화면 맞춤',command=self.fit_view).pack(side='left',padx=4)
        ttk.Button(tools,text='저장본 새로고침',command=lambda:self.reload_source(force=True)).pack(side='left',padx=4)
        ttk.Button(tools,text='선택 내역 복사',command=self.copy_selected).pack(side='left',padx=4)
        options=ttk.Frame(self,padding=(12,2,12,6));options.pack(fill='x')
        ttk.Button(options,text='작업창 선택 찾기',command=self.sync_selection).pack(side='left')
        ttk.Checkbutton(options,text='작업창 선택 따라가기',variable=self.follow_selection,command=self._follow_changed).pack(side='left',padx=10)
        ttk.Label(options,text='시설·케이블·코어ID 검색 · 휠 확대/축소 · 드래그 이동',style='Muted.TLabel').pack(side='left')
        ttk.Label(self,textvariable=self.notice,style='Muted.TLabel',padding=(12,5),wraplength=790).pack(side='bottom',fill='x')
        self.panes=ttk.Panedwindow(self,orient='vertical');self.panes.pack(fill='both',expand=True,padx=8,pady=(0,4))
        drawing=ttk.Frame(self.panes);drawing.rowconfigure(0,weight=1);drawing.columnconfigure(0,weight=1);self.panes.add(drawing,weight=3)
        self.canvas=tk.Canvas(drawing,bg='#f5f7fb',highlightthickness=0);self.canvas.grid(row=0,column=0,sticky='nsew')
        xs=ttk.Scrollbar(drawing,orient='horizontal',command=self.canvas.xview);ys=ttk.Scrollbar(drawing,orient='vertical',command=self.canvas.yview)
        xs.grid(row=1,column=0,sticky='ew');ys.grid(row=0,column=1,sticky='ns');self.canvas.configure(xscrollcommand=xs.set,yscrollcommand=ys.set)
        details=ttk.Frame(self.panes);self.panes.add(details,weight=1)
        ttk.Label(details,textvariable=self.detail_text,padding=(4,5)).pack(fill='x')
        frame=ttk.Frame(details);frame.pack(fill='both',expand=True);frame.columnconfigure(0,weight=1);frame.rowconfigure(0,weight=1)
        self.core_tree=SortableTreeview(frame,columns=REFERENCE_COLUMNS,show='headings',height=8,selectmode='extended')
        self.core_tree.grid(row=0,column=0,sticky='nsew')
        for name,label,width in zip(REFERENCE_COLUMNS,REFERENCE_HEADINGS,(150,70,140,200,80,120,250,250)):
            self.core_tree.heading(name,text=label);self.core_tree.column(name,width=width,minwidth=60,stretch=False)
        vs=ttk.Scrollbar(frame,orient='vertical',command=self.core_tree.yview);hs=ttk.Scrollbar(frame,orient='horizontal',command=self.core_tree.xview)
        vs.grid(row=0,column=1,sticky='ns');hs.grid(row=1,column=0,sticky='ew');self.core_tree.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
        for seq in ('<Control-c>','<Control-C>'):self.core_tree.bind(seq,self.copy_selected)
        for seq in ('<Control-a>','<Control-A>'):self.core_tree.bind(seq,self.select_all_rows)
        for seq in ('<Control-s>','<Control-S>','<Control-z>','<Control-Z>','<Control-y>','<Control-Y>'):
            self.bind(seq,lambda e:'break')
        for seq in ('<Control-f>','<Control-F>'):self.bind(seq,self.focus_find)
        self.bind('<Escape>',self.close_key);self.bind('<Delete>',lambda e:'break')
        self.canvas.bind('<MouseWheel>',self.zoom);self.canvas.bind('<Button-4>',lambda e:self.zoom_by(1.12,e));self.canvas.bind('<Button-5>',lambda e:self.zoom_by(1/1.12,e))
        for button in (1,3):
            self.canvas.bind(f'<ButtonPress-{button}>',self.pan_start);self.canvas.bind(f'<B{button}-Motion>',self.pan_move);self.canvas.bind(f'<ButtonRelease-{button}>',self.pan_end)
        self.canvas.bind('<Configure>',lambda e:self._place_empty())
        self.protocol('WM_DELETE_WINDOW',self.destroy);self.reload_source(force=True);self._poll_job=self.after(700,self._poll)

    def hamche_label_layout(self,*args,**kwargs):return type(self.app).hamche_label_layout(self,*args,**kwargs)
    def cable_label_layout(self,*args,**kwargs):return type(self.app).cable_label_layout(self,*args,**kwargs)
    def render_cable_labels(self,*args,**kwargs):return type(self.app).render_cable_labels(self,*args,**kwargs)

    def _token(self):
        kind=reference_kind(self.app.scenario_kind());path=self.app.scenario_path(kind) if kind else None
        def stamp(p):
            try:s=p.stat();return s.st_mtime_ns,s.st_size,s.st_ino
            except FileNotFoundError:return None
        return (id(self.app.store),str(self.app.store.path.resolve()),self.app.scenario_kind(),kind,
                stamp(path) if path else None,stamp(Path(str(path)+'-wal')) if path else None)

    def reload_source(self,force=False):
        if self._closed:return
        try:token=self._token()
        except OSError as error:self.clear_source('참고 도면을 확인할 수 없습니다: '+str(error));return
        if not force and token==self._source_token:return
        previous=self._source_token;self._source_token=token
        same_source=previous is not None and previous[:4]==token[:4]
        selected=self.selected_item if same_source else None
        self.source_kind=token[3];self.source_path=self.app.scenario_path(self.source_kind) if self.source_kind else None
        self.source_text.set((STAGE_NAMES[self.source_kind]+' 참고') if self.source_kind else '참고 도면')
        self.title(self.source_text.get()+' · 읽기 전용 · '+self.app.store.path.stem)
        if not self.source_kind:
            self.clear_source('현장반영에서는 GIS 도면을, 후도면에서는 현장반영 도면을 참고할 수 있습니다.');return
        if token[4] is None:
            self.clear_source(STAGE_NAMES[self.source_kind]+' 저장본이 없습니다. 해당 단계 도면을 먼저 저장하세요.');return
        try:snapshot=ReferenceSnapshot(type(self.app.store),self.source_path)
        except (sqlite3.Error,OSError,ValueError) as error:
            self.clear_source('참고 도면을 열 수 없습니다. 저장본을 확인하세요. '+str(error));return
        old=self.reference_snapshot;self.reference_snapshot=snapshot;self.store=snapshot.store
        if old is not None:old.close()
        self.display_options=dict(self.app.display_options);self.selected.clear();self.selected_item=None
        self._find_signature=None;self._find_index=-1;self._selection_token=None
        self.detail_text.set('함체 또는 케이블을 선택하면 코어내역을 표시합니다.');self.core_tree.delete(*self.core_tree.get_children())
        when=datetime.fromtimestamp(token[4][0]/1e9).strftime('%Y-%m-%d %H:%M:%S')
        self.notice.set('저장본 기준: '+when+' · 참고창에서는 도면을 수정하거나 저장하지 않습니다.')
        self.render()
        if selected:self.select_item(*selected)
        if not same_source:
            if self._fit_job is not None:self.after_cancel(self._fit_job)
            self._fit_job=self.after_idle(self._fit_initial)

    def _fit_initial(self):self._fit_job=None;self.fit_view()

    def clear_source(self,message):
        if self.reference_snapshot is not None:self.reference_snapshot.close();self.reference_snapshot=None
        self.store=None;self.selected.clear();self.selected_item=None;self.item_to_node.clear();self.item_to_cable.clear()
        self.core_tree.delete(*self.core_tree.get_children());self.detail_text.set('참고할 저장 도면이 없습니다.')
        self.canvas.delete('all');self.canvas.configure(scrollregion=(0,0,1,1));self.canvas.xview_moveto(0);self.canvas.yview_moveto(0)
        self.canvas.create_text(20,30,text=message,width=620,anchor='nw',fill='#475569',tags='empty_reference')
        self.notice.set(message);self._find_signature=None

    def _place_empty(self):
        if self.store is None:self.canvas.itemconfigure('empty_reference',width=max(100,self.canvas.winfo_width()-40))

    def render(self):
        if self.store is None:return
        x,y=self.canvas.canvasx(0),self.canvas.canvasy(0)
        type(self.app).render_drawing_canvas(self)
        nodes=self.store.nodes();left=min([0]+[n['x']-160 for n in nodes])*self.view_scale;top=min([0]+[n['y']-180 for n in nodes])*self.view_scale
        self.canvas.configure(scrollregion=(left,top,self.world_w*self.view_scale,self.world_h*self.view_scale))
        self._scroll_to(x,y)

    def _scroll_to(self,x,y):
        bounds=tuple(float(v) for v in self.canvas.cget('scrollregion').split())
        if len(bounds)!=4:return
        x0,y0,x1,y1=bounds
        self.canvas.xview_moveto(max(0,(x-x0)/max(1,x1-x0)));self.canvas.yview_moveto(max(0,(y-y0)/max(1,y1-y0)))

    def fit_view(self):
        if self.store is None:return
        nodes=self.store.nodes()
        if not nodes:return
        self.update_idletasks();self._fit_nodes(nodes)

    def _fit_nodes(self,nodes):
        if not nodes:return
        x0=min(n['x'] for n in nodes)-140;x1=max(n['x'] for n in nodes)+140
        y0=min(n['y'] for n in nodes)-170;y1=max(n['y'] for n in nodes)+140
        w=max(1,self.canvas.winfo_width());h=max(1,self.canvas.winfo_height())
        self.view_scale=max(.03,min(1.5,(w-30)/max(1,x1-x0),(h-30)/max(1,y1-y0)))
        self.render();self._scroll_to((x0+x1)*self.view_scale/2-w/2,(y0+y1)*self.view_scale/2-h/2)

    def zoom(self,event):return self.zoom_by(1.12 if event.delta>0 else 1/1.12,event)
    def zoom_by(self,factor,event):
        if self.store is None:return 'break'
        old=self.view_scale;x=self.canvas.canvasx(event.x)/old;y=self.canvas.canvasy(event.y)/old
        self.view_scale=max(.03,min(3.,old*factor));self.render();self._scroll_to(x*self.view_scale-event.x,y*self.view_scale-event.y)
        return 'break'

    def pan_start(self,event):
        self.canvas.focus_set();self._drag_start=(event.x,event.y);self.canvas.scan_mark(event.x,event.y);return 'break'
    def pan_move(self,event):
        if self._drag_start:self.canvas.scan_dragto(event.x,event.y,gain=1)
        return 'break'
    def pan_end(self,event):
        start=self._drag_start;self._drag_start=None
        if not start or abs(start[0]-event.x)+abs(start[1]-event.y)>5:return 'break'
        x,y=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x-3,y-3,x+3,y+3)):
            if item in self.item_to_node:self.select_item('node',self.item_to_node[item]);break
            if item in self.item_to_cable:self.select_item('cable',self.item_to_cable[item]);break
        return 'break'

    def select_item(self,kind,key,center=False):
        if self.store is None:return False
        row=self.store.node(key) if kind=='node' else self.store.cable(key) if kind=='cable' else None
        rows=reference_core_rows(self.store,kind,key)
        if kind in ('node','cable') and row is None:return False
        if kind=='core' and not rows:return False
        self.selected_item=(kind,key)
        self.selected={key} if kind in ('node','cable') else {r['slot'][0][5:] if r['slot'][0].startswith('PORT:') else r['slot'][0] for r in rows}
        title=(row['name'] if kind=='node' else row['cable_id'] or row['spec']) if row is not None else key
        self.detail_text.set(str(title)+' · '+str(len(rows))+'개 코어 · 접속은 이 참고 도면에 저장된 실제 선번입니다.')
        self.core_tree.delete(*self.core_tree.get_children())
        for i,item in enumerate(rows):self.core_tree.insert('','end',iid=str(i),values=item['values'])
        self.render()
        if center:
            nodes=[]
            for target in self.selected:
                node=self.store.node(target);cable=self.store.cable(target)
                nodes.extend([node] if node else [self.store.node(cable['n1id']),self.store.node(cable['n2id'])] if cable else [])
            self._fit_nodes([n for n in nodes if n])
        return True

    def find_next(self,event=None):
        if self.store is None:return 'break'
        query=self.find_text.get().strip();results=drawing_search(self.store,query)
        signature=(query,self._source_token)
        if signature!=self._find_signature:self._find_signature=signature;self._find_index=-1
        if not results:self.notice.set('검색 결과가 없습니다. 시설명·시설ID·케이블ID·코어ID를 입력하세요.');return 'break'
        self._find_index=(self._find_index+1)%len(results);result=results[self._find_index]
        kind,key=('node',result['node_id']) if 'node_id' in result else ('cable',result['cable_id']) if 'cable_id' in result else ('core',result['core_id'])
        self.select_item(kind,key,center=True);self.notice.set(f"찾기 {self._find_index+1}/{len(results)} · {result['kind']} · {result['identifier']}")
        return 'break'

    def sync_selection(self):
        self.reload_source()
        if self.store is None:return
        selection=tuple(sorted(self.app.selected));self._selection_token=selection
        for key in selection:
            if self.store.node(key):self.select_item('node',key,center=True);return
            if self.store.cable(key):self.select_item('cable',key,center=True);return
        self.notice.set('작업창에서 선택한 시설·케이블이 참고 도면에 없습니다.' if selection else '작업창에서 함체 또는 케이블을 먼저 선택하세요.')

    def _follow_changed(self):
        self._selection_token=None
        if self.follow_selection.get():self.sync_selection()

    def focus_find(self,event=None):self.find_entry.focus_set();self.find_entry.selection_range(0,'end');return 'break'
    def close_key(self,event=None):self.destroy();return 'break'
    def select_all_rows(self,event=None):self.core_tree.selection_set(self.core_tree.get_children());return 'break'
    def copy_selected(self,event=None):
        chosen=set(self.core_tree.selection());rows=[i for i in self.core_tree.get_children() if i in chosen]
        if not rows:self.notice.set('복사할 코어내역 행을 선택하세요. Ctrl+A로 전체를 선택할 수 있습니다.');return 'break'
        import csv
        output=io.StringIO();writer=csv.writer(output,delimiter='\t',lineterminator='\n');writer.writerow(REFERENCE_HEADINGS)
        for item in rows:writer.writerow(self.core_tree.item(item,'values'))
        self.clipboard_clear();self.clipboard_append(output.getvalue());self.notice.set(str(len(rows))+'개 코어내역을 복사했습니다.');return 'break'

    def _poll(self):
        self._poll_job=None
        if self._closed:return
        try:
            self.reload_source()
            if self.follow_selection.get() and tuple(sorted(self.app.selected))!=self._selection_token:self.sync_selection()
        finally:
            if not self._closed:self._poll_job=self.after(700,self._poll)

    def destroy(self):
        if self._closed:return
        self._closed=True
        for job in (self._poll_job,self._fit_job):
            if job is not None:
                try:self.after_cancel(job)
                except tk.TclError:pass
        self._poll_job=None;self._fit_job=None
        if self.reference_snapshot is not None:self.reference_snapshot.close();self.reference_snapshot=None;self.store=None
        if getattr(self.app,'_reference_drawing',None) is self:self.app._reference_drawing=None
        super().destroy()


def open_reference_drawing(app):
    dialog=getattr(app,'_reference_drawing',None)
    if dialog is not None and dialog.winfo_exists():
        dialog.reload_source();dialog.deiconify();dialog.lift();return dialog
    dialog=ReferenceDrawingDialog(app);app._reference_drawing=dialog;return dialog
