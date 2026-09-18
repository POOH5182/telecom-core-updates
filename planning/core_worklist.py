"""Read-only work classification from field evidence and after topology changes."""


def worklist_clipboard(rows,headings=None):
    """Excel-compatible TSV preserving Unicode, blank cells and multiline names."""
    import csv
    import io
    output=io.StringIO(newline='');writer=csv.writer(output,delimiter='\t',lineterminator='\n')
    if headings is not None:writer.writerow(headings)
    writer.writerows(rows)
    return output.getvalue()


class CoreWorklistCopy:
    """Read-only spreadsheet selection, independent of the single-row name editor."""
    def __init__(self,dialog):
        self.dialog=dialog;self.tree=dialog.tree;self.column='detail';self.notice=tk.StringVar()
        self.mode=tk.StringVar(value='cells');self.anchor=None;self.end=None
        self.selected_rows=();self.selected_columns=();self.native_selection=()
        self.dragging=False;self._scroll_job=None;self._paint_job=None;self._labels=[]
        style=ttk.Style(self.tree)
        style.map('CoreWorklist.Treeview',background=[('selected','#f1f5f9')],foreground=[('selected','#18334f')])
        self.tree.configure(style='CoreWorklist.Treeview')
        self.bar=bar=ttk.Frame(dialog,padding=(8,0,8,4));bar.pack(fill='x',before=dialog.tree.master)
        actions=ttk.Frame(bar);actions.pack(fill='x')
        for text,command in (
          ('선택 범위 복사',self.copy),
          ('코어내역 복사',lambda:self.copy(column='detail')),
          ('코어ID 복사',lambda:self.copy(column='id')),
          ('목록 전체 복사',lambda:self.copy(all_rows=True)),
          ('선번 연결도',lambda:open_core_layout(dialog.parent))):
            ttk.Button(actions,text=text,command=command).pack(side='left',padx=3)
        ttk.Label(actions,textvariable=self.notice).pack(side='right',padx=4)
        selection=ttk.Frame(bar);selection.pack(fill='x',pady=(4,0))
        for title,value in (('셀 범위','cells'),('행 전체','rows'),('열 전체','columns')):
            ttk.Radiobutton(selection,text=title,value=value,variable=self.mode,command=self.change_mode).pack(side='left',padx=3)
        ttk.Label(selection,text='드래그 / Shift+클릭 · Ctrl+C 복사 · 제목 클릭: 정렬',foreground='#1769aa').pack(side='left',padx=8)
        self.menu=tk.Menu(dialog,tearoff=False)
        for text,command in (
          ('선택 범위 복사',self.copy),
          ('코어ID 복사',lambda:self.copy(column='id')),
          ('코어내역 복사',lambda:self.copy(column='detail')),
          ('선택 행 전체 복사',lambda:self.copy(row=True)),
          ('목록 전체 복사',lambda:self.copy(all_rows=True))):
            self.menu.add_command(label=text,command=command)
        # Before the sorting tag: column-selection mode can drag across headings.
        self._tag='WorklistRange:'+str(self.tree)
        self.tree.bindtags((self._tag,)+self.tree.bindtags())
        bindings={'<ButtonPress-1>':self.press,'<B1-Motion>':self.motion,
                  '<Double-Button-1>':self.double_click,
                  '<ButtonRelease-1>':self.release,'<Button-3>':self.context_menu,
                  '<Control-c>':self.copy,'<Control-C>':self.copy,
                  '<Control-a>':self.select_all,'<Control-A>':self.select_all,
                  '<Escape>':self.escape,'<<TreeviewSelect>>':self.native_changed,
                  '<Configure>':self.queue_paint,'<Destroy>':self.destroy}
        for key in ('Left','Right','Up','Down'):
            bindings['<'+key+'>']=self.key_move
            bindings['<Shift-'+key+'>']=self.key_move
        self._sequences=tuple(bindings)
        for sequence,callback in bindings.items():self.tree.bind_class(self._tag,sequence,callback)
        self._before_sort=self.tree.before_sort;self.tree.before_sort=self.before_sort
        for option in ('xscrollcommand','yscrollcommand'):
            original=self.tree.cget(option)
            def scrolled(first,last,original=original):
                if original:self.tree.tk.call(*self.tree.tk.splitlist(original),first,last)
                self.queue_paint()
            self.tree.configure(**{option:scrolled})

    def clear(self):
        self.stop_scroll();self.dragging=False;self.anchor=None;self.end=None
        self.selected_rows=();self.selected_columns=();self.notice.set('')
        for label in self._labels:label.place_forget()

    def before_sort(self):
        self.clear()
        if self._before_sort:self._before_sort()

    def change_mode(self):
        self.clear();self.notice.set('복사할 범위를 드래그하세요.');self.tree.focus_set()

    def escape(self,event=None):
        self.clear();return 'break'

    def native_changed(self,event=None):
        if self.selected_rows and self.tree.selection()!=self.native_selection:self.clear()

    def point(self,x,y,clamp=False):
        columns=tuple(self.tree['columns']);rows=self.tree.get_children()
        if not rows:return None
        column=self.tree.identify_column(x)
        if not column or column=='#0':
            if not clamp:return None
            column='#1' if x<1 else '#'+str(len(columns))
        index=int(column[1:])-1
        if not 0<=index<len(columns):return None
        iid=self.tree.identify_row(y)
        if not iid and clamp:
            # Use the visible edge, never jump from a short drag to the last row.
            step=1 if y<self.body_top() else -1
            start=self.body_top() if step==1 else self.tree.winfo_height()-2
            for yy in range(start,self.tree.winfo_height() if step==1 else 0,step):
                iid=self.tree.identify_row(yy)
                if iid:break
        if not iid and self.mode.get()=='columns':iid=rows[0]
        return (iid,columns[index]) if iid else None

    def body_top(self):
        for y in range(1,min(100,self.tree.winfo_height())):
            if self.tree.identify_row(y):return y
        return 25

    def press(self,event):
        region=self.tree.identify_region(event.x,event.y)
        if region=='separator':return None
        if region=='heading' and self.mode.get()!='columns':return None
        cell=self.point(event.x,event.y)
        if not cell:return None
        self.tree.focus_set();self.column=cell[1]
        if not (event.state & 1 and self.anchor):self.anchor=cell
        self.end=cell;self.dragging=True;self.pointer=(event.x,event.y)
        # Copying another range must not overwrite a pending name or retarget Apply.
        dirty=self.dialog._edit_core is not None and self.dialog.name_var.get()!=self.dialog._name_original
        if not dirty:self.tree.selection_set(self.anchor[0]);self.tree.focus(self.anchor[0])
        self.native_selection=self.tree.selection()
        self.update_range();return 'break'

    def update_range(self):
        rows=self.tree.get_children();columns=tuple(self.tree['columns'])
        if not self.anchor or self.anchor[0] not in rows or self.end[0] not in rows:self.clear();return
        a,b=sorted((rows.index(self.anchor[0]),rows.index(self.end[0])))
        c,d=sorted((columns.index(self.anchor[1]),columns.index(self.end[1])))
        self.selected_rows=rows if self.mode.get()=='columns' else rows[a:b+1]
        self.selected_columns=columns if self.mode.get()=='rows' else columns[c:d+1]
        self.notice.set(f'{len(self.selected_rows)}행 × {len(self.selected_columns)}열 선택')
        self.queue_paint()

    def double_click(self,event):
        if self.mode.get()!='cells':return self.press(event)
        if self.tree.identify_region(event.x,event.y)=='heading':return None
        cell=self.point(event.x,event.y)
        if cell:
            self.clear();self.tree.selection_set(cell[0]);self.tree.focus(cell[0])
            self.dialog.double_click(event)
            return 'break'

    def motion(self,event):
        if not self.dragging:return None
        self.pointer=(event.x,event.y);cell=self.point(event.x,event.y,clamp=True)
        if cell:self.end=cell;self.update_range()
        self.stop_scroll();self._scroll_job=self.tree.after(80,self.auto_scroll)
        return 'break'

    def auto_scroll(self):
        self._scroll_job=None
        if not self.dragging:return
        x,y=self.pointer;dx=-1 if x<4 else 1 if x>=self.tree.winfo_width()-4 else 0
        dy=-1 if y<self.body_top() else 1 if y>=self.tree.winfo_height()-4 else 0
        if self.mode.get()=='columns':dy=0
        if dx:self.tree.xview_scroll(dx,'units')
        if dy:self.tree.yview_scroll(dy,'units')
        if dx or dy:
            cell=self.point(max(2,min(x,self.tree.winfo_width()-3)),max(self.body_top(),min(y,self.tree.winfo_height()-3)),clamp=True)
            if cell:self.end=cell;self.update_range()
            self._scroll_job=self.tree.after(80,self.auto_scroll)

    def stop_scroll(self):
        if self._scroll_job is not None:self.tree.after_cancel(self._scroll_job);self._scroll_job=None

    def release(self,event):
        if not self.dragging:return None
        cell=self.point(event.x,event.y,clamp=True)
        if cell:self.end=cell;self.update_range()
        self.dragging=False;self.stop_scroll();return 'break'

    def key_move(self,event):
        rows=self.tree.get_children();columns=tuple(self.tree['columns'])
        if not rows:return 'break'
        cell=self.end if self.end and self.end[0] in rows else (self.tree.focus() or rows[0],self.column)
        if cell[0] not in rows:cell=(rows[0],self.column)
        r=rows.index(cell[0]);c=columns.index(cell[1])
        r=max(0,min(len(rows)-1,r+({'Up':-1,'Down':1}.get(event.keysym,0))))
        c=max(0,min(len(columns)-1,c+({'Left':-1,'Right':1}.get(event.keysym,0))))
        self.end=(rows[r],columns[c]);self.column=columns[c]
        if not (event.state & 1 and self.anchor):self.anchor=self.end
        self.native_selection=self.tree.selection();self.tree.see(rows[r]);self.update_range();return 'break'

    def select_all(self,event=None):
        rows=self.tree.get_children();columns=tuple(self.tree['columns'])
        if rows:
            self.mode.set('cells');self.anchor=(rows[0],columns[0]);self.end=(rows[-1],columns[-1])
            self.native_selection=self.tree.selection();self.update_range()
        return 'break'

    def queue_paint(self,event=None):
        if self._paint_job is None:self._paint_job=self.tree.after_idle(self.paint)

    def forward(self,event,sequence):
        # Highlight labels stay mouse-transparent by forwarding to the real table.
        self.tree.event_generate(sequence,x=event.x+event.widget.winfo_x(),y=event.y+event.widget.winfo_y(),
                                 state=event.state,time=event.time,**({'delta':event.delta} if sequence=='<MouseWheel>' else {}))
        return 'break'

    def paint(self):
        self._paint_job=None
        for label in self._labels:label.place_forget()
        if not self.selected_rows:return
        selected=set(self.selected_rows);y=self.body_top();used=0;seen=set()
        style=ttk.Style(self.tree);font=style.lookup(self.tree.cget('style') or 'Treeview','font') or 'TkDefaultFont'
        while y<self.tree.winfo_height():
            iid=self.tree.identify_row(y)
            if not iid:y+=1;continue
            box=self.tree.bbox(iid)
            if not box:y+=1;continue
            if iid in seen:y+=1;continue
            seen.add(iid);y=box[1]+box[3]
            if iid not in selected:continue
            for column in self.selected_columns:
                x,yy,w,h=self.tree.bbox(iid,column)
                if x+w<=0 or x>=self.tree.winfo_width():continue
                if used==len(self._labels):
                    label=tk.Label(self.tree,anchor='w',background='#dbeafe',foreground='#143d70',
                                   highlightbackground='#7fa9df',highlightthickness=1,borderwidth=0,padx=4,takefocus=False)
                    for sequence in ('<ButtonPress-1>','<B1-Motion>','<ButtonRelease-1>','<Button-3>','<MouseWheel>'):
                        label.bind(sequence,lambda e,s=sequence:self.forward(e,s))
                    self._labels.append(label)
                label=self._labels[used];used+=1
                label.configure(text=self.tree.set(iid,column).replace('\r',' ').replace('\n',' '),font=font)
                label.place(x=x,y=yy,width=w,height=h)

    def context_menu(self,event):
        cell=self.point(event.x,event.y)
        if not cell:return 'break'
        self.column=cell[1]
        if cell[0] not in self.selected_rows or cell[1] not in self.selected_columns:
            self.anchor=self.end=cell;self.native_selection=self.tree.selection();self.update_range()
        previous=self.dialog.grab_current()
        try:self.menu.tk_popup(event.x_root,event.y_root)
        finally:
            self.menu.grab_release()
            if previous is not None and previous.winfo_exists():previous.grab_set()
        return 'break'

    def copy(self,event=None,column=None,row=False,all_rows=False):
        self.native_changed()
        visible=self.tree.get_children();columns=tuple(self.tree['columns'])
        wanted=set(self.selected_rows or self.tree.selection())
        selected=visible if all_rows else tuple(i for i in visible if i in wanted)
        if not selected:self.notice.set('복사할 항목을 선택하세요.');return 'break'
        chosen=columns if all_rows or row else (column,) if column else self.selected_columns or (self.column,)
        values=[[self.tree.set(i,c) for c in chosen] for i in selected]
        if len(selected)==len(chosen)==1 and not all_rows and not row:text=worklist_clipboard(values).removesuffix('\n')
        else:text=worklist_clipboard(values,[self.tree.heading_text(c) for c in chosen] if all_rows else None)
        self.dialog.clipboard_clear();self.dialog.clipboard_append(text)
        self.notice.set(f'{len(selected)}행 × {len(chosen)}열 복사 완료');return 'break'

    def destroy(self,event=None):
        if event is not None and event.widget is not self.tree:return
        self.stop_scroll()
        if self._paint_job is not None:self.tree.after_cancel(self._paint_job);self._paint_job=None
        for sequence in self._sequences:self.tree.unbind_class(self._tag,sequence)

def work_list_items(app,items):
    """Real IDs and physical field-end ON obligations only; no saved writes."""
    result={}
    for key,item in items.items():
        cid=str(item.get('core_id') or '').strip()
        if not cid:continue
        if item.get('field_endpoints'):
            result[key]=item
            continue
        if cid.startswith('임시-'):
            # Temporary obligations are built from physical field endpoints
            # below, never resurrected by an old token or an interior ON.
            continue
        result[key]=item
    return result


def work_source_method(source,changed=False):
    states=set(source.get('source_states') or ())
    if states & {'절단','cut'}:return '절단절체'
    if changed or states & {'철거','remove'} or source.get('source_facilities'):return '코어절체'
    return source.get('method','')


WORK_MISSING_STATUS_KEY='missing_work_status_v110'
WORK_HANDLED_STATUS={'exception':'예외 처리','cancel':'해지','broken':'끊김'}


def work_status_codes(rows=(),labels=()):
    values=set(labels)
    for row in rows:values.update(statuses(row))
    aliases={'예외':'exception','예외처리':'exception','예외코어':'exception','해지':'cancel','해지코어':'cancel',
             '끊김':'broken','끊킴':'broken','끊김코어':'broken','끊킴코어':'broken'}
    codes={aliases.get(''.join(str(v).split()),STATUS_CODES.get(v,v)) for v in values}
    return [code for code in WORK_HANDLED_STATUS if code in codes]


def work_removed_status_history(store,group_id=None,exclude_groups=()):
    """Recover the most recent identity-removal snapshot on the active undo branch.

    A later reintroduction invalidates old removal evidence. Empty statuses are
    retained too, so clearing a state cannot revive an older field disposition.
    Signal exception and cancel_expected never become a handled disposition.
    """
    sql="""SELECT e.*,g.created_at FROM history_events e JOIN history_groups g ON g.id=e.group_id
        WHERE g.undone=0 AND e.table_name IN ('cores','ports','core_annotations')"""
    args=()
    if group_id:sql+=' AND e.group_id=?';args=(group_id,)
    if exclude_groups:
        sql+=' AND e.group_id NOT IN (SELECT value FROM json_each(?))';args+= (json.dumps(sorted(exclude_groups)),)
    sql+=' ORDER BY e.seq'
    removed={};seen={};annotations={}
    for event in store.conn.execute(sql,args):
        old=json.loads(event['old_json']) if event['old_json'] else {}
        new=json.loads(event['new_json']) if event['new_json'] else {}
        cid=str(old.get('core_id') or '').strip();new_id=str(new.get('core_id') or '').strip()
        if event['table_name']=='core_annotations':
            if cid and (not new or new_id!=cid):annotations[(event['group_id'],cid)]=json.loads(old.get('labels') or '[]')
            continue
        if new_id:seen[new_id]=event['seq']
        if not cid or cid==new_id:continue
        record=removed.get(cid)
        if not record or record['group_id']!=event['group_id']:
            record=dict(core_id=cid,source_kind='after',group_id=event['group_id'],rows=[],slots=[],order=event['seq'],time=event['created_at'])
            removed[cid]=record
        slot=(old['cable_id'],int(old['core_index'])) if event['table_name']=='cores' else ('PORT:'+old['node_id'],int(old['port_index']))
        record['rows'].append(old);record['slots'].append(list(slot));record['order']=event['seq']
    for cid,record in list(removed.items()):
        if seen.get(cid,0)>record['order']:del removed[cid];continue
        record['codes']=work_status_codes(record.pop('rows'),annotations.get((record['group_id'],cid),()))
    return removed


def work_removed_status_ledger(store):
    row=store.conn.execute('SELECT value FROM workflow_state WHERE key=?',(WORK_MISSING_STATUS_KEY,)).fetchone()
    return json.loads(row[0]) if row else {}


def preserve_removed_work_status(store):
    """Join the caller's existing transaction/history group; never write on read."""
    if completion_kind(store)!='after' or not store._history_group:return
    removed=work_removed_status_history(store,store._history_group)
    if not removed:return
    present={r[0] for r in store.conn.execute("SELECT core_id FROM cores WHERE core_id<>'' UNION SELECT core_id FROM ports WHERE core_id<>''")}
    removed={cid:row for cid,row in removed.items() if cid not in present}
    if not removed:return
    saved=work_removed_status_ledger(store);saved.update(removed)
    store.conn.execute('INSERT INTO workflow_state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
        (WORK_MISSING_STATUS_KEY,json.dumps(saved,ensure_ascii=False)))


def work_missing_status_context(app,net):
    store=app.store;stamp=(store.data_revision(),store.conn.total_changes,getattr(store,'_view_generation',0),getattr(app,'_transfer_source_stamp',None))
    if getattr(store,'_missing_status_stamp',None)!=stamp:
        ledger=work_removed_status_ledger(store)
        # Old drawings can still provide their last deletion's saved row even
        # before V110. Never use undone events or the old accepted work list.
        history=work_removed_status_history(store,exclude_groups=getattr(app,'_work_field_history_groups',()))
        store._missing_status_value=(ledger,history);store._missing_status_stamp=stamp
    ledger,history=store._missing_status_value
    return dict(net=net,ledger=ledger,history=history,field=getattr(app,'_work_field_status',{}))


def work_missing_status(item,context):
    net=context['net'];cid=item['core_id'];evidence=None
    current=net.by_id.get(cid,set())
    if current or cid in net.annotations:
        evidence=dict(codes=work_status_codes([net.slots[s] for s in current],json.loads(net.annotations.get(cid,{}).get('labels','[]'))),origin='후도면 현재 상태')
    else:
        endpoints={tuple(a['slot']) for a in item.get('field_endpoints',())}
        for source,label in ((context['history'],'후도면 삭제 직전 기록'),(context['ledger'],'후도면 삭제 시 보존한 상태')):
            matches=[r for key,r in source.items() if r.get('source_kind')=='after' and
                ((not endpoints and key==cid) or (endpoints and endpoints & {tuple(s) for s in r.get('slots',())}))]
            if matches:
                latest=max(matches,key=lambda r:r.get('order',0))
                if evidence is None or latest.get('order',0)>=evidence.get('order',0):
                    evidence=dict(codes=latest['codes'],origin=label,order=latest.get('order',0))
        if evidence is None:
            if endpoints:codes=item.get('field_status_codes',[])
            else:codes=context['field'].get(cid,[])
            evidence=dict(codes=codes,origin='현장반영 도면 상태')
    codes=work_status_codes(labels=evidence['codes'])
    if not codes:return None
    result=WORK_HANDLED_STATUS[codes[0]];labels=' · '.join(WORK_HANDLED_STATUS[c] for c in codes)
    return dict(result=result,reason=labels,complete='exception' in codes,excluded='exception' not in codes,
        missing=False,error=False,handled_missing=True,physical_complete=False,
        note=labels+' 처리 · 후도면 배정 없음 · 근거: '+evidence['origin'])


def handled_missing_work(app):
    report=app.work_report() if callable(getattr(app,'work_report',None)) else Workflow(app).report()
    return {row['core_id']:row for row in report['rows'] if row.get('handled_missing')}


def work_physical_components(net):
    result={};remaining=set(net.slots)
    for root in sorted(net.slots):
        if root not in remaining:continue
        members=set();stack=[root]
        while stack:
            slot=stack.pop()
            if slot in members:continue
            members.add(slot);remaining.discard(slot)
            stack.extend(peer for _,peer in net.links.get(slot,()) if peer not in members)
        for slot in members:result[slot]=members
    return result


def work_physical_edges(net,members):
    return sorted({(nid,*sorted((slot,peer))) for slot in members for nid,peer in net.links.get(slot,()) if peer in members})


def field_temporary_work(net):
    """One field obligation per physical temporary path, using end-cable ON.

    IDs are labels. Internal temporary tokens and same-ID disconnected rows
    neither supply endpoint signal nor merge different physical services.
    """
    components=work_physical_components(net);seen=set();items={}
    for slot,members in sorted(components.items()):
        if slot in seen:continue
        seen.update(members)
        ids={str(net.slots[s].get('core_id') or '').strip() for s in members}-{''}
        if not ids or any(not cid.startswith('임시-') for cid in ids):continue
        anchors=[];ends=[];end_names=[]
        for position in sorted(members):
            cable=net.cables.get(position[0])
            if not cable:continue
            for nid in (cable['n1id'],cable['n2id']):
                node=net.nodes.get(nid,{});peers=[p for n,p in net.links.get(position,()) if n==nid]
                terminal=cable_terminal(node,net.degree[nid]) and not peers
                ports=[p for p in peers if p[0]=='PORT:'+nid and port_endpoint_kind(node)]
                rn_end=bool(port_endpoint_kind(node)) and (bool(ports) or not peers)
                if not terminal and not rn_end:continue
                endpoint=['terminal',nid,''] if terminal else [port_endpoint_kind(node),nid,str(net.slots[ports[0]].get('label','')).upper() if ports else '']
                row=net.slots[position]
                anchors.append(dict(slot=list(position),node=nid,ends=sorted((cable['n1id'],cable['n2id'])),
                    core_id=str(row.get('core_id') or ''),signal=core_signal_code(row.get('signal')),endpoint=endpoint,
                    location=net.title(position)))
                ends.append(endpoint);end_names.append(node.get('name',nid))
        if not any(a['signal']=='on' for a in anchors):continue
        cables={s[0] for s in members if s[0] in net.cables}
        states={net.cables[c]['status'] for c in cables}
        facilities={n for c in cables for n in (net.cables[c]['n1id'],net.cables[c]['n2id'])}
        removed={net.nodes[n]['name'] for n in facilities if net.nodes[n]['type'] in ('hamche','rn') and net.nodes[n]['status'] in ('철거','remove')}
        key='field-end:'+digest([(a['slot'],a['node']) for a in anchors])
        row=dict(work_key=key,core_id=next((a['core_id'] for a in anchors if a['signal']=='on' and a['core_id']),sorted(ids)[0]),
            source_core_ids=sorted(ids),field_endpoints=anchors,source_keys=[key],signal='on',
            detail=next((net.slots[s].get('detail') for s in sorted(members) if net.slots[s].get('detail')),''),
            source_slots=sorted(members),source_cables=sorted(cables),source_states=sorted(states),source_facilities=sorted(removed),
            source_edges=work_physical_edges(net,members),
            source_routes=[net.title(s) for s in sorted(members)],ends=sorted(ends),end_names=sorted(end_names),input_missing=False)
        row['method']=work_source_method(row);row['signature']=digest([row,[(s,net.slots[s]) for s in sorted(members)]])
        row['field_status_codes']=work_status_codes([net.slots[s] for s in members],
            [label for cid in ids for label in json.loads(net.annotations.get(cid,{}).get('labels','[]'))])
        items[key]=row
    return items


def field_work_capture(net,items):
    items={k:v for k,v in items.items() if not str(v.get('core_id') or '').startswith('임시-')}
    items.update({k:v for k,v in field_temporary_work(net).items() if v['method']})
    return items


def work_match_field_ends(net,item,components=None):
    """Resolve preserved physical endpoint slots; never guess by cable alone."""
    components=components if components is not None else work_physical_components(net)
    members=set();matched=[];unresolved=[]
    for anchor in item['field_endpoints']:
        original=tuple(anchor['slot']);cable=net.cables.get(original[0]);position=None
        if cable and sorted((cable['n1id'],cable['n2id']))==anchor['ends']:
            current=net.slots.get(original,{})
            # An ID-preserving number move is identifiable only when unique
            # on this same end cable. Renamed temporary IDs use the saved slot.
            same=[s for s in net.by_id.get(anchor['core_id'],()) if s[0]==original[0]]
            if str(current.get('core_id') or '').strip():position=original
            elif len(same)==1:position=same[0]
        if position is None:unresolved.append(anchor['location']);continue
        matched.append(position);members.update(components.get(position,{position}))
    return dict(members=members,matched=matched,unresolved=unresolved)


def field_work_route(net,item,options):
    members={tuple(s) for s in item.get('current_slots',())}
    if not members:
        return dict(complete=False,present=False,error=False,ends=[],end_names=[],route='',signature='',notes=['현장 끝단 케이블의 후도면 배정 위치를 찾지 못함'])
    ids={str(net.slots[s].get('core_id') or '').strip() for s in members}-{''}
    real={cid for cid in ids if not cid.startswith('임시-')}
    cid=item['core_id'];view=copy.copy(net);view.by_id={**net.by_id,cid:members}
    # Inspect physical membership rather than labels. The original saved rows
    # stay intact, and conflicting real identities are checked below.
    route=view.inspect(cid,{**options,'reject_temporary':False,'check_details':False,'reject_removed':False})
    notes=list(route['notes'])
    if len(real)>1:notes.append('서로 다른 실제 코어ID가 연결됨: '+' / '.join(sorted(real)))
    if any(STATUS_CODES.get(label,label)=='error' for value in ids for label in json.loads(net.annotations.get(value,{}).get('labels','[]'))):
        notes.append('현재 연결 경로에 오류 상태 표시가 있음')
    signals={core_signal_code(net.slots[s].get('signal')) for s in members}-{'unknown'}
    if len(signals)>1:notes.append('현재 연결 경로 신호 불일치: '+' / '.join(sorted(signals)))
    if item.get('unresolved_endpoints'):notes.append('현장 끝단 대응 확인 필요: '+' / '.join(item['unresolved_endpoints']))
    if item.get('endpoint_collision'):notes.append('서로 다른 현장 끝단 선번이 같은 후도면 선번에 대응됨: 선번 확인 필요')
    # Field can have disconnected halves. All observed field endpoints must
    # survive; a newly joined opposite end is allowed for a single-ended half.
    expected={tuple(a['endpoint']) for a in item['field_endpoints']}
    actual={tuple(e) for e in route['ends']}
    if any(not any(e[:2]==a[:2] and (not e[2] or e[2]==a[2]) for a in actual) for e in expected):
        notes.append('현장 끝단 케이블의 끝점 또는 RN 내부포트가 유지되지 않음')
    route.update(notes=list(dict.fromkeys(notes)),complete=not notes,error=route['error'] or len(real)>1 or len(signals)>1)
    return route


def project_field_temporary(net,basis):
    """Match and coalesce field halves only through actual after connections."""
    components=work_physical_components(net);groups={};aliases={}
    for key,source in basis.items():
        row=copy.deepcopy(source);match=work_match_field_ends(net,row,components)
        members=match['members'];ids={str(net.slots[s].get('core_id') or '').strip() for s in members}-{''}
        real=sorted(cid for cid in ids if not cid.startswith('임시-'))
        current_id=real[0] if len(real)==1 else sorted(ids)[0] if ids else source['core_id']
        row.update(core_id=current_id,current_slots=sorted(members),unresolved_endpoints=match['unresolved'],matched_endpoints=match['matched'])
        row['work_basis']='현장 끝단 신호 ON 기준 · 현장 ID: '+' / '.join(source['source_core_ids'])+' → 후도면 ID: '+(current_id if members else '배정 확인 필요')
        marker=tuple(sorted(members)) if members and not match['unresolved'] else ('unresolved',key)
        if marker not in groups:groups[marker]=row
        else:
            target=groups[marker]
            # Two different numbers on the same field end cable are separate
            # obligations even when the after drawing accidentally merges them.
            existing={(a['slot'][0],a['node']):tuple(a['slot']) for a in target['field_endpoints']}
            target['endpoint_collision']=target.get('endpoint_collision',False) or any((a['slot'][0],a['node']) in existing and existing[(a['slot'][0],a['node'])]!=tuple(a['slot']) for a in row['field_endpoints'])
            for field in ('source_core_ids','source_keys','field_endpoints','source_slots','source_cables','source_states','source_facilities','source_routes','source_edges','ends','end_names','field_status_codes'):
                target[field]=list({json.dumps(v,ensure_ascii=False,sort_keys=True):v for v in target[field]+row[field]}.values())
            target['work_key']='field-ends:'+digest(sorted(target['source_keys']))
            target['signature']=digest([basis[k]['signature'] for k in sorted(target['source_keys'])])
            target['method']=work_source_method(target)
            target['work_basis']='현장 끝단 신호 ON 기준 · 현장 ID: '+' / '.join(target['source_core_ids'])+' → 후도면 ID: '+current_id
        for old in source['source_core_ids']:
            aliases.setdefault(old,set()).add(current_id if members and not match['unresolved'] else old)
    return {row['work_key']:row for row in groups.values()},aliases


def field_work_record(net,item,before=False):
    members=item['source_slots'] if before else item['current_slots']
    if not members:return None
    route=field_work_route(net,{**item,'current_slots':members,'unresolved_endpoints':[] if before else item.get('unresolved_endpoints',[])},DEFAULTS)
    return dict(slots=list(map(tuple,members)),cables=sorted({s[0] for s in members}),
        numbers=[plan_number_label(net,tuple(s)) for s in members],detail=item['detail'],
        ends=route['ends'],end_names=route['end_names'],result=route,
        signature=digest([route['signature'],item['signature']]))


def work_route_index(net):
    """Canonical physical footprints, ignoring names, signals and edge direction.

    Neutral transit slots in a one-real-ID component already belong to that
    physical path. Filling their IDs during field handoff is not a transfer.
    Conflicting real identities never borrow each other's slots.
    """
    real=lambda cid:bool(cid) and not cid.startswith('임시-')
    members={cid:set(slots) for cid,slots in net.by_id.items() if real(cid)}
    unseen=set(net.slots)
    while unseen:
        stack=[next(iter(unseen))];component=set()
        while stack:
            slot=stack.pop()
            if slot in component:continue
            component.add(slot);unseen.discard(slot)
            stack.extend(peer for _,peer in net.links.get(slot,()) if peer not in component)
        ids={str(net.slots[s].get('core_id') or '').strip() for s in component}
        ids={cid for cid in ids if real(cid)}
        if len(ids)==1:members[next(iter(ids))].update(component)
    edges=defaultdict(set)
    for sp in net.splices:
        a=(sp['cable1_id'],int(sp['core1_index']));b=(sp['cable2_id'],int(sp['core2_index']))
        edge=(sp['node_id'],*sorted((a,b)))
        edges[a].add(edge);edges[b].add(edge)
    result={}
    for cid,slots in members.items():
        cables={s[0] for s in slots if s[0] in net.cables}
        states={net.cables[c]['status'] for c in cables}
        facilities={nid for c in cables for nid in (net.cables[c]['n1id'],net.cables[c]['n2id'])}
        facilities.update(s[0][5:] for s in slots if s[0].startswith('PORT:'))
        removed={net.nodes[nid]['name'] for nid in facilities if nid in net.nodes
                 and net.nodes[nid]['type'] in ('hamche','rn') and net.nodes[nid]['status'] in ('철거','remove')}
        own=[net.slots[s] for s in sorted(slots) if str(net.slots[s].get('core_id') or '').strip()==cid]
        result[cid]=dict(core_id=cid,slots=slots,edges=set().union(*(edges[s] for s in slots)),
            attachments={(c,*sorted((net.cables[c]['n1id'],net.cables[c]['n2id']))) for c in cables},
            source_slots=sorted(slots),source_cables=sorted(cables),source_states=sorted(states),
            source_facilities=sorted(removed),source_routes=[net.title(s) for s in sorted(slots)],
            detail=next((r.get('detail') for r in own if r.get('detail')),''),
            signal=next((r.get('signal') for r in own if r.get('signal')),''))
    return result


def work_transfer_changes(before,after):
    notes=[]
    old_numbers=defaultdict(set);new_numbers=defaultdict(set)
    for owner,index in before['slots']:old_numbers[owner].add(index)
    for owner,index in after['slots']:new_numbers[owner].add(index)
    for owner in sorted(old_numbers.keys() & new_numbers.keys()):
        if old_numbers[owner]!=new_numbers[owner]:
            kind='RN 내부포트 변경' if owner.startswith('PORT:') else '코어번호 변경'
            if kind not in notes:notes.append(kind)
    if old_numbers.keys()!=new_numbers.keys():notes.append('케이블·포트 경로 변경')
    # Compare attachments only on retained cables: replacing an owner is already
    # a route change, while dragging/renaming a symbol is not a topology change.
    old_ends={r[0]:r[1:] for r in before['attachments']}
    new_ends={r[0]:r[1:] for r in after['attachments']}
    if any(old_ends[c]!=new_ends[c] for c in old_ends.keys() & new_ends.keys()):notes.append('케이블 접속시설 변경')
    if before['edges']!=after['edges']:notes.append('접속 상대 변경')
    return notes


def work_transfer_sources(app,items):
    """Retain field work types; add real per-core moves on existing cables.

    This is a projection, not saved work decisions or a new completion policy.
    Source signatures stay stable until the field basis changes, so existing
    exclusions/endpoint approvals retain their normal staleness protections.
    """
    if app.scenario_kind()!='after':return items
    path=app.scenario_path('before')
    if not path.exists():return items
    stamp=(str(path.resolve()),path.stat().st_mtime_ns,path.stat().st_size)
    if getattr(app,'_transfer_source_stamp',None)!=stamp:
        conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True);conn.row_factory=sqlite3.Row
        try:
            basis_net=Network(conn);basis=work_route_index(basis_net)
            app._field_temporary_basis=field_temporary_work(basis_net)
            app._work_field_history_groups={r[0] for r in conn.execute('SELECT id FROM history_groups')}
            app._work_field_status={cid:work_status_codes([basis_net.slots[s] for s in slots],json.loads(basis_net.annotations.get(cid,{}).get('labels','[]')))
                                    for cid,slots in basis_net.by_id.items()}
            for cid,row in basis.items():
                original=basis_net.by_id[cid]
                try:
                    basis_net.by_id[cid]=row['slots']
                    route=basis_net.inspect(cid,{**DEFAULTS,'reject_removed':False,'reject_temporary':False,'check_details':False})
                finally:basis_net.by_id[cid]=original
                row.update(ends=route['ends'],end_names=route['end_names'])
                row['signature']=digest(serial(row))
            app._transfer_source_index=basis;app._transfer_source_stamp=stamp
        finally:conn.close()
    basis=app._transfer_source_index
    current_net=Network(app.store.conn)
    current=work_route_index(current_net)
    items=copy.deepcopy(items)
    for cid,old in basis.items():
        changed=work_transfer_changes(old,current.get(cid,dict(slots=set(),edges=set(),attachments=set())))
        if cid not in items and not changed:continue
        if cid not in items:
            row={k:copy.deepcopy(v) for k,v in old.items() if k not in ('slots','edges','attachments')}
            row.update(input_missing=False,derived_transfer=True)
            items[cid]=row
        row=items[cid]
        # Field cut always wins, including a route that also has removed cables
        # or a later number move. After cable status never replaces this basis.
        row['method']=work_source_method(old,bool(changed)) or row.get('method','')
        row['work_basis']='현장반영 대비 '+ ' · '.join(changed) if changed else '현장반영 작업대상 유지'
        if changed:row['work_basis']+=' · 현장반영: '+' → '.join(old['source_routes'])
    temporary,_=project_field_temporary(current_net,app._field_temporary_basis)
    items={k:v for k,v in items.items() if not v.get('field_endpoints') and not str(v.get('core_id') or '').startswith('임시-')}
    for key,row in temporary.items():
        members=set(map(tuple,row['current_slots']))
        changed=set(map(tuple,row['source_slots']))!=members or serial(row['source_edges'])!=serial(work_physical_edges(current_net,members))
        if not row['method'] and not changed:continue
        row['method']=work_source_method(row,changed)
        # Inspection follows stored physical connections, as mandatory after
        # completion does; cut/removal paint is work evidence, not a break.
        row['field_route']=field_work_route(current_net,row,state(app.store)['options'])
        items[key]=row
    context=work_missing_status_context(app,current_net)
    for row in items.values():row['missing_status']=work_missing_status(row,context)
    return items
