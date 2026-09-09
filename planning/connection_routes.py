"""Read-only, slot-based directional route review before a local connection."""

CONNECTION_ROUTE_COLORS=('#ff7a00','#7c3aed')


def connection_route_report(store,node_id,left,right,context=None):
    """Cut only the selected local joins, then follow actual splices outwards.

    IDs are labels, never edges. Every branch is visited; repeated states are
    reported and stopped so corrupt or circular drawings cannot loop forever.
    """
    context=context or store.trace_context()
    nodes,cables,rows,links=(context[k] for k in ('nodes','cables','row_by_slot','links'))
    selected={tuple(left),tuple(right)}
    name=lambda nid:str(nodes.get(nid,{}).get('name') or '?')
    # SQLite node/cable rows support [] but not .get().
    nodes={nid:dict(n) for nid,n in nodes.items()};cables={cid:dict(c) for cid,c in cables.items()}
    def slot_name(slot):
        row=rows.get(slot,{})
        if slot[0].startswith('PORT:'):return name(slot[0][5:])+' / '+str(row.get('label') or slot[1])
        cable=cables.get(slot[0],{})
        return str(cable.get('cable_id') or cable.get('spec') or slot[0])+f' / {slot[1]}번'
    def local_links(slot):
        return [other for nid,other in links.get(slot,()) if nid==node_id]
    def outward_links(slot,nid):
        return sorted(other for n,other in links.get(slot,()) if n==nid
                      and not (nid==node_id and (slot in selected or other in selected)))
    def walk(start):
        side={'start':start,'rows':[],'slots':set(),'nodes':{},'paths':[[]],'ends':[],'issues':[],'local':local_links(start)}
        visited=set();stack=[(start,node_id,0,0)];arrivals={}
        while stack:
            slot,entry,path_index,depth=stack.pop();state_key=(slot,entry)
            if state_key in visited:
                side['issues'].append(name(entry)+' · '+slot_name(slot)+' 경로 재방문: 순환·중복 접속 확인');continue
            visited.add(state_key)
            if len(visited)>5000:
                side['issues'].append('경로가 5,000구간을 넘어 표시를 중단했습니다. 전체 확인이 필요합니다.');break
            row=rows.get(slot)
            if not row:side['issues'].append(slot_name(slot)+' · 삭제되었거나 존재하지 않는 코어');continue
            port=slot[0].startswith('PORT:');cable=cables.get(slot[0]);end='';note=''
            if port:
                exit_node=slot[0][5:]
                if entry!=exit_node:side['issues'].append(slot_name(slot)+' · 다른 시설의 내부 포트에 잘못 접속');continue
                end='내부 포트 끝';target=name(exit_node)+' / '+str(row.get('label') or slot[1])
                next_slots=[]
                if outward_links(slot,exit_node):
                    # A valid port is an endpoint. More than its incoming cable is invalid.
                    if len(outward_links(slot,exit_node))>1:side['issues'].append(target+' · 내부 포트 중복 접속')
            else:
                if not cable or entry not in (cable['n1id'],cable['n2id']):
                    side['issues'].append(slot_name(slot)+' · 시설과 케이블 접속 위치가 맞지 않음');continue
                exit_node=cable['n2id'] if entry==cable['n1id'] else cable['n1id'];target=name(exit_node)
                next_slots=outward_links(slot,exit_node)
                if not next_slots:
                    terminal=cable_terminal(nodes.get(exit_node),context['node_counts'].get(exit_node,0),context['extras'].get(exit_node,{}))
                    end='말단' if terminal else '미접속'
                if len(next_slots)>1:side['issues'].append(target+' · '+slot_name(slot)+' 분기·중복 접속 '+str(len(next_slots))+'개')
                if exit_node==node_id:side['issues'].append('현재 연결 함체 '+name(node_id)+'로 돌아오는 경로가 있습니다.')
            side['slots'].add(slot)
            side['nodes'].setdefault(entry,depth);side['nodes'].setdefault(exit_node,depth+1)
            arrival=(slot,entry)
            if exit_node in arrivals and arrivals[exit_node]!=arrival and not port:
                side['issues'].append(target+'를 같은 방향에서 다시 지납니다. 경로 중복 확인')
            arrivals[exit_node]=arrival
            if not str(row.get('core_id') or '').strip():note='빈 코어ID'
            if end:note=(note+' · ' if note else '')+end
            step={'slot':slot,'from_id':entry,'to_id':exit_node,'from':name(entry),'to':target,
                  'cable':('내부 포트' if port else str(cable.get('cable_id') or '(ID 없음)')+' / '+str(cable.get('spec') or str(cable['size'])+'C')),
                  'index':str(row.get('label') or slot[1]) if port else slot[1],
                  'core_id':str(row.get('core_id') or ''),'detail':str(row.get('detail') or ''),'note':note}
            side['rows'].append(step);side['paths'][path_index].append(step)
            if end:side['ends'].append(target+' ('+end+')')
            for offset,other in reversed(list(enumerate(next_slots))):
                other_row=rows.get(other,{})
                aid,bid=str(row.get('core_id') or ''),str(other_row.get('core_id') or '')
                if aid!=bid:side['issues'].append(target+' · 접속된 코어ID 다름: '+(aid or '(빈 ID)')+' ↔ '+(bid or '(빈 ID)'))
                branch=path_index
                if offset:branch=len(side['paths']);side['paths'].append([])
                stack.append((other,exit_node,branch,depth+1))
        side['issues']=list(dict.fromkeys(side['issues']));side['ends']=list(dict.fromkeys(side['ends']))
        return side
    sides=[walk(tuple(left)),walk(tuple(right))]
    shared_slots=sides[0]['slots']&sides[1]['slots']
    shared_cables={s[0] for s in sides[0]['slots'] if s[0] in cables}&{s[0] for s in sides[1]['slots'] if s[0] in cables}
    meeting_ids=(sides[0]['nodes'].keys()&sides[1]['nodes'].keys())-{node_id}
    meeting_ids=sorted(meeting_ids,key=lambda n:(max(s['nodes'][n] for s in sides),sum(s['nodes'][n] for s in sides),name(n),n))
    meetings=[]
    for nid in meeting_ids:
        at=[]
        for side in sides:
            at.append(list(dict.fromkeys(slot_name(r['slot']) for r in side['rows'] if nid in (r['from_id'],r['to_id']))))
        meetings.append({'node_id':nid,'name':name(nid),'sides':at})
    issues=[]
    if shared_slots:issues.append('양쪽이 다른 곳에서 이미 이어져 있습니다. 여기서 연결하면 순환 경로가 생길 수 있습니다. 겹친 코어: '+' / '.join(slot_name(s) for s in sorted(shared_slots)))
    different_cables=shared_cables-{s[0] for s in shared_slots}
    if different_cables:issues.append('같은 케이블의 서로 다른 코어를 양쪽에서 지납니다: '+' / '.join(str(cables[c].get('cable_id') or c) for c in sorted(different_cables)))
    for i,side in enumerate(sides,1):issues.extend(f'{i}번방향 · '+issue for issue in side['issues'])
    groups=[];colors={}
    for i,side in enumerate(sides):
        for row in side['rows']:
            row['draw_color']='#c62828' if row['slot'] in shared_slots else '#a16207' if row['slot'][0] in shared_cables else CONNECTION_ROUTE_COLORS[i]
            if row['slot'][0] in cables:colors[row['slot'][0]]=row['draw_color']
        groups.append({'number':i+1,'title':f'{i+1}번방향 · '+(' / '.join(side['ends']) or '끝점 없음·경로 확인 필요'),
                       'color':CONNECTION_ROUTE_COLORS[i],'paths':side['paths'],'issues':side['issues']})
    summary=[f'연결 지점: {name(node_id)} · 1번방향 주황 / 2번방향 보라 / 같은 코어 겹침 빨강 / 같은 케이블의 다른 코어 갈색']
    for i,side in enumerate(sides,1):summary.append(f'{i}번방향 도달 끝: '+(' / '.join(side['ends']) or '끝점 없음·경로 확인 필요'))
    if meetings:
        summary.append('다시 만나는 시설 (양쪽에서 가까운 순): '+' → '.join(m['name'] for m in meetings)+' · 같은 시설을 지나는 것만으로 서로 접속된 것은 아닙니다.')
    else:summary.append('현재 연결 지점 외에 양쪽이 함께 지나는 시설은 없습니다.')
    summary.extend(issues or ['현재 도면의 실제 접속 기준으로 겹친 케이블·코어 또는 순환 징후가 없습니다.'])
    return {'node_id':node_id,'node_name':name(node_id),'sides':sides,'shared_slots':shared_slots,'shared_cables':shared_cables,
            'meetings':meetings,'issues':issues,'summary':'\n'.join(summary),'groups':groups,'cable_colors':colors,'highlight':set(colors),
            'revision':store.data_revision(),'generation':getattr(store,'_view_generation',0)}


def connection_batch_warnings(pairs,reports):
    """Also catch loops created only by applying several reviewed pairs together."""
    parents={}
    def root(slot):
        parents.setdefault(slot,slot)
        while parents[slot]!=slot:
            parents[slot]=parents[parents[slot]];slot=parents[slot]
        return slot
    def join(a,b):parents[root(a)]=root(b)
    for report in reports:
        for side in report['sides']:
            for slot in side['slots']:join(side['start'],slot)
    warnings={}
    for i,(_,a,b) in enumerate(pairs):
        a,b=tuple(a),tuple(b)
        if root(a)==root(b) and not reports[i]['shared_slots']:
            warnings[i]='선택한 연결들을 함께 반영하면 이미 이어진 경로가 다시 연결되어 순환할 수 있습니다.'
        join(a,b)
    return warnings


class ConnectionRouteDialog(RememberedToplevel):
    """One review family for waiting pairs and field corrections, with no writes."""
    def __init__(self,parent,store,node_id,pairs,accept=None,changes=None):
        super().__init__(parent,position_family='ConnectionRouteDialog')
        self.app=top_app(parent);self.store=store;self.node_id=node_id;self.pairs=list(pairs);self.accepted=False;self._closed=False
        self.revision=store.data_revision();self.generation=getattr(store,'_view_generation',0);self._previous_grab=self.grab_current()
        context=store.trace_context();self.reports=[connection_route_report(store,node_id,a,b,context) for _,a,b in self.pairs]
        self.batch_warnings=connection_batch_warnings(self.pairs,self.reports)
        self.warning_pairs=[i for i,report in enumerate(self.reports) if report['issues'] or i in self.batch_warnings]
        self.title('연결 확인 · 양방향 코어 경로');self.geometry('1260x850');self.minsize(1000,680);self.transient(parent);self.grab_set()
        top=ttk.Frame(self,padding=8);top.pack(fill='x')
        ttk.Label(top,text='연결 지점: '+str(store.node(node_id)['name'])+'   1번방향 ↔ 2번방향',font=('Malgun Gothic',11,'bold')).pack(side='left')
        self.choice=ttk.Combobox(top,state='readonly',values=[f"{i+1}. {'[주의] ' if i in self.warning_pairs else ''}{p[0]}" for i,p in enumerate(self.pairs)],width=48)
        self.choice.pack(side='right');self.choice.bind('<<ComboboxSelected>>',self.render)
        ttk.Label(self,text='각 방향은 선택한 코어부터 실제 접속을 따라갑니다. 현재 함체의 선택 코어 접속을 제외하고 양쪽을 비교합니다. 전송 신호의 실제 송·수신 방향을 뜻하지 않습니다.',padding=(8,0,8,6),wraplength=1200).pack(fill='x')
        if self.warning_pairs:
            ttk.Label(self,text='경로 주의 '+str(len(self.warning_pairs))+'건: '+', '.join(str(i+1)+'번 '+self.pairs[i][0] for i in self.warning_pairs)+' · 위 목록에서 각 경로를 확인하세요.',foreground='#c62828',padding=(8,0,8,6),wraplength=1200).pack(fill='x')
        book=ttk.Notebook(self);book.pack(fill='both',expand=True,padx=8)
        page=ttk.Frame(book);book.add(page,text='양방향 경로·만나는 곳')
        info_frame=ttk.Frame(page);info_frame.pack(fill='x')
        self.info=tk.Text(info_frame,height=6,wrap='word',font=('Malgun Gothic',9));self.info.pack(side='left',fill='x',expand=True)
        info_scroll=ttk.Scrollbar(info_frame,orient='vertical',command=self.info.yview);info_scroll.pack(side='right',fill='y');self.info.configure(yscrollcommand=info_scroll.set)
        self.info.configure(state='disabled')
        pairbox=ttk.Frame(page);pairbox.pack(fill='both',expand=True);self.tables=[];self.headings=[]
        for i in range(2):
            frame=ttk.LabelFrame(pairbox,text=f'{i+1}번방향',padding=4);frame.pack(side='left',fill='both',expand=True,padx=3)
            heading=tk.StringVar();self.headings.append(heading)
            ttk.Label(frame,textvariable=heading,foreground=CONNECTION_ROUTE_COLORS[i],wraplength=570).pack(fill='x')
            holder=ttk.Frame(frame);holder.pack(fill='both',expand=True)
            columns=('from','cable','index','id','to','note');tree=SortableTreeview(holder,columns=columns,show='headings',height=6)
            for key,label,width in zip(columns,('출발 시설','케이블ID / 규격','코어번호','코어ID','도착 시설','확인내용'),(130,180,75,125,130,150)):
                tree.heading(key,text=label);tree.column(key,width=width,minwidth=60,stretch=False)
            tree.tag_configure('overlap',foreground='#c62828');tree.tag_configure('cable',foreground='#a16207')
            tree.grid(row=0,column=0,sticky='nsew');holder.rowconfigure(0,weight=1);holder.columnconfigure(0,weight=1)
            sy=ttk.Scrollbar(holder,orient='vertical',command=tree.yview);sy.grid(row=0,column=1,sticky='ns')
            sx=ttk.Scrollbar(holder,orient='horizontal',command=tree.xview);sx.grid(row=1,column=0,sticky='ew');tree.configure(xscrollcommand=sx.set,yscrollcommand=sy.set)
            self.tables.append(tree)
        frame=ttk.Frame(page);frame.pack(fill='both',expand=True,pady=5)
        self.diagram=tk.Canvas(frame,bg='white',height=210,highlightthickness=0);self.diagram.grid(row=0,column=0,sticky='nsew')
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        sx=ttk.Scrollbar(frame,orient='horizontal',command=self.diagram.xview);sx.grid(row=1,column=0,sticky='ew')
        sy=ttk.Scrollbar(frame,orient='vertical',command=self.diagram.yview);sy.grid(row=0,column=1,sticky='ns');self.diagram.configure(xscrollcommand=sx.set,yscrollcommand=sy.set)
        if changes:
            cp=ttk.Frame(book);book.add(cp,text='반영할 변경 내용')
            ct=SortableTreeview(cp,columns=('action','slot','detail'),show='headings')
            for key,label in zip(('action','slot','detail'),('처리','케이블·코어번호','내용')):ct.heading(key,text=label);ct.column(key,width=300)
            ct.pack(side='left',fill='both',expand=True);cy=ttk.Scrollbar(cp,orient='vertical',command=ct.yview);cy.pack(side='right',fill='y');ct.configure(yscrollcommand=cy.set)
            for row in changes:ct.insert('','end',values=row)
        bottom=ttk.Frame(self,padding=8);bottom.pack(fill='x');self.accept_button=None
        if accept:
            self.accept_button=ttk.Button(bottom,text=accept,command=self.confirm);self.accept_button.pack(side='right')
        ttk.Button(bottom,text='닫기 / 취소',command=self.destroy).pack(side='right',padx=6)
        self.status=tk.StringVar();ttk.Label(bottom,textvariable=self.status,wraplength=750).pack(side='left')
        self.bind('<Escape>',lambda e:self.destroy());self.protocol('WM_DELETE_WINDOW',self.destroy)
        if accept:
            pending=[self]
            while pending:
                widget=pending.pop();pending.extend(widget.winfo_children())
                if not isinstance(widget,(ttk.Combobox,tk.Text)):
                    widget.bind('<KeyPress-space>',lambda e:'break');widget.bind('<KeyRelease-space>',self.space_confirm)
        if self.pairs:self.choice.current(0);self.render()

    def current(self):
        return (not self.app or self.app.store is self.store) and getattr(self.store,'_view_generation',0)==self.generation and self.store.data_revision()==self.revision

    def render(self,event=None):
        if not self.current():
            self.status.set('도면이 변경되었습니다. 창을 다시 열어 확인하세요.')
            if self.accept_button:self.accept_button.configure(state='disabled')
            return
        index=self.choice.current()
        if index<0:return
        report=self.reports[index];self.report=report
        details=([self.batch_warnings[index]] if index in self.batch_warnings else [])+[report['summary']]
        for meeting in report['meetings']:
            details.append(meeting['name']+' · 1번: '+', '.join(meeting['sides'][0])+' / 2번: '+', '.join(meeting['sides'][1]))
        self.info.configure(state='normal');self.info.delete('1.0','end');self.info.insert('1.0','\n'.join(details));self.info.configure(state='disabled')
        for i,side in enumerate(report['sides']):
            tree=self.tables[i];tree.delete(*tree.get_children());start=self.store.core(*side['start']) or {}
            self.headings[i].set(f"코어번호 {side['start'][1]} · 코어ID {start.get('core_id') or '(빈 ID)'}\n"+self.store._slot_title(*side['start'])+'\n현재 함체 접속: '+(' / '.join(self.store._slot_title(*slot) for slot in side['local']) or '없음'))
            for row in side['rows']:
                tag='overlap' if row['slot'] in report['shared_slots'] else 'cable' if row['slot'][0] in report['shared_cables'] else ''
                tree.insert('','end',values=tuple(row[k] for k in ('from','cable','index','core_id','to','note')),tags=(tag,))
        if self.app:
            namespace=type(self.app).__init__.__globals__;namespace['draw_trace_diagram'](self.diagram,report)
            labels=namespace['core_path_number_labels'](*[[{'cable_id':r['slot'][0],'core_index':r['slot'][1]} for r in side['rows']] for side in report['sides']])
            self.app.start_highlight_blink(report['cable_colors'],owner=self,core_labels=labels)
        self.status.set(f"경로 {index+1}/{len(self.pairs)} · 확인사항 {len(report['issues'])}건 · 도면 연결은 최종 확인 전까지 바뀌지 않습니다.")

    def confirm(self):
        if not self.current():self.render();return
        self.accepted=True;self.destroy()

    def space_confirm(self,event):
        if self.accept_button is not None and not isinstance(event.widget,(ttk.Combobox,tk.Text)):
            self.confirm();return 'break'

    def destroy(self):
        if self._closed:return
        self._closed=True
        if self.app and getattr(self.app,'highlight_owner',None) is self:self.app.stop_highlight_blink(clear=True)
        previous=self._previous_grab;super().destroy()
        try:
            if previous is not None and previous.winfo_exists():previous.grab_set()
        except tk.TclError:pass
