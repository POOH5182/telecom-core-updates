"""Independent, modeless GIS/field/after saved drawing windows."""


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


def reference_slot_highlight(store,slots):
    """Project chosen physical connections only; a matching ID is never an edge."""
    audit=field_slot_audit(store);net=audit['net'];rows=audit['rows']
    seeds=tuple(sorted({(str(owner),int(index)) for owner,index in slots if (str(owner),int(index)) in rows}))
    visited=set();groups=[];nodes=set();bands=defaultdict(list);cable_slots=defaultdict(set);label_colors={}
    for seed in seeds:
        if seed in visited:continue
        members=set();pending=[seed]
        while pending:
            slot=pending.pop()
            if slot in members or slot not in rows:continue
            members.add(slot);pending.extend(peer for _,peer in net.links.get(slot,()) if peer not in members)
        visited.update(members);number=len(groups)+1;color=core_segment_color(number-1)
        identities={str(rows[slot].get('core_id') or '').strip() for slot in members
                    if str(rows[slot].get('core_id') or '').strip() and not str(rows[slot].get('core_id')).startswith('임시-')}
        groups.append(dict(number=number,color=color,slots=tuple(sorted(members))))
        cable_lines=defaultdict(list)
        for slot in sorted(members):
            row=rows[slot];core_id=str(row.get('core_id') or '')
            shown=('임시코어'+core_id[3:]) if core_id.startswith('임시-') and core_id[3:].isdigit() else core_id
            if slot[0] in net.cables:
                cable=net.cables[slot[0]];nodes.update((cable['n1id'],cable['n2id']))
                owners=[slot[0]];prefix=str(slot[1])+'번';cable_slots[slot[0]].add(slot)
            elif slot[0].startswith('PORT:'):
                nodes.add(slot[0][5:]);owners=sorted({peer[0] for _,peer in net.links.get(slot,()) if peer[0] in net.cables})
                prefix='RN 포트 '+str(row.get('label') or slot[1])
            else:continue
            for owner in owners:cable_lines[owner].append(prefix+' · 코어ID: '+(shown or '(없음)'))
        for cable,lines in cable_lines.items():
            text=f'경로 {number}'+(' · 코어ID 다름' if len(identities)>1 else '')+'\n'+'\n'.join(lines)
            bands[cable].append(dict(number=number,color=color,text=text))
            if len(identities)>1:label_colors[cable]='#c62828'
    overlaps=frozenset(cable for cable,members in cable_slots.items() if len(members)>1)
    colors={cable:OVERLAP_COLOR if cable in overlaps else items[0]['color'] for cable,items in bands.items()}
    labels={cable:('겹침 · '+str(len(cable_slots[cable]))+'개 선번\n' if cable in overlaps else '')+
            '\n'.join(item['text'] for item in items) for cable,items in bands.items()}
    return dict(seed_slots=seeds,slots=frozenset(visited),groups=groups,nodes=frozenset(nodes),colors=colors,labels=labels,
                bands=dict(bands),label_colors=label_colors,overlaps=overlaps,boundaries=[],
                summary=f'실제 접속 {len(groups)}구간 · {len(visited)}개 선번')


class ReferenceDrawingDialog(RememberedToplevel):
    """A pinned stage drawing: independent navigation, private read-only data."""
    def __init__(self,app,kind):
        self._stage_kind=kind;self._stage_reference=True;self._stage_independent=True
        super().__init__(app);self.app=app;self.source_kind=kind
        self.title('통신 코어 도면 · 참고용');self.geometry('1450x900');self.minsize(920,640)
        self.reference_snapshot=None;self.store=None;self.source_path=None;self._reference_details={}
        self._source_token=None;self._selection_token=None;self._poll_job=None;self._fit_job=None;self._closed=False
        self.selected_item=None;self.selected=set();self.view_scale=1.;self.preview_positions={};self.label_fonts={}
        self.display_options=dict(app.display_options);self.item_to_node={};self.item_to_cable={}
        self.cable_line_items={};self.cable_base_styles={};self.highlight_cables=set();self.highlight_blink_on=False
        self.highlight_cable_colors={};self._drag_start=None;self._find_signature=None;self._find_index=-1
        self.source_text=tk.StringVar();self.notice=tk.StringVar();self.find_text=tk.StringVar()
        self.follow_selection=tk.BooleanVar(value=False);self._core_labels={}
        self.highlight_owner=None;self.highlight_blink_job=None;self.highlight_core_labels={};self.highlight_connection_model={}
        self._highlight_label_items=[];self._highlight_hint_items=[];self._highlight_glow_items={}

        self.dashboard_expanded=True;self.minimap_visible=False;self.minimap_transform=None;self.minimap_view_item=None
        self.minimap_drag_anchor=None;self.pending_drag=None;self.world_w=5200;self.world_h=4200
        header=tk.Frame(self,bg='#14243d');header.pack(fill='x');self.desktop_header=header
        title_row=tk.Frame(header,bg='#14243d');title_row.pack(fill='x',padx=16,pady=(12,8))
        actions=tk.Frame(title_row,bg='#14243d');actions.pack(side='right')
        ttk.Button(actions,text='저장본 새로고침',command=lambda:self.reload_source(force=True),style='Header.TButton').pack(side='left',padx=3)
        ttk.Button(actions,text='다른 도면 새 창으로',command=lambda:open_reference_drawing(app),style='Header.TButton').pack(side='left',padx=3)
        title_text=tk.Frame(title_row,bg='#14243d');title_text.pack(side='left',fill='x',expand=True)
        tk.Label(title_text,text='통신 코어 도면',font=('Malgun Gothic',15,'bold'),fg='white',bg='#14243d',anchor='w').pack(fill='x')
        tk.Label(title_text,textvariable=self.source_text,font=('Malgun Gothic',8),fg='#a7bbd7',bg='#14243d',anchor='w').pack(fill='x')
        stages=tk.Frame(header,bg='#14243d');stages.pack(fill='x',padx=16,pady=(0,12));self.stage_buttons={}
        for i,target in enumerate(('gis','before','after')):
            text=STAGE_WINDOW_NAMES[target]+(' · 이 창' if target==kind else ' · 새 창으로 열기')
            button=tk.Button(stages,text=text,command=lambda k=target:open_reference_drawing(app,k),
                font=('Malgun Gothic',9,'bold'),fg='white',bg=STAGE_WINDOW_COLORS[target] if target==kind else '#294468',
                activebackground=STAGE_WINDOW_COLORS[target],activeforeground='white',relief='flat',bd=0,padx=8,pady=7,cursor='hand2')
            button.grid(row=0,column=i,sticky='ew',padx=(0,5) if i<2 else 0);stages.columnconfigure(i,weight=1,uniform='stage');self.stage_buttons[target]=button
        toolbar=FlowToolbar(self);toolbar.pack(fill='x');self.drawing_toolbar=toolbar
        for label,command in (('선택/이동',self.clear_selection),('선택 내역',self.open_selected_detail),('찾기 Ctrl+F',self.focus_find),
                              ('보기설정',self.open_display_settings),('코어추적',self.open_core_trace),('화면 맞춤',self.fit_view),('도면 강조 해제',self.clear_selection)):
            toolbar.add(ttk.Button(toolbar,text=label,command=command,style='Tool.TButton'))
        self.find_entry=ttk.Entry(toolbar,textvariable=self.find_text,width=24);toolbar.add(self.find_entry)
        self.find_entry.bind('<Return>',self.find_next)
        toolbar.add(ttk.Button(toolbar,text='찾기 / 다음',command=self.find_next,style='Tool.TButton'))
        statusbar=ttk.Frame(self,padding=(14,6));statusbar.pack(side='bottom',fill='x')
        ttk.Label(statusbar,text='드래그 이동 · 휠 확대/축소 · 더블클릭 내역',style='Muted.TLabel').pack(side='right',padx=(10,0))
        ttk.Label(statusbar,textvariable=self.notice,style='Muted.TLabel',anchor='w').pack(side='left',fill='x',expand=True)
        drawing=ttk.Frame(self);self.canvas_frame=drawing;drawing.pack(fill='both',expand=True)
        drawing.rowconfigure(0,weight=1);drawing.columnconfigure(0,weight=1)
        self.canvas=tk.Canvas(drawing,bg='#f5f7fb',highlightthickness=0);self.canvas.grid(row=0,column=0,sticky='nsew')
        xs=ttk.Scrollbar(drawing,orient='horizontal',command=self.canvas.xview);ys=ttk.Scrollbar(drawing,orient='vertical',command=self.canvas.yview)
        xs.grid(row=1,column=0,sticky='ew');ys.grid(row=0,column=1,sticky='ns')
        self.canvas.configure(xscrollcommand=lambda a,b:self._canvas_scrolled(xs,a,b),yscrollcommand=lambda a,b:self._canvas_scrolled(ys,a,b))
        self._make_dashboard(drawing)
        self.minimap_frame=tk.Frame(drawing,bg='white',highlightbackground='#7f8da3',highlightthickness=1)
        tk.Label(self.minimap_frame,text='미니맵 · 클릭 이동 / 주황 상자 드래그',font=('Malgun Gothic',8,'bold'),fg='white',bg='#26354d',padx=8,pady=4).pack(fill='x')
        self.minimap=tk.Canvas(self.minimap_frame,width=250,height=155,bg='#fbfcfe',highlightthickness=0,cursor='hand2');self.minimap.pack()
        self.minimap.bind('<Button-1>',self.minimap_press);self.minimap.bind('<B1-Motion>',self.minimap_drag);self.minimap.bind('<ButtonRelease-1>',self.minimap_release)
        for seq in ('<Control-s>','<Control-S>','<Control-z>','<Control-Z>','<Control-y>','<Control-Y>'):
            self.bind(seq,lambda e:'break')
        for seq in ('<Control-f>','<Control-F>'):self.bind(seq,self.focus_find)
        self.bind('<Escape>',self.clear_selection);self.bind('<Delete>',lambda e:'break')
        self.canvas.bind('<MouseWheel>',self.zoom);self.canvas.bind('<Button-4>',lambda e:self.zoom_by(1.12,e));self.canvas.bind('<Button-5>',lambda e:self.zoom_by(1/1.12,e))
        for button in (1,3):
            self.canvas.bind(f'<ButtonPress-{button}>',self.pan_start);self.canvas.bind(f'<B{button}-Motion>',self.pan_move);self.canvas.bind(f'<ButtonRelease-{button}>',self.pan_end)
        self.canvas.bind('<Double-Button-1>',self.double_click);self.canvas.bind('<Configure>',self._canvas_resized)
        self.protocol('WM_DELETE_WINDOW',self.destroy)
        apply_stage_window_chrome(self,kind,True)
        self.reload_source(force=True);self._poll_job=self.after(700,self._poll)

    def _make_dashboard(self,parent):
        self.dashboard_frame=tk.Frame(parent,bg='white',highlightbackground='#dbe3ed',highlightthickness=1)
        self.dashboard_frame.place(x=18,y=18,anchor='nw')
        head=tk.Frame(self.dashboard_frame,bg='white');head.pack(fill='x')
        tk.Label(head,text='도면 현황',font=('Malgun Gothic',11,'bold'),fg='#192b46',bg='white',padx=14,pady=12).pack(side='left')
        self.minimap_toggle_button=tk.Button(head,text='미니맵 보기',command=self.toggle_minimap,font=('Malgun Gothic',8),fg='#64748b',bg='white',relief='flat',padx=7,pady=3)
        self.minimap_toggle_button.pack(side='right',padx=3,pady=3)
        self.dashboard_toggle_button=tk.Button(head,text='접기 ▲',command=self.toggle_dashboard,font=('Malgun Gothic',8),fg='#64748b',bg='white',relief='flat',padx=7,pady=3)
        self.dashboard_toggle_button.pack(side='right',padx=3,pady=3)
        self.metrics_frame=tk.Frame(self.dashboard_frame,bg='white');self.metrics_frame.pack(fill='both')
        self.metrics_text=tk.StringVar();self.metrics_rate=tk.StringVar()
        tk.Label(self.metrics_frame,textvariable=self.metrics_text,justify='left',anchor='w',font=('Malgun Gothic',9),bg='white',padx=14,pady=8,wraplength=290).pack(fill='x')
        tk.Label(self.metrics_frame,textvariable=self.metrics_rate,anchor='w',font=('Malgun Gothic',22,'bold'),fg=STAGE_WINDOW_COLORS[self.source_kind],bg='white',padx=14).pack(fill='x')
        self.completion_bar=ttk.Progressbar(self.metrics_frame,maximum=100,style='Completion.Horizontal.TProgressbar');self.completion_bar.pack(fill='x',padx=14,pady=(6,12))
        tk.Label(self.metrics_frame,text='참고용 · 해당 단계의 저장본',font=('Malgun Gothic',9),bg='#edf3fc',fg='#315eac',padx=14,pady=8).pack(fill='x')

    def refresh_dashboard(self):
        if self.store is None:
            self.metrics_text.set('저장 도면이 없습니다.');self.metrics_rate.set('—');self.completion_bar['value']=0;return
        nodes=self.store.nodes();cables=self.store.cables();report=completion_report(self.store,self.source_kind)
        total=report['total'];done=report['done'];rate=report['rate']
        self.metrics_text.set(f"{STAGE_WINDOW_NAMES[self.source_kind]}\n시설 {len(nodes)}개 · 케이블 {len(cables)}개\n연결 대상 {total}개 · 완료 {done}개 · 미완료 {total-done}개")
        self.metrics_rate.set(f'{rate:.1f}%' if rate is not None else '대상 없음');self.completion_bar['value']=rate or 0

    def toggle_dashboard(self):
        self.dashboard_expanded=not self.dashboard_expanded
        if self.dashboard_expanded:self.metrics_frame.pack(fill='both')
        else:self.metrics_frame.pack_forget()
        self.dashboard_toggle_button.configure(text='접기 ▲' if self.dashboard_expanded else '펼치기 ▼')

    def toggle_minimap(self):
        self.minimap_visible=not self.minimap_visible
        if self.minimap_visible:self.minimap_frame.place(relx=1.,rely=1.,x=-18,y=-18,anchor='se');self.refresh_minimap()
        else:self.minimap_frame.place_forget()
        self.minimap_toggle_button.configure(text='미니맵 숨기기' if self.minimap_visible else '미니맵 보기')

    def hamche_label_layout(self,*args,**kwargs):return type(self.app).hamche_label_layout(self,*args,**kwargs)
    def cable_label_layout(self,*args,**kwargs):return type(self.app).cable_label_layout(self,*args,**kwargs)
    def render_cable_labels(self,*args,**kwargs):return type(self.app).render_cable_labels(self,*args,**kwargs)
    def refresh_minimap(self):
        if self.store is not None:type(self.app).refresh_minimap(self)
    def refresh_minimap_viewport(self):return type(self.app).refresh_minimap_viewport(self)
    def minimap_release(self,event):return type(self.app).minimap_release(self,event)
    def minimap_press(self,event):return type(self.app).minimap_press(self,event)
    def minimap_click(self,event):
        if not self.minimap_transform:return
        minx,miny,factor,pad=self.minimap_transform
        x=(minx+(event.x-pad)/factor)*self.view_scale-self.canvas.winfo_width()/2
        y=(miny+(event.y-pad)/factor)*self.view_scale-self.canvas.winfo_height()/2
        self._scroll_to(x,y)
    def minimap_drag(self,event):
        if not self.minimap_drag_anchor:return 'break'
        x,y,left,top,factor,scale=self.minimap_drag_anchor
        self._scroll_to(left+(event.x-x)/factor*scale,top+(event.y-y)/factor*scale);return 'break'
    def _canvas_scrolled(self,bar,a,b):bar.set(a,b);self.refresh_minimap_viewport()
    def _canvas_resized(self,event=None):
        if self.store is None:self.canvas.itemconfigure('empty_reference',width=max(100,self.canvas.winfo_width()-40))
        self.refresh_minimap_viewport()

    def _token(self):
        path=self.app.scenario_path(self.source_kind)
        def stamp(p):
            try:s=p.stat();return s.st_mtime_ns,s.st_size,s.st_ino
            except FileNotFoundError:return None
        return (str(self.app.store.path.resolve()),self.source_kind,stamp(path),stamp(Path(str(path)+'-wal')))

    def _close_details(self):
        for dialog in list(self._reference_details.values()):
            try:dialog.destroy()
            except tk.TclError:pass
        self._reference_details.clear()

    def reload_source(self,force=False):
        if self._closed:return
        try:token=self._token()
        except OSError as error:self.clear_source('참고 도면을 확인할 수 없습니다: '+str(error));return
        for target,button in self.stage_buttons.items():
            button.configure(state='normal' if target==self.source_kind or self.app.scenario_path(target).is_file() else 'disabled')
        if not force and token==self._source_token:return
        previous=self._source_token;self._source_token=token;same_source=previous is not None and previous[:2]==token[:2]
        selected=self.selected_item if same_source else None
        self.source_path=self.app.scenario_path(self.source_kind)
        self.source_text.set(STAGE_WINDOW_NAMES[self.source_kind]+' · '+self.app.store.path.stem+' · 저장된 도면')
        self.title('통신 코어 도면 · '+self.app.store.path.stem)
        if token[2] is None:
            self.clear_source(STAGE_WINDOW_NAMES[self.source_kind]+' 저장본이 없습니다. 작업창에서 해당 단계 도면을 저장하면 여기에 표시됩니다.');return
        try:snapshot=ReferenceSnapshot(type(self.app.store),self.source_path)
        except (sqlite3.Error,OSError,ValueError) as error:
            self.clear_source('참고 도면을 열 수 없습니다. 저장본을 확인하세요. '+str(error));return
        self.clear_reference_highlight(repaint=False);self._close_details()
        old=self.reference_snapshot;self.reference_snapshot=snapshot;self.store=snapshot.store
        if old is not None:old.close()
        self.selected.clear();self.selected_item=None;self.highlight_cables.clear();self._core_labels={}
        self._find_signature=None;self._find_index=-1;self._selection_token=None
        when=datetime.fromtimestamp(token[2][0]/1e9).strftime('%Y-%m-%d %H:%M:%S')
        self.notice.set('저장본 '+when+' · 더블클릭하면 함체·케이블 내역을 엽니다.')
        self.refresh_dashboard();self.render()
        if selected:self.select_item(*selected)
        if not same_source:
            if self._fit_job is not None:self.after_cancel(self._fit_job)
            self._fit_job=self.after_idle(self._fit_initial)

    def _fit_initial(self):self._fit_job=None;self.fit_view()

    def clear_source(self,message):
        self.clear_reference_highlight(repaint=False);self._close_details()
        if self._fit_job is not None:
            try:self.after_cancel(self._fit_job)
            except tk.TclError:pass
            self._fit_job=None
        if self.reference_snapshot is not None:self.reference_snapshot.close();self.reference_snapshot=None
        self.store=None;self.selected.clear();self.selected_item=None;self.item_to_node.clear();self.item_to_cable.clear()
        self.highlight_cables.clear();self._core_labels={};self.minimap_transform=None;self.minimap.delete('all')
        self.canvas.delete('all');self.canvas.configure(scrollregion=(0,0,1,1));self.canvas.xview_moveto(0);self.canvas.yview_moveto(0)
        self.canvas.create_text(20,210,text=message,width=620,anchor='nw',fill='#475569',tags='empty_reference')
        self.notice.set(message);self._find_signature=None;self.refresh_dashboard()

    def render(self):
        if self.store is None:return
        x,y=self.canvas.canvasx(0),self.canvas.canvasy(0)
        type(self.app).render_drawing_canvas(self)
        nodes=self.store.nodes();left=min([0]+[n['x']-160 for n in nodes])*self.view_scale;top=min([0]+[n['y']-180 for n in nodes])*self.view_scale
        self.canvas.configure(scrollregion=(left,top,self.world_w*self.view_scale,self.world_h*self.view_scale))
        type(self.app).apply_highlight_visuals(self)
        type(self.app).render_highlight_core_labels(self)
        self._scroll_to(x,y);self.refresh_minimap()

    def clear_reference_highlight(self,owner=None,repaint=True):
        if owner is not None and self.highlight_owner is not owner:return False
        if self.highlight_blink_job is not None:
            try:self.after_cancel(self.highlight_blink_job)
            except tk.TclError:pass
        self.highlight_blink_job=None;self.highlight_owner=None;self.highlight_blink_on=True
        self.highlight_cables.clear();self.highlight_cable_colors.clear();self.highlight_core_labels={};self._core_labels={}
        self.highlight_connection_model={}
        if repaint and not self._closed and self.store is not None:
            type(self.app).apply_highlight_visuals(self);type(self.app).render_highlight_core_labels(self)
        return True

    def highlight_reference_slots(self,slots,owner=None,center=False):
        if self._closed or self.store is None:return None
        model=reference_slot_highlight(self.store,slots)
        self.clear_reference_highlight(repaint=False)
        self.highlight_owner=owner if owner is not None else self
        self.highlight_connection_model=model;self.highlight_cable_colors=dict(model['colors'])
        self.highlight_cables=set(model['colors']);self.highlight_core_labels=dict(model['labels']);self._core_labels=self.highlight_core_labels
        self.highlight_blink_on=True
        if center:
            nodes=[self.store.node(nid) for nid in model['nodes']]
            self._fit_nodes([n for n in nodes if n])
        # Repaint the owned route without moving focus away from its table.
        type(self.app).apply_highlight_visuals(self);type(self.app).render_highlight_core_labels(self)
        self.notice.set(STAGE_WINDOW_NAMES[self.source_kind]+' · '+model['summary']+' · 선택 코어ID·선번 경로 표시')
        if self.highlight_cables:self.highlight_blink_job=self.after(330,self._reference_blink_tick)
        return model

    def _reference_blink_tick(self):
        self.highlight_blink_job=None
        if self._closed or self.store is None or not self.highlight_cables:return
        self.highlight_blink_on=not self.highlight_blink_on
        type(self.app).apply_highlight_visuals(self)
        self.highlight_blink_job=self.after(330,self._reference_blink_tick)

    def _scroll_to(self,x,y):
        bounds=tuple(float(v) for v in self.canvas.cget('scrollregion').split())
        if len(bounds)!=4:return
        x0,y0,x1,y1=bounds
        self.canvas.xview_moveto(max(0,(x-x0)/max(1,x1-x0)));self.canvas.yview_moveto(max(0,(y-y0)/max(1,y1-y0)));self.refresh_minimap_viewport()

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
        if self._drag_start:self.canvas.scan_dragto(event.x,event.y,gain=1);self.refresh_minimap_viewport()
        return 'break'
    def target(self,event):
        x,y=self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)
        for item in reversed(self.canvas.find_overlapping(x-3,y-3,x+3,y+3)):
            if item in self.item_to_node:return 'node',self.item_to_node[item]
            if item in self.item_to_cable:return 'cable',self.item_to_cable[item]
        return None
    def pan_end(self,event):
        start=self._drag_start;self._drag_start=None
        if not start or abs(start[0]-event.x)+abs(start[1]-event.y)>5:return 'break'
        target=self.target(event)
        if target:self.select_item(*target)
        return 'break'
    def double_click(self,event):
        self._drag_start=None;target=self.target(event)
        if target:self.select_item(*target);self.open_selected_detail()
        return 'break'

    def select_item(self,kind,key,center=False):
        if self.store is None:return False
        row=self.store.node(key) if kind=='node' else self.store.cable(key) if kind=='cable' else None
        if kind in ('node','cable') and row is None:return False
        rows=reference_core_rows(self.store,kind,key) if kind=='core' else []
        if kind=='core' and not rows:return False
        self.clear_reference_highlight(repaint=False)
        self.selected_item=(kind,key)
        self.selected={key} if kind in ('node','cable') else {r['slot'][0][5:] if r['slot'][0].startswith('PORT:') else r['slot'][0] for r in rows}
        title=(row['name'] if kind=='node' else row['cable_id'] or row['spec']) if row is not None else key
        self.notice.set(str(title)+' · '+('전체 코어 경로 표시 · 선택 내역에서 접속 확인' if kind=='core' else '더블클릭 또는 선택 내역으로 열기'))
        self.render()
        if kind=='core':
            self.highlight_reference_slots([row['slot'] for row in rows],owner=self,center=center);return True
        if center:
            nodes=[]
            for target in self.selected:
                node=self.store.node(target);cable=self.store.cable(target)
                nodes.extend([node] if node else [self.store.node(cable['n1id']),self.store.node(cable['n2id'])] if cable else [])
            self._fit_nodes([n for n in nodes if n])
        return True

    def clear_selection(self,event=None):
        self._drag_start=None;self.selected.clear();self.selected_item=None;self.clear_reference_highlight(repaint=False);self.render();return 'break'
    def open_selected_detail(self):
        if self.store is None:return None
        if self.selected_item:return open_reference_detail(self,*self.selected_item)
        self.notice.set('함체 또는 케이블을 선택하거나 코어ID를 검색하세요.');return None
    def open_core_trace(self):
        if self.selected_item and self.selected_item[0]=='core':return self.open_selected_detail()
        self.focus_find();self.notice.set('추적할 코어ID를 입력하고 Enter를 누르세요. 끊어진 구간을 포함해 모두 표시합니다.')
    def open_display_settings(self):return ReferenceDisplaySettings(self)

    def find_next(self,event=None):
        if self.store is None:return 'break'
        query=self.find_text.get().strip();results=drawing_search(self.store,query);signature=(query,self._source_token)
        if signature!=self._find_signature:self._find_signature=signature;self._find_index=-1
        if not results:
            self.clear_reference_highlight(owner=self);self.notice.set('검색 결과가 없습니다. 시설명·시설ID·케이블ID·코어ID를 입력하세요.');return 'break'
        self._find_index=(self._find_index+1)%len(results);result=results[self._find_index]
        kind,key=('node',result['node_id']) if 'node_id' in result else ('cable',result['cable_id']) if 'cable_id' in result else ('core',result['core_id'])
        self.select_item(kind,key,center=True);self.notice.set(f"찾기 {self._find_index+1}/{len(results)} · {result['kind']} · {result['identifier']} · 선택 내역으로 확인")
        return 'break'

    def sync_selection(self):
        self.reload_source()
        if self.store is None:return
        selection=tuple(sorted(self.app.selected));self._selection_token=selection
        for key in selection:
            if self.store.node(key):self.select_item('node',key,center=True);return
            if self.store.cable(key):self.select_item('cable',key,center=True);return
        self.notice.set('작업창에서 선택한 시설·케이블이 참고 도면에 없습니다.' if selection else '작업창에서 함체 또는 케이블을 먼저 선택하세요.')
    def focus_find(self,event=None):self.find_entry.focus_set();self.find_entry.selection_range(0,'end');return 'break'
    def close_key(self,event=None):self.destroy();return 'break'

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
        self._closed=True;self.clear_reference_highlight(repaint=False)
        for job in (self._poll_job,self._fit_job):
            if job is not None:
                try:self.after_cancel(job)
                except tk.TclError:pass
        self._poll_job=None;self._fit_job=None;self._close_details()
        if self.reference_snapshot is not None:self.reference_snapshot.close();self.reference_snapshot=None;self.store=None
        registry=getattr(self.app,'_reference_drawings',{})
        if registry.get(self.source_kind) is self:registry.pop(self.source_kind,None)
        if getattr(self.app,'_reference_drawing',None) is self:self.app._reference_drawing=None
        super().destroy()


class ReferenceDisplaySettings(RememberedToplevel):
    def __init__(self,view):
        self._stage_kind=view.source_kind;self._stage_reference=True
        super().__init__(view);self.view=view;self.title('보기설정');self.resizable(False,False)
        namespace=type(view.app).__init__.__globals__;self.values={}
        frame=ttk.Frame(self,padding=14);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='이 참고 도면 창의 화면 표시만 바꿉니다.').pack(anchor='w',pady=(0,8))
        for group,keys in namespace['DISPLAY_GROUPS']:
            section=ttk.LabelFrame(frame,text=group,padding=8);section.pack(fill='x',pady=3)
            for key in keys:
                variable=tk.BooleanVar(value=view.display_options[key]);self.values[key]=variable
                ttk.Checkbutton(section,text=namespace['DISPLAY_LABELS'][key],variable=variable).pack(anchor='w')
        buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=(10,0))
        ttk.Button(buttons,text='닫기',command=self.destroy).pack(side='right')
        ttk.Button(buttons,text='적용',command=self.apply).pack(side='right',padx=5)
        for seq in ('<Control-s>','<Control-S>','<Control-z>','<Control-Z>','<Control-y>','<Control-Y>','<Control-f>','<Control-F>'):
            self.bind(seq,lambda e:'break')
        self.bind('<Escape>',lambda e:(self.destroy(),'break')[1])
        apply_stage_window_chrome(self,view.source_kind,True)
    def apply(self):
        if not self.view._closed:self.view.display_options={key:var.get() for key,var in self.values.items()};self.view.render()
        self.destroy()


class ReferenceDrawingChooser(RememberedToplevel):
    def __init__(self,app):
        super().__init__(app);self.app=app;self.title('도면 새 창으로 열기');self.geometry('560x450');self.resizable(False,False)
        frame=ttk.Frame(self,padding=20);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='각 도면을 다른 모니터에 띄워 보세요.',style='Title.TLabel').pack(anchor='w',pady=(0,8))
        ttk.Label(frame,text='새 창은 저장된 도면을 보여 줍니다. 현재 작업창에서 계속 편집할 수 있습니다.\n창마다 확대·이동·검색과 내역 확인을 따로 할 수 있습니다.',wraplength=485).pack(anchor='w',pady=(0,16))
        self.stage_buttons={}
        for kind in ('gis','before','after'):
            button=tk.Button(frame,text=STAGE_WINDOW_NAMES[kind]+' · 새 창으로 열기',command=lambda k=kind:self.open_kind(k),
                bg=STAGE_WINDOW_COLORS[kind],fg='white',activebackground=STAGE_WINDOW_COLORS[kind],activeforeground='white',
                font=('Malgun Gothic',10,'bold'),relief='flat',padx=12,pady=9,cursor='hand2')
            button.pack(fill='x',pady=4);self.stage_buttons[kind]=button
        ttk.Label(frame,text='저장본이 없는 단계는 먼저 작업창에서 생성·저장하세요.',style='Muted.TLabel').pack(anchor='w',pady=(12,0))
        self.refresh_availability()
        for seq in ('<Control-s>','<Control-S>','<Control-z>','<Control-Z>','<Control-y>','<Control-Y>','<Control-f>','<Control-F>'):
            self.bind(seq,lambda e:'break')
        self.bind('<Escape>',lambda e:(self.destroy(),'break')[1]);self.protocol('WM_DELETE_WINDOW',self.destroy)
    def refresh_availability(self):
        for kind,button in self.stage_buttons.items():button.configure(state='normal' if self.app.scenario_path(kind).is_file() else 'disabled')
    def open_kind(self,kind):return open_reference_drawing(self.app,kind)
    def destroy(self):
        if getattr(self.app,'_reference_chooser',None) is self:self.app._reference_chooser=None
        super().destroy()


def open_reference_drawing(app,kind=None):
    if kind is None:
        dialog=getattr(app,'_reference_chooser',None)
        if dialog is not None and dialog.winfo_exists():dialog.refresh_availability();dialog.deiconify();dialog.lift();return dialog
        dialog=ReferenceDrawingChooser(app);app._reference_chooser=dialog;return dialog
    if kind not in ('gis','before','after'):raise ValueError('알 수 없는 도면 단계입니다.')
    if not hasattr(app,'_reference_drawings'):app._reference_drawings={}
    dialog=app._reference_drawings.get(kind)
    if dialog is not None and dialog.winfo_exists():dialog.reload_source();dialog.deiconify();dialog.lift();return dialog
    dialog=ReferenceDrawingDialog(app,kind);app._reference_drawings[kind]=dialog;return dialog


def close_reference_drawings(app):
    for dialog in list(getattr(app,'_reference_drawings',{}).values()):dialog.destroy()
    chooser=getattr(app,'_reference_chooser',None)
    if chooser is not None and chooser.winfo_exists():chooser.destroy()
    legacy=getattr(app,'_reference_drawing',None)
    if legacy is not None and legacy.winfo_exists():legacy.destroy()
