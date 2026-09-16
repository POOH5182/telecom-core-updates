"""One selected after-drawing core: map selection and explicit physical numbers.

Clicks build a read-only draft. A sealed, reviewed transaction writes only empty
chosen slots and required local splices, preserving every existing component.
"""


class ManualCoreAllocator(AfterAllocator):
    def __init__(self,app,source):
        super().__init__(app);self.source=tuple(source);self.load()

    def load(self):
        self.current();self.route_service=AfterRoutePlanner(self.app);self.ctx=self.route_service.context()
        self.net=self.ctx['net'];row=self.net.slots.get(self.source)
        if not row or not str(row.get('core_id') or '').strip():raise ValueError('배분할 코어ID가 있는 번호를 선택하세요.')
        self.core_id=str(row['core_id']).strip();self.key=json.dumps(['id',self.core_id],ensure_ascii=False,separators=(',',':'))
        if self.key not in self.ctx['entries']:raise ValueError('이 코어는 후도면 배정 대상에서 제외된 상태입니다. 신호·상태를 확인하세요.')
        self.problem=self.route_service.problem(self.key,self.ctx)
        if self.problem['entry'].get('exception_complete'):raise ValueError('예외 완료 처리된 코어입니다. 상태를 먼저 확인하세요.')
        self.existing={}
        for part in self.problem['components']:
            for cable,index in part['slots']:
                if cable in self.net.cables and cable not in self.existing:self.existing[cable]=index
        self.snapshot=plan_snapshot(self.store.conn)
        self.rows={(r['cable_id'],int(r['core_index'])):r for r in self.snapshot['cores']}
        self.pairs={allocation_pair(s['node_id'],(s['cable1_id'],s['core1_index']),(s['cable2_id'],s['core2_index'])) for s in self.snapshot['splices']}
        self.occupied={s for _,a,b in self.pairs for s in (a,b)}
        self.fixed={tuple(json.loads(k)) for k in self.ctx['data']['fixed_slots']}
        for n in self.net.nodes.values():
            extra=json.loads(n.get('extra_json') or '{}')
            for name in ('autoSameNumberExcluded','assignmentExceptions'):
                values=extra.get(name,{})
                if not isinstance(values,(dict,list)):continue
                for key in values:
                    if isinstance(values,dict) and not values[key]:continue
                    try:c,i=key.rsplit('::',1);self.fixed.add((c,int(i)))
                    except (ValueError,AttributeError):pass
        self.locked_nodes={n for n in self.net.nodes if node_locked(self.store,n)}
        self.drawing_locked=locked(self.store)
        self.stamp=self.token()

    def fresh(self):
        self.current()
        if self.token()!=self.stamp:raise ValueError('도면·잠금·계획이 변경되었습니다. 새로고침한 뒤 선번을 다시 선택하세요.')

    def availability(self,cable,index):
        slot=(cable,index);row=self.rows.get(slot);c=self.net.cables.get(cable)
        if not row or not c:return False,'철거·절단되었거나 없는 번호'
        if self.existing.get(cable)==index:return False,'기존 연결 선번 유지'
        if cable in self.existing:return False,'이 케이블은 기존 선번 '+str(self.existing[cable])+'번 유지'
        if self.drawing_locked or {c['n1id'],c['n2id']}&self.locked_nodes:return False,'함체·케이블 잠금'
        if slot in self.fixed:return False,'고정·예약·배정 예외 번호'
        if slot in self.occupied:return False,'기존 접속 사용 중'
        if plan_used(row):return False,'기존 코어ID·내역·신호·상태 사용 중'
        return True,'빈 번호 · 클릭하여 선택'

    def ordered_route(self,selected):
        cables=set(selected);adj=defaultdict(list)
        for cid in cables:
            c=self.net.cables.get(cid)
            if not c:raise ValueError('철거·절단 케이블은 배분할 수 없습니다.')
            a,b=c['n1id'],c['n2id'];adj[a].append((b,cid));adj[b].append((a,cid))
        ends=sorted(n for n,links in adj.items() if len(links)==1)
        if len(ends)!=2 or any(len(links)>2 for links in adj.values()):
            raise ValueError('선택 케이블이 아직 하나의 경로로 이어지지 않습니다. 끊긴 구간을 잇는 케이블을 고르세요. 분기·순환은 배정할 수 없습니다.')
        nodes=[ends[0]];ordered=[];seen=set()
        while True:
            choices=[(n,c) for n,c in adj[nodes[-1]] if c not in seen]
            if not choices:break
            if len(choices)!=1:raise ValueError('케이블 경로가 여러 방향으로 나뉩니다.')
            n,c=choices[0];seen.add(c);ordered.append(c);nodes.append(n)
        if seen!=cables:raise ValueError('분리된 구간이 남아 있습니다. 모든 기존 구간을 연결하세요.')
        route=dict(ok=True,nodes=nodes,cables=ordered,endpoints=ends,source='수동 코어분배')
        self.route_service.validate(self.problem,route)
        return route

    def preview(self,selected):
        self.fresh()
        if self.problem['blocks']:raise ValueError(' / '.join(self.problem['blocks']))
        chosen={str(c):int(n) for c,n in selected.items()}
        if any(chosen.get(c)!=n for c,n in self.existing.items()):raise ValueError('기존 구간의 선번을 모두 유지하세요.')
        for c,n in chosen.items():
            if c not in self.existing:
                allowed,reason=self.availability(c,n)
                if not allowed:raise ValueError(plan_number_label(self.net,(c,n))+': '+reason)
        route=self.ordered_route(chosen)
        records=[self.net.slots[s] for s in self.net.by_id[self.core_id]]
        known={str(r.get('signal') or '') for r in records}-{'','unknown','확인필요'}
        if len(known)>1 or known-{'on','off','exception'}:raise ValueError('기존 구간의 신호 불일치·오류를 먼저 확인하세요.')
        if any('error' in statuses(r) for r in records):raise ValueError('기존 코어의 오류 상태를 먼저 확인하세요.')
        source=self.net.slots[self.source]
        metadata=tuple(self.core_id if f=='core_id' else next(iter(known),'unknown') if f=='signal' else str(source.get(f) or '') for f in PLAN_FIELDS)
        ports={}
        for n in route['endpoints']:
            if self.net.nodes[n]['type']=='rn':
                options=[s for s in self.net.by_id[self.core_id] if s[0]=='PORT:'+n]
                if len(options)!=1:raise ValueError(self.net.nodes[n]['name']+': 사용할 RN 내부포트를 먼저 지정하세요.')
                ports[n]=options[0]
        candidate=dict(current={c:(c,n) for c,n in self.existing.items()},route=route,metadata=metadata,ports=ports)
        context=dict(candidates={self.key:candidate},rows=self.rows,pairs=self.pairs,net=self.net,locked_nodes=self.locked_nodes)
        projected=self.project(context,{self.key},{(self.key,c):n for c,n in chosen.items()})
        if projected['failed']:raise ValueError(' / '.join(projected['failed'].values()))
        proposal=dict(source=self.source,core_id=self.core_id,token=self.stamp,selected=chosen,route=route,
                      new=projected['new'],splices=projected['final'],added=projected['additions'],removed=projected['removed'])
        self.validate_final(proposal)
        proposal['seal']=self.seal(proposal)
        return proposal

    @staticmethod
    def seal(p):
        return digest([p['source'],p['core_id'],p['token'],sorted(p['selected'].items()),p['route'],
                       sorted(p['new'].items()),sorted(p['splices']),sorted(p['added']),sorted(p['removed'])])

    def validate_final(self,p):
        # Simulate only in memory, without triggers, history, or baseline writes.
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row
        try:
            for table in ('nodes','cables','cores','ports','splices','core_annotations'):
                conn.execute(self.store.conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone()[0])
                for row in self.snapshot[table]:
                    conn.execute('INSERT INTO '+table+' ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
            for slot,values in p['new'].items():conn.execute('UPDATE cores SET core_id=?,detail=?,status1=?,status2=?,signal=? WHERE cable_id=? AND core_index=?',values+slot)
            conn.execute('DELETE FROM splices')
            conn.executemany('INSERT INTO splices VALUES(?,?,?,?,?)',[(n,*a,*b) for n,a,b in p['splices']])
            check=Network(conn,active_only=True).inspect(self.core_id,{**DEFAULTS,'check_details':False,'reject_temporary':False})
            if not check['complete']:raise ValueError('배정 후 연결을 완료할 수 없습니다: '+' / '.join(check['notes']))
        finally:conn.close()

    def apply(self,proposal):
        self.fresh()
        if self.seal(proposal)!=proposal.get('seal'):raise ValueError('배정안이 변경되었습니다. 다시 확인하세요.')
        p=self.preview(proposal['selected'])
        if p['seal']!=proposal['seal']:raise ValueError('배정안이 변경되었습니다. 다시 확인하세요.')
        if not p['new'] and not p['added'] and not p['removed']:raise ValueError('이미 연결된 경로입니다. 적용할 변경이 없습니다.')
        backup=self.store.path.parent/'backups'/('before_manual_allocation_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.sqlite3')
        self.store.backup_to(backup)
        expected={slot:tuple(row[f] for f in PLAN_FIELDS) for slot,row in self.rows.items()};expected.update(p['new'])
        with self.store.action('수동 코어분배'):
            self._apply_rows(self.snapshot,expected,p['splices'],lambda s:s)
            actual=plan_snapshot(self.store.conn)
            if {(r['cable_id'],r['core_index']):tuple(r[f] for f in PLAN_FIELDS) for r in actual['cores']}!=expected:
                raise ValueError('코어내역 검사가 실패하여 배정을 취소했습니다.')
            for table in ('nodes','cables','ports','core_annotations','survey_rows'):
                if actual[table]!=self.snapshot[table]:raise ValueError('기존 정보 보존 검사가 실패하여 배정을 취소했습니다.')
            pairs={allocation_pair(r['node_id'],(r['cable1_id'],r['core1_index']),(r['cable2_id'],r['core2_index'])) for r in actual['splices']}
            if pairs!=p['splices']:raise ValueError('접속 검사가 실패하여 배정을 취소했습니다.')
            check=Network(self.store.conn,active_only=True).inspect(self.core_id,{**DEFAULTS,'check_details':False,'reject_temporary':False})
            if not check['complete']:raise ValueError('연결 검사 실패: '+' / '.join(check['notes']))
            service=AfterRoutePlanner(self.app);current=service.problem(self.key);data=plan_settings(self.store)
            previous=data.setdefault('route_step',{}).setdefault('decisions',{}).get(self.key,{})
            record=dict(previous,state='ok',signature=current['signature'],time=now(),core_id=self.core_id,
                        nodes=p['route']['nodes'],cables=p['route']['cables'],endpoints=p['route']['endpoints'],source='수동 코어분배')
            data['route_step']['decisions'][self.key]=record;plan_save(self.store,data,'수동 코어분배 경로 확정')
        return backup


class ManualAllocationReview(RememberedToplevel):
    def __init__(self,parent,text):
        super().__init__(parent);self.result=False;self.title('수동 코어분배 · 적용 전 확인');self.geometry('880x640');self.transient(parent);self.grab_set()
        ttk.Label(self,text='선택한 코어의 선번과 함체 접속을 아래 내용대로 적용합니다.',padding=12).pack(fill='x')
        footer=ttk.Frame(self,padding=12);footer.pack(side='bottom',fill='x')
        ttk.Button(footer,text='배정·접속 적용',command=self.confirm).pack(side='right')
        ttk.Button(footer,text='돌아가기',command=self.destroy).pack(side='right',padx=8)
        field_set_text(field_readonly_text(self,18),text)
        self.bind('<Escape>',lambda e:self.destroy())
    def confirm(self):self.result=True;self.destroy()


class ManualAllocationActions:
    CELL_W=220;CELL_H=54;GUTTER=48

    def build_sheet(self,sheetbox):
        ttk.Label(sheetbox,text='전체 선번표 · 흰색: 빈 번호 / 파랑: 기존 선택 코어 / 주황: 배정안 / 회색: 사용·잠금·예약 · 사용 중인 칸을 누르면 실제 연결을 확인합니다.',wraplength=1350,padding=4).grid(row=0,column=0,columnspan=2,sticky='ew')
        self.headers=tk.Canvas(sheetbox,height=60,bg='#e7edf5',highlightthickness=0);self.headers.grid(row=1,column=0,sticky='ew')
        self.sheet=tk.Canvas(sheetbox,bg='white',height=280,highlightthickness=0);self.sheet.grid(row=2,column=0,sticky='nsew')
        sheetbox.rowconfigure(2,weight=1);sheetbox.columnconfigure(0,weight=1)
        self.sy=ttk.Scrollbar(sheetbox,orient='vertical',command=self.sheet.yview);self.sy.grid(row=2,column=1,sticky='ns')
        self.sx=ttk.Scrollbar(sheetbox,orient='horizontal',command=self.scroll_x);self.sx.grid(row=3,column=0,sticky='ew')
        self.sheet.configure(yscrollcommand=self.sy.set,xscrollcommand=self.sx.set)
        self.sheet.bind('<Button-1>',self.sheet_click);self.headers.bind('<Button-1>',self.header_click)
        self.sheet.bind('<MouseWheel>',lambda e:self.sheet.yview_scroll(-3 if e.delta>0 else 3,'units'))

    def read_stamp(self):return (id(self.app.store),getattr(self.app.store,'_view_generation',0),self.app.store.data_revision(),self.app.store.conn.total_changes)

    def check_live(self):
        if self._watch is not None:
            try:self.after_cancel(self._watch)
            except tk.TclError:pass
        self._watch=None
        if self._closed:return
        if self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.service.generation:
            self.destroy();return
        if self.read_stamp()!=self.live_stamp:
            self.stale=True;self.apply_button.configure(state='disabled')
            self.message.set('도면이 변경되어 이전 배정안의 적용을 중지했습니다. 새로고침한 뒤 번호를 다시 선택하세요.')
            if getattr(self.app,'highlight_owner',None) is self:self.app.stop_highlight_blink(clear=True)
        self._watch=self.after(500,self.check_live)

    def history(self,redo=False):
        if self.app.store is not self.store or getattr(self.store,'_view_generation',0)!=self.service.generation:
            self.destroy();return 'break'
        self.app.change_history(redo=redo);self.check_live();return 'break'

    def run(self,fn):
        try:return fn()
        except (ValueError,sqlite3.Error,OSError) as error:
            self.message.set(str(error));messagebox.showwarning('코어분배',str(error),parent=self.winfo_toplevel())

    def reload(self):
        self.service.load();self.selected=dict(self.service.existing);self.columns=list(self.selected)
        self.inspect_cables=set();self.inspected=None;self.stale=False;self.live_stamp=self.read_stamp()
        self.apply_button.configure(state='normal');self.message.set('현재 저장된 도면으로 새로 불러왔습니다. 케이블과 번호를 선택하세요.');self.render()

    def add_cable(self,cid):
        self.service.fresh()
        if cid not in self.service.net.cables:raise ValueError('철거·절단 케이블은 배분할 수 없습니다.')
        if cid not in self.columns:self.columns.append(cid)
        self.active_cable=cid;self.message.set(self.cable_title(cid)+' · 아래 선번표에서 번호를 선택하세요.')
        self.render();width=self.GUTTER+self.CELL_W*len(self.columns)
        self.scroll_x('moveto',max(0,(self.GUTTER+self.columns.index(cid)*self.CELL_W)/max(1,width)))

    def cable_title(self,cid):
        c=self.service.net.cables.get(cid,{})
        return (c.get('cable_id') or cid)+' / '+c.get('spec','')+' · '+' ↔ '.join(self.service.net.nodes.get(c.get(k),{}).get('name','?') for k in ('n1id','n2id'))

    def choose_slot(self,cid,index):
        self.service.fresh();self.active_cable=cid;self.inspected=(cid,index)
        self.inspect_cables=set();stack=[(cid,index)];seen=set()
        while stack:
            slot=stack.pop()
            if slot in seen:continue
            seen.add(slot)
            if slot[0] in self.service.net.cables:self.inspect_cables.add(slot[0])
            stack.extend(other for _,other in self.service.net.links[slot] if other not in seen)
        allowed,reason=self.service.availability(cid,index)
        if allowed:
            if self.selected.get(cid)==index:self.selected.pop(cid);self.message.set('배정안에서 '+str(index)+'번 선택을 해제했습니다.')
            else:self.selected[cid]=index;self.message.set(self.cable_title(cid)+f' · {index}번 배정안 선택 (적용 전)')
        else:self.message.set(reason+' · 해당 번호의 실제 연결을 표시합니다.')
        self.render()

    def remove_cable(self,cid):
        if cid in self.service.existing:self.message.set('기존 연결 구간은 유지됩니다.');return
        self.columns.remove(cid);self.selected.pop(cid,None);self.inspected=None;self.inspect_cables=set();self.render()

    def map_click(self,event):
        x=self.map.canvasx(event.x);y=self.map.canvasy(event.y)
        for item in reversed(self.map.find_overlapping(x-4,y-4,x+4,y+4)):
            for tag in self.map.gettags(item):
                if tag.startswith('manual_cable:'):self.run(lambda:self.add_cable(tag[13:]));return 'break'
        return 'break'

    def sheet_click(self,event):
        col=int((self.sheet.canvasx(event.x)-self.GUTTER)//self.CELL_W);index=int(self.sheet.canvasy(event.y)//self.CELL_H)+1
        if 0<=col<len(self.columns):
            cid=self.columns[col]
            if index<=int(self.service.net.cables[cid]['size']):self.run(lambda:self.choose_slot(cid,index))

    def header_click(self,event):
        x=self.headers.canvasx(event.x);col=int((x-self.GUTTER)//self.CELL_W)
        if 0<=col<len(self.columns) and x>=self.GUTTER+(col+1)*self.CELL_W-28:self.remove_cable(self.columns[col])

    def scroll_x(self,*args):self.sheet.xview(*args);self.headers.xview(*args)

    def render(self):
        self.render_sheet();self.render_details();self.draw_map();self.highlight()

    def render_sheet(self):
        self.sheet.delete('all');self.headers.delete('all');net=self.service.net
        width=self.GUTTER+len(self.columns)*self.CELL_W;count=max((net.cables[c]['size'] for c in self.columns),default=1)
        self.sheet.configure(scrollregion=(0,0,width,count*self.CELL_H));self.headers.configure(scrollregion=(0,0,width,60))
        for n in range(1,count+1):self.sheet.create_text(24,(n-.5)*self.CELL_H,text=str(n),fill='#475569')
        for col,cid in enumerate(self.columns):
            x=self.GUTTER+col*self.CELL_W;c=net.cables[cid]
            self.headers.create_rectangle(x,0,x+self.CELL_W,60,fill='#dbeafe' if cid in self.service.existing else '#ffedd5',outline='#cbd5e1')
            head=self.cable_title(cid)+'\n'+(f"기존 {self.selected[cid]}번 유지" if cid in self.service.existing else '선택 '+str(self.selected[cid])+'번' if cid in self.selected else '번호를 선택하세요')
            self.headers.create_text(x+8,28,anchor='w',width=self.CELL_W-36,text=head,font=('Malgun Gothic',9))
            if cid not in self.service.existing:self.headers.create_text(x+self.CELL_W-14,12,text='×',fill='#9a3412',font=('Malgun Gothic',12,'bold'))
            for n in range(1,int(c['size'])+1):
                row=self.service.rows[cid,n];allowed,reason=self.service.availability(cid,n)
                chosen=self.selected.get(cid)==n;existing=self.service.existing.get(cid)==n
                fill='#dbeafe' if existing else '#ffedd5' if chosen else 'white' if allowed else '#e5e7eb'
                y=(n-1)*self.CELL_H
                self.sheet.create_rectangle(x,y,x+self.CELL_W,y+self.CELL_H,fill=fill,outline='#d1d9e4',width=2 if chosen else 1,tags=(f'slot:{cid}:{n}',))
                linked=any(self.service.net.links[cid,n]);signal={'on':'ON','off':'OFF','unknown':'확인필요','':'확인필요'}.get(row['signal'],row['signal'])
                text=(str(row['core_id'] or '')+' · '+str(row['detail'] or '')).strip(' ·') or ('빈 번호' if allowed else reason)
                tail=('기존 연결 유지' if existing else '배정 예정' if chosen else '접속 있음' if linked else '접속 없음')+' · '+signal
                self.sheet.create_text(x+7,y+self.CELL_H/2,anchor='w',width=self.CELL_W-14,text=text+'\n'+tail,font=('Malgun Gothic',9),fill='#1e3a8a' if existing else '#172033')

    def render_details(self):
        s=self.service;lines=[]
        for i,part in enumerate(s.problem['components'],1):
            lines.append(f'기존 구간 {i}: '+' ↔ '.join(s.net.nodes[n]['name'] for n in part['nodes']))
            lines.extend('  '+plan_number_label(s.net,slot) for slot in part['slots'])
        lines.append('\n현재 배정안 (아직 저장되지 않음)')
        for cid in self.columns:lines.append(self.cable_title(cid)+' → '+(str(self.selected[cid])+'번' if cid in self.selected else '번호 미선택'))
        if self.inspected:
            slot=self.inspected;row=s.rows.get(slot,{})
            lines.append('\n확인 번호: '+plan_number_label(s.net,slot))
            lines.append('ID: '+str(row.get('core_id') or '(빈 번호)')+' / '+str(row.get('detail') or ''))
            cable=s.net.cables[slot[0]]
            for nid in (cable['n1id'],cable['n2id']):
                peers=[peer for node,peer in s.net.links[slot] if node==nid]
                lines.append(s.net.nodes[nid]['name']+': '+(' / '.join(plan_number_label(s.net,p)+' · '+str(s.net.slots[p].get('core_id') or '') for p in peers) if peers else '미접속'))
        if s.problem['blocks']:lines.append('\n확인 필요: '+' / '.join(s.problem['blocks']))
        field_set_text(self.details,'\n'.join(lines))

    def component_colors(self):
        return {c:ROUTE_PART_COLORS[i%len(ROUTE_PART_COLORS)] for i,p in enumerate(self.service.problem['components']) for c in p['cables']}

    def highlight(self):
        if self.stale:return
        colors={c:'#be185d' for c in self.inspect_cables};colors.update(self.component_colors())
        colors.update({c:ROUTE_ORANGE for c in self.selected if c not in self.service.existing})
        self.app.start_highlight_blink(colors,owner=self,core_labels={c:str(n)+'번' for c,n in self.selected.items()})

    def draw_map(self):
        self.map.delete('all');s=self.service;net=s.net
        cables={c['id']:c for c in s.snapshot['cables']};shown=set(cables)
        if self.scope!='전체':
            anchors=set(self.columns)|self.inspect_cables
            nodes={n for cid in anchors for n in (net.cables[cid]['n1id'],net.cables[cid]['n2id'])}
            shown=anchors|{cid for cid,c in cables.items() if {c['n1id'],c['n2id']}&nodes}
        nodes={n for cid in shown for n in (cables[cid]['n1id'],cables[cid]['n2id']) if n in net.nodes}
        if not nodes:return
        w=max(350,self.map.winfo_width());h=max(220,self.map.winfo_height());xs=[net.nodes[n]['x'] for n in nodes];ys=[net.nodes[n]['y'] for n in nodes]
        scale=min((w-140)/max(1,max(xs)-min(xs)),(h-100)/max(1,max(ys)-min(ys)))
        pos={n:((net.nodes[n]['x']-(min(xs)+max(xs))/2)*scale+w/2,(net.nodes[n]['y']-(min(ys)+max(ys))/2)*scale+h/2) for n in nodes}
        groups=defaultdict(list)
        for cid in shown:
            c=cables[cid]
            if c['n1id'] in pos and c['n2id'] in pos:groups[tuple(sorted((c['n1id'],c['n2id'])))].append(cid)
        colors=self.component_colors()
        for (a,b),ids in groups.items():
            ax,ay=pos[a];bx,by=pos[b];length=max(1,math.hypot(bx-ax,by-ay))
            for i,cid in enumerate(sorted(ids)):
                bend=(i-(len(ids)-1)/2)*36;mx=(ax+bx)/2-(by-ay)/length*bend;my=(ay+by)/2+(bx-ax)/length*bend
                color=colors.get(cid,ROUTE_ORANGE if cid in self.selected else '#be185d' if cid in self.inspect_cables else '#64748b')
                tag='manual_cable:'+cid;c=cables[cid]
                if cid in self.inspect_cables:self.map.create_line(ax,ay,mx,my,bx,by,smooth=True,fill='#be185d',width=9,dash=(4,3),tags=(tag,))
                self.map.create_line(ax,ay,mx,my,bx,by,smooth=True,fill=color,width=5 if cid in self.selected else 3,dash=() if cid in net.cables else (5,4),tags=(tag,))
                label=(c['cable_id'] or cid)+' / '+c['spec']
                if cid in self.selected:label+='\n'+str(self.selected[cid])+'번'+(' 기존' if cid in s.existing else ' 배정안')
                elif cid in self.columns:label+='\n번호 미선택'
                self.map.create_text(mx,my-14,text=label,fill=color,font=('Malgun Gothic',9),tags=(tag,))
        for n,(x,y) in pos.items():
            self.map.create_oval(x-5,y-5,x+5,y+5,fill='white',outline='#334155',width=2)
            self.map.create_text(x,y+17,text=net.nodes[n]['name'],font=('Malgun Gothic',9,'bold'),fill='#172033')
        self.map.configure(scrollregion=(0,0,w,h))

    def zoom(self,event):
        factor=1.18 if event.delta>0 else 1/1.18;x=self.map.canvasx(event.x);y=self.map.canvasy(event.y)
        self.map.scale('all',x,y,factor,factor);self.map.configure(scrollregion=self.map.bbox('all'));return 'break'

    def toggle_scope(self):self.scope='경로 주변' if self.scope=='전체' else '전체';self.draw_map()

    def review_text(self,p):
        net=self.service.net;lines=['코어ID: '+p['core_id'],'','선택한 전체 경로']
        for cid in p['route']['cables']:lines.append(self.cable_title(cid)+' → '+str(p['selected'][cid])+'번'+(' (기존 유지)' if cid in self.service.existing else ' (새 배정)'))
        for title,pairs in (('추가할 함체 접속',p['added']),('철거·절단 케이블의 기존 접속 해체',p['removed'])):
            lines.extend(['',title])
            full=Network(self.store.conn) if p['removed'] else net
            lines.extend(full.nodes[n]['name']+': '+plan_number_label(full,a)+' ↔ '+plan_number_label(full,b) for n,a,b in sorted(pairs))
            if not pairs:lines.append('없음')
        lines.extend(['','기존 코어의 선번·내역과 전도면은 유지됩니다. 적용 직전 백업하며 Ctrl+Z로 전체 배정을 취소할 수 있습니다.'])
        return '\n'.join(lines)

    def apply(self):
        if any(c not in self.selected for c in self.columns):raise ValueError('번호를 선택하지 않은 케이블이 있습니다. 번호를 선택하거나 제목의 ×로 제외하세요.')
        proposal=self.service.preview(self.selected);review=ManualAllocationReview(self,self.review_text(proposal));self.wait_window(review)
        if not review.result:return
        self.service.apply(proposal);self.app.refresh();self.reload();self.message.set('선택한 코어의 선번·함체 접속을 적용했습니다. Ctrl+Z로 취소하거나 다른 코어를 선택하세요.')

    def return_to_core(self):
        editor=self.editor;self.destroy()
        if editor is not None and editor.winfo_exists():editor.deiconify();editor.lift();editor.focus_core(self.service.source[1])

    def destroy(self):
        if self._closed:return
        self._closed=True
        if self._watch is not None:
            try:self.after_cancel(self._watch)
            except tk.TclError:pass
        if getattr(self.app,'highlight_owner',None) is self:self.app.stop_highlight_blink(clear=True)
        if self.editor is not None:
            try:
                if self.editor.winfo_exists():self.editor._core_trace_enabled=True
            except tk.TclError:pass
        if getattr(self.app,'_manual_allocation_window',None) is self:self.app._manual_allocation_window=None
        super().destroy()


class ManualCoreAllocationDialog(ManualAllocationActions,RememberedToplevel):
    CELL_W=220;CELL_H=54;GUTTER=48

    def __init__(self,app,source,editor=None):
        service=ManualCoreAllocator(app,source)
        super().__init__(app);self.app=app;self.store=app.store;self.service=service;self.editor=editor
        self._closed=False;self._watch=None;self.stale=False;self.scope='전체';self.inspect_cables=set();self.inspected=None
        self.selected=dict(service.existing);self.columns=list(self.selected);self.active_cable=source[0]
        self.title('코어분배 · 도면과 선번 직접 선택');self.geometry('1420x900');self.minsize(960,680)
        self.protocol('WM_DELETE_WINDOW',self.destroy)
        for sequence in ('<Control-z>','<Control-Z>'):self.bind(sequence,lambda e:self.history(False))
        for sequence in ('<Control-y>','<Control-Y>'):self.bind(sequence,lambda e:self.history(True))
        row=service.net.slots[tuple(source)]
        title=ttk.Frame(self,padding=10);title.pack(fill='x')
        ttk.Label(title,text='코어분배 · '+service.core_id+' · '+str(row.get('detail') or ''),style='Title.TLabel').pack(side='left')
        toolbar=FlowToolbar(self);toolbar.pack(fill='x')
        toolbar.add(ttk.Button(toolbar,text='새로고침 · 배정안 초기화',command=lambda:self.run(self.reload)))
        toolbar.add(ttk.Button(toolbar,text='전체 / 경로 주변',command=self.toggle_scope))
        toolbar.add(ttk.Button(toolbar,text='도면 맞춤',command=self.draw_map))
        toolbar.add(ttk.Button(toolbar,text='다른 코어 선택',command=self.return_to_core))
        self.apply_button=toolbar.add(ttk.Button(toolbar,text='배정안 확인·적용',command=lambda:self.run(self.apply)))
        toolbar.add(ttk.Button(toolbar,text='닫기 · 배정안 취소',command=self.destroy))
        self.message=tk.StringVar(value='도면에서 케이블 클릭 → 아래 선번표에서 빈 번호 클릭 → 배정안 확인·적용. 기존 선번은 유지됩니다.')
        ttk.Label(self,textvariable=self.message,padding=(12,5),wraplength=1350,foreground='#1769aa').pack(fill='x')
        panes=ttk.Panedwindow(self,orient='vertical');panes.pack(fill='both',expand=True,padx=10,pady=(0,8))
        upper=ttk.Panedwindow(panes,orient='horizontal');panes.add(upper,weight=1)
        mapbox=ttk.Frame(upper);detailbox=ttk.Frame(upper,width=340);upper.add(mapbox,weight=3);upper.add(detailbox,weight=1)
        self.map=tk.Canvas(mapbox,bg='#f7f9fc',height=290,highlightthickness=0)
        self.map.grid(row=0,column=0,sticky='nsew');mapbox.rowconfigure(0,weight=1);mapbox.columnconfigure(0,weight=1)
        sy=ttk.Scrollbar(mapbox,orient='vertical',command=self.map.yview);sy.grid(row=0,column=1,sticky='ns')
        sx=ttk.Scrollbar(mapbox,orient='horizontal',command=self.map.xview);sx.grid(row=1,column=0,sticky='ew')
        self.map.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.map.bind('<Configure>',lambda e:self.draw_map());self.map.bind('<Button-1>',self.map_click)
        self.map.bind('<MouseWheel>',self.zoom)
        self.map.bind('<ButtonPress-2>',lambda e:self.map.scan_mark(e.x,e.y));self.map.bind('<B2-Motion>',lambda e:self.map.scan_dragto(e.x,e.y,gain=1))
        ttk.Label(detailbox,text='기존 연결 · 배정안 · 선택 번호 확인',padding=6).pack(fill='x')
        self.details=field_readonly_text(detailbox,10)
        sheetbox=ttk.Frame(panes);panes.add(sheetbox,weight=1)
        self.build_sheet(sheetbox)
        if editor:
            editor.clear_core_trace();editor._core_trace_enabled=False
        self.live_stamp=self.read_stamp();self.render();self._watch=self.after(500,self.check_live)


class MapCoreAllocationPanel(ManualAllocationActions,ttk.Frame):
    """Keep the main map interactive while one core's explicit draft is open."""
    GRID_H=28

    def __init__(self,app,source,editor):
        service=ManualCoreAllocator(app,source)
        super().__init__(app,padding=(10,4))
        self.app=app;self.store=app.store;self.service=service;self.editor=editor
        self._closed=False;self._watch=None;self.stale=False;self.scope='전체';self.inspect_cables=set();self.inspected=None
        self.selected=dict(service.existing);self.columns=list(self.selected);self.active_cable=source[0]
        self._size_binding=None;self._resize_job=None;self._grid_columns=12
        self.dashboard_visible=bool(app.dashboard_frame.place_info())
        app.cancel_left_pan();app.drag_anchor=None;app.pending_drag=None;app.selected.clear()
        app.mode='select';app.cable_start=None
        self.configure(height=self.panel_height());self.pack_propagate(False)
        self.pack(side='bottom',fill='x',before=app.canvas_frame)
        app.dashboard_frame.place_forget()
        toolbar=FlowToolbar(self);toolbar.pack(fill='x')
        toolbar.add(ttk.Label(toolbar,text='코어배정 중 · '+service.core_id,font=('Malgun Gothic',10,'bold')))
        self.apply_button=toolbar.add(ttk.Button(toolbar,text='배정안 확인·적용',command=lambda:self.run(self.apply),style='Primary.TButton'))
        toolbar.add(ttk.Button(toolbar,text='전체도면 맞춤',command=app.fit_view))
        toolbar.add(ttk.Button(toolbar,text='배정안 초기화',command=lambda:self.run(self.reload)))
        toolbar.add(ttk.Button(toolbar,text='코어 선택으로 돌아가기',command=self.close_requested))
        self.message=tk.StringVar(value='도면 케이블 클릭 → 아래 빈 번호 클릭 → 배정안 확인·적용. 다른 사용 번호를 누르면 접속 경로를 확인합니다.')
        self.message_label=ttk.Label(self,textvariable=self.message,foreground='#1769aa',padding=(2,2))
        self.message_label.pack(fill='x')
        body=ttk.Panedwindow(self,orient='horizontal');body.pack(fill='both',expand=True)
        left=ttk.Frame(body);right=ttk.Frame(body,width=300);body.add(left,weight=3);body.add(right,weight=1)
        self.cable_status=tk.StringVar();ttk.Label(left,textvariable=self.cable_status,font=('Malgun Gothic',9,'bold'),wraplength=650).grid(row=0,column=0,columnspan=2,sticky='ew')
        self.sheet=tk.Canvas(left,bg='white',highlightthickness=0,width=600,height=190)
        self.sheet.grid(row=1,column=0,sticky='nsew');left.rowconfigure(1,weight=1);left.columnconfigure(0,weight=1)
        self.sy=ttk.Scrollbar(left,orient='vertical',command=self.sheet.yview);self.sy.grid(row=1,column=1,sticky='ns')
        self.sheet.configure(yscrollcommand=self.sy.set)
        self.sheet.bind('<Button-1>',self.sheet_click);self.sheet.bind('<Configure>',lambda e:self.render_sheet())
        self.sheet.bind('<MouseWheel>',lambda e:self.sheet.yview_scroll(-3 if e.delta>0 else 3,'units'))
        self.sheet.bind('<Motion>',self.hover_slot)
        self.hover=tk.StringVar(value='흰색: 빈 번호 · 파랑: 기존 연결 · 주황: 배정안 · 회색: 사용·잠금·예약')
        ttk.Label(left,textvariable=self.hover,wraplength=650).grid(row=2,column=0,columnspan=2,sticky='ew')
        ttk.Label(right,text='기존 구간 · 배정안 · 양쪽 접속',padding=2).pack(fill='x')
        self.details=field_readonly_text(right,6)
        self.details.configure(width=34)
        editor.clear_core_trace();editor._core_trace_enabled=False
        self.editor_grab=editor.grab_current() is editor
        if self.editor_grab:editor.grab_release()
        editor.withdraw();app._map_allocation_panel=self
        self.live_stamp=self.read_stamp();self.render();self._watch=self.after(500,self.check_live)
        self._size_binding=app.bind('<Configure>',self.resize_panel,add='+')
        app.update_idletasks();app.lift();app.canvas.focus_set()
        app.status.set('코어배정 중 · '+service.core_id+' · 케이블을 클릭하면 아래에 전체 선번이 표시됩니다.')

    def panel_height(self):
        available=self.app.canvas_frame.winfo_height()+(self.winfo_height() if self.winfo_ismapped() else 0)
        return max(210,min(340,int(available*.43)))

    def resize_panel(self,event):
        if event.widget is self.app and not self._closed:
            self.message_label.configure(wraplength=max(650,event.width-35))
            if self._resize_job is None:self._resize_job=self.after_idle(self.resize_fit)

    def resize_fit(self):
        self._resize_job=None
        if not self._closed:self.configure(height=self.panel_height())

    def draw_map(self):pass # The real App canvas retains its viewport, zoom and panning.

    def add_cable(self,cid):
        self.service.fresh()
        if cid not in self.service.net.cables:raise ValueError('철거·절단 케이블은 배분할 수 없습니다.')
        if cid not in self.columns:self.columns.append(cid)
        self.active_cable=cid;self.inspected=None;self.inspect_cables=set()
        self.message.set(self.cable_title(cid)+' · 빈 번호 클릭: 배정안 선택 / 사용 번호 클릭: 실제 접속 확인')
        self.sheet.yview_moveto(0);self.render()

    def render_sheet(self):
        if self._closed:return
        self.sheet.delete('all');s=self.service;cid=self.active_cable
        if cid not in s.net.cables:return
        count=int(s.net.cables[cid]['size']);width=max(260,self.sheet.winfo_width())
        self._grid_columns=max(8,min(24,width//32));cell=width/self._grid_columns
        height=math.ceil(count/self._grid_columns)*self.GRID_H
        self.sheet.configure(scrollregion=(0,0,width,height))
        empty=allowed_count=0
        for index in range(1,count+1):
            row=s.rows[cid,index];allowed,reason=s.availability(cid,index)
            empty+=not plan_used(row) and (cid,index) not in s.occupied;allowed_count+=allowed
            chosen=self.selected.get(cid)==index;existing=s.existing.get(cid)==index
            fill='#dbeafe' if existing else '#ffedd5' if chosen else 'white' if allowed else '#e5e7eb'
            x=((index-1)%self._grid_columns)*cell;y=((index-1)//self._grid_columns)*self.GRID_H
            self.sheet.create_rectangle(x+1,y+1,x+cell-1,y+self.GRID_H-1,fill=fill,outline='#f97316' if chosen and not existing else '#94a3b8',width=2 if chosen else 1,tags=('number:'+str(index),))
            self.sheet.create_text(x+cell/2,y+self.GRID_H/2,text=str(index),fill='#1e3a8a' if existing else '#172033',tags=('number:'+str(index),))
        self.cable_status.set(self.cable_title(cid)+f' · 전체 {count} / 빈 {empty} / 선택 가능 {allowed_count}')

    def pointer_number(self,event):
        x=self.sheet.canvasx(event.x);y=self.sheet.canvasy(event.y);width=max(260,self.sheet.winfo_width())
        if x<0 or x>=width or y<0:return None
        index=int(y//self.GRID_H)*self._grid_columns+int(x/(width/self._grid_columns))+1
        if index<=int(self.service.net.cables[self.active_cable]['size']):return index

    def sheet_click(self,event):
        index=self.pointer_number(event)
        if index is not None:self.run(lambda:self.choose_slot(self.active_cable,index))
        return 'break'

    def hover_slot(self,event):
        index=self.pointer_number(event)
        if index is None:return
        row=self.service.rows[self.active_cable,index];reason=self.service.availability(self.active_cable,index)[1]
        self.hover.set(f"{index}번 · {row['core_id'] or '(ID 없음)'} · {row['detail'] or '(내역 없음)'} · {reason}")

    def highlight(self):
        if self.stale:return
        colors={c:'#be185d' for c in self.inspect_cables};colors.update(self.component_colors())
        colors.update({c:ROUTE_ORANGE for c in self.selected if c not in self.service.existing})
        colors.setdefault(self.active_cable,'#0891b2')
        labels={c:str(n)+'번'+(' 기존' if c in self.service.existing else ' 배정안') for c,n in self.selected.items()}
        if self.inspected:
            labels[self.inspected[0]]=labels.get(self.inspected[0],'')+' · 확인 '+str(self.inspected[1])+'번'
        self.app.start_highlight_blink(colors,owner=self,core_labels=labels)

    def apply(self):
        # Visiting a cable only inspects capacity; only selected numbers enter the route.
        proposal=self.service.preview(self.selected)
        review=ManualAllocationReview(self.app,self.review_text(proposal));self.wait_window(review)
        if not review.result:return
        self.service.apply(proposal);self.app.refresh();self.reload()
        self.message.set('선번과 함체 접속 적용 완료 · Ctrl+Z로 취소 가능 · 코어 선택으로 돌아가 다음 코어를 배정하세요.')

    def close_requested(self):
        if self.selected!=self.service.existing and not messagebox.askyesno('배정안 취소','아직 적용하지 않은 선번 선택을 취소하고 코어 선택으로 돌아갈까요?',parent=self.app):return False
        self.destroy();return True

    def destroy(self,restore_editor=True):
        if self._closed:return
        valid=self.app.store is self.store and getattr(self.store,'_view_generation',0)==self.service.generation
        if self._resize_job is not None:self.after_cancel(self._resize_job);self._resize_job=None
        if self._size_binding is not None:self.app.unbind('<Configure>',self._size_binding);self._size_binding=None
        if getattr(self.app,'_map_allocation_panel',None) is self:self.app._map_allocation_panel=None
        if self.dashboard_visible:self.app.dashboard_frame.place(relx=1.0,x=-24,y=18,anchor='ne')
        editor=self.editor
        super().destroy()
        if restore_editor and valid and editor is not None and editor.winfo_exists():
            editor.deiconify();editor.lift();editor.focus_core(self.service.source[1]);editor.queue_core_trace()
            if self.editor_grab:editor.grab_set()
