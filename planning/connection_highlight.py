"""Physical segment colors, shared-cable highlights and local open-end hints.

Same-ID components are context only. A hint never adds a splice or chooses an
ambiguous pair. OFF and valid terminal ends never request an allocation.
"""

OVERLAP_COLOR='#e600a9'
SEGMENT_COLORS=('#ff7a00','#7c3aed','#00897b','#1565c0','#b45379','#657c16','#006b88','#795548')


def core_segment_color(index):
    if index<len(SEGMENT_COLORS):return SEGMENT_COLORS[index]
    import colorsys
    rgb=colorsys.hsv_to_rgb(((index-len(SEGMENT_COLORS))*.61803398875+.07)%1,.76,.67)
    return '#'+''.join(f'{round(c*255):02x}' for c in rgb)


def _route_id_text(value):
    value=str(value or '').strip()
    return ('임시코어'+value[3:]) if value.startswith('임시-') and value[3:].isdigit() else value


ROUTE_SIGNAL_TEXT={'on':'신호 있음 (ON)','off':'신호 없음 (OFF)','unknown':'신호 미입력','exception':'신호 예외','error':'신호 오류'}
ROUTE_SIGNAL_SHORT={'on':'ON','off':'OFF','unknown':'미입력','exception':'예외','error':'오류'}
ROUTE_SIGNAL_COLORS={'on':'#15803d','off':'#475569','unknown':'#b45309','exception':'#6a1b9a','error':'#c62828','mixed':'#c62828'}


def route_signal_state(rows,slots):
    """Saved signal of one traced segment: ON, OFF, 미입력 (blank/확인필요) or mixed. Read-only.

    미입력 is neutral: ON 1 + 미입력 7 is ON. Only different entered signals (ON and OFF) are mixed.
    """
    counts=defaultdict(int)
    for slot in slots:
        row=rows.get(slot)
        if row is None:continue
        code=core_signal_code(dict(row).get('signal'))
        counts[code if code in ROUTE_SIGNAL_TEXT else 'unknown']+=1
    known=[c for c in counts if c!='unknown']
    if not known:return 'unknown',ROUTE_SIGNAL_TEXT['unknown']
    if len(known)==1:
        return known[0],ROUTE_SIGNAL_TEXT[known[0]]
    # V166: the 미입력 count is not shown (user request); only entered signals are counted.
    order=('on','off','exception','error')
    return 'mixed','신호 섞임: '+' · '.join(f'{ROUTE_SIGNAL_SHORT[c]} {counts[c]}' for c in order if counts.get(c))


def route_cable_signals(rows,slots,cables):
    """Per-cable signal code of one traced segment (cables only, ports stay in the legend)."""
    found=defaultdict(set)
    for slot in slots:
        if slot[0] not in cables:continue
        code=core_signal_code(dict(rows.get(slot) or {}).get('signal'))
        found[slot[0]].add(code if code in ROUTE_SIGNAL_TEXT else 'unknown')
    return {cable:next(iter(codes)) for cable,codes in found.items() if len(codes)==1}


ROUTE_SIGNAL_FILLS={'on':'#dcfce7','off':'#e2e8f0','unknown':'#fef3c7','exception':'#f3e8ff','error':'#fee2e2'}


def route_cable_signal_fills(model):
    """Label background per cable on a 섞임 path; one signal per cable only."""
    marks=defaultdict(set)
    for row in (model or {}).get('legend') or ():
        for cable,code in (row.get('cable_signals') or {}).items():marks[cable].add(code)
    return {cable:ROUTE_SIGNAL_FILLS[next(iter(codes))] for cable,codes in marks.items() if len(codes)==1}


def compact_route_display(groups,rows,cables,overlaps,overlap_color=OVERLAP_COLOR,nodes=None):
    """Cable text is only the core number; IDs, cables and segment colors go to a legend."""
    numbers=defaultdict(list);legend=[];ports=defaultdict(list);nodes=nodes or {}
    def cable_name(cable_id):
        cable=cables.get(cable_id) or {}
        return str(cable.get('cable_id') or cable.get('spec') or cable_id)
    for group in groups:
        ids=[_route_id_text(i) for i in group.get('ids') or ()]
        if not ids:ids=list(dict.fromkeys(_route_id_text(rows.get(s,{}).get('core_id')) for s in group['slots'] if str(rows.get(s,{}).get('core_id') or '').strip()))
        parts=[]
        for slot in group['slots']:
            if slot[0] in cables:
                numbers[slot[0]].append(int(slot[1]));parts.append(f'{cable_name(slot[0])} {slot[1]}번')
            elif slot[0].startswith('PORT:'):
                # RN internal assignment is shown at the RN itself and in the legend.
                nid=slot[0][5:];port=str(rows.get(slot,{}).get('label') or slot[1])
                parts.append(str((nodes.get(nid) or {}).get('name') or 'RN')+' '+port)
                ports[nid].append(dict(port=port,color=group['color'],number=group['number']))
        names=list(dict.fromkeys(str(rows.get(x,{}).get('detail') or '').strip() for x in group['slots'] if str(rows.get(x,{}).get('detail') or '').strip()))
        signal,signal_text=route_signal_state(rows,group['slots'])
        legend.append(dict(kind='segment',number=group['number'],color=group['color'],ids=tuple(ids),name_text=' / '.join(names),
            core_text=' / '.join(ids) or 'ID 없음',cable_text=', '.join(dict.fromkeys(parts)),
            fault=' · '.join(group.get('faults') or ()),signal=signal,signal_text=signal_text,signal_color=ROUTE_SIGNAL_COLORS[signal],
            cable_signals=route_cable_signals(rows,group['slots'],cables) if signal=='mixed' else {}))
    short={cable:'·'.join(str(n) for n in sorted(set(values)))+'번' for cable,values in numbers.items()}
    # V166: on a 섞임 path every cable says which signal it carries (1번 ON / 1번 OFF).
    marks=defaultdict(set)
    for row in legend:
        for cable,code in row.get('cable_signals',{}).items():marks[cable].add(code)
    for cable,codes in marks.items():
        if cable in short and len(codes)==1 and codes!={'unknown'}:short[cable]+=' '+ROUTE_SIGNAL_SHORT[next(iter(codes))]
    shared=sorted(overlaps,key=cable_name)
    if shared:legend.append(dict(kind='overlap',number=0,color=overlap_color,ids=(),core_text='겹침',name_text='같은 케이블에 여러 코어',
        cable_text='같은 케이블에 여러 코어: '+', '.join(cable_name(c) for c in shared),fault=''))
    port_labels={nid:dict(text=str((nodes.get(nid) or {}).get('name') or 'RN')+' · '+' / '.join(dict.fromkeys(i['port'] for i in items)),
                          color=items[0]['color'],ports=tuple(dict.fromkeys(i['port'] for i in items))) for nid,items in ports.items()}
    return short,legend,port_labels


def overlap_junctions(net,rows,slots,overlaps,color=OVERLAP_COLOR):
    """Where a cable carries several traced cores, say which core continues where.

    Read-only: each saved splice at an end enclosure of a shared cable becomes
    one line "far end쪽 11번 → far end쪽 5번". Unconnected ends stay boundaries.
    """
    members=set(slots);overlaps=set(overlaps);nodes=net.nodes or {}
    def name(nid):return str((nodes.get(nid) or {}).get('name') or nid)
    def far(cable,nid):return cable.get('n2id') if cable.get('n1id')==nid else cable.get('n1id')
    def side(slot,nid):
        if slot[0].startswith('PORT:'):return name(slot[0][5:])+' RN 포트 '+str(rows.get(slot,{}).get('label') or slot[1])
        cable=net.cables.get(slot[0]) or {};end=far(cable,nid)
        # Parallel cables to the same enclosure also need the cable name.
        parallel=sum(1 for c in net.cables.values() if nid in (c.get('n1id'),c.get('n2id')) and far(c,nid)==end)>1
        owner=' '+str(cable.get('cable_id') or cable.get('spec') or slot[0]) if parallel else ''
        return f'{name(end)}쪽{owner} {slot[1]}번'
    found=defaultdict(dict)
    for slot in sorted(members):
        if slot[0] not in overlaps:continue
        for nid,peer in net.links.get(slot,()):
            if peer not in members:continue
            # Read from the shared cable; when both sides are shared keep one order.
            a,b=side(slot,nid),side(peer,nid)
            if peer[0] in overlaps and b<a:a,b=b,a
            found[nid][frozenset((slot,peer))]=a+' → '+b
    result=[]
    for nid in sorted(found,key=lambda n:(name(n),n)):
        lines=sorted(found[nid].values())
        result.append(dict(node_id=nid,name=name(nid),color=color,lines=tuple(lines),
                           text=name(nid)+' · 코어 이어짐\n'+'\n'.join(lines)))
    return result


def core_connection_highlight(store,slots):
    audit=field_slot_audit(store);net=audit['net'];seeds=set(map(tuple,slots))
    chosen={audit['by_slot'][s]['key']:audit['by_slot'][s] for s in seeds if s in audit['by_slot']}
    components=dict(chosen)
    # Equal 임시 IDs split by a rebuilt cable are shown like equal real IDs.
    components.update(same_temporary_components(audit,chosen.values()))
    # Expand only real identities found on these components; never recurse.
    identities={cid for c in components.values() for cid in c['real_ids']}
    for cid in identities:
        for c in audit['by_id'].get(cid,()):components[c['key']]=c
    groups=[];by_slot={};bands=defaultdict(list);free=defaultdict(list);label_colors={};cable_slots=defaultdict(set)
    for index,comp in enumerate(sorted(components.values(),key=lambda c:c['slots'][0])):
        number=index+1;color=core_segment_color(index)
        group=dict(key=comp['key'],number=number,color=color,slots=tuple(comp['slots']),ids=tuple(comp['real_ids']),
                   selected=comp['key'] in chosen,off_only=comp['off_only'],issues=tuple(comp['notes']+comp['holds']))
        groups.append(group);cable_lines=defaultdict(list)
        for slot in comp['slots']:
            by_slot[slot]=group;row=audit['rows'].get(slot,{})
            if slot[0] in net.cables:cable_slots[slot[0]].add(slot)
            cid=str(row.get('core_id') or '').strip()
            number_text=str(row.get('label') or slot[1]) if slot[0].startswith('PORT:') else str(slot[1])
            line=number_text+' · '+(cid or 'ID 없음')+(' · OFF' if core_signal_off(row) else '')
            owners=[slot[0]] if slot[0] in net.cables else sorted({s[0] for _,s in net.links.get(slot,()) if s[0] in net.cables})
            for cable in owners:
                cable_lines[cable].append(('RN 포트 ' if slot[0].startswith('PORT:') else '')+line)
        faults=[]
        for cause,label in (('identity','코어ID 다름'),('signal','신호 불일치'),('branch','중복·분기'),('invalid','접속정보 오류'),('marked','오류 상태')):
            if cause in comp['causes']:faults.append(label)
        group['faults']=tuple(faults)
        for cable,lines in cable_lines.items():
            text=f'구간 {number}'+(' · ID 충돌' if 'identity' in comp['causes'] else '')+'\n'+'\n'.join(lines)
            if faults:text+='\n'+' · '.join(faults);label_colors[cable]='#c62828'
            bands[cable].append(dict(number=number,color=color,text=text))
        for nid,slot in comp['free']:
            if slot in audit['exception_complete_slots'] or (core_connection_exempt(audit['rows'].get(slot)) and not core_signal_off(audit['rows'].get(slot))):continue
            row=audit['rows'].get(slot,{})
            # Corrupt ports/splices must be reviewed, not offered as free ends.
            occupied=any(n==nid for n,_ in net.links.get(slot,())) or bool(net.bad.get(slot))
            cable=net.cables.get(slot[0],{})
            owner=str(cable.get('cable_id') or cable.get('spec') or slot[0]) if cable else 'RN 내부'
            position=str(row.get('label') or slot[1]) if slot[0].startswith('PORT:') else str(slot[1])
            free[nid].append(dict(slot=slot,group=number,color=color,owner=owner,index=position,
                core_id=str(row.get('core_id') or ''),off=core_signal_off(row),occupied=occupied,
                ids=set(comp['real_ids']),signals=set(comp['signals']),fault=bool(faults or comp['holds']),
                text=f'구간 {number} · {owner} / {position} · '+(str(row.get('core_id') or '') or 'ID 없음')))
    boundaries=[];blocked=defaultdict(list)
    if completion_kind(store)=='after':
        for item in after_auto_diagnostics(store):
            if item['core_id'] in identities:blocked[item['node_id']].append(item['reason'])
    for nid,ends in sorted(free.items(),key=lambda v:(net.nodes.get(v[0],{}).get('name',''),v[0])):
        node=net.nodes.get(nid)
        if not node:continue
        ends.sort(key=lambda e:(e['group'],e['owner'],e['index'],e['slot']))
        active=[e for e in ends if not e['off']]
        eligible=[e for e in active if not e['occupied'] and not e['fault']]
        candidates=[]
        for i,left in enumerate(eligible):
            for right in eligible[i+1:]:
                if left['group']==right['group'] or left['slot'][0]==right['slot'][0]:continue
                ids=left['ids']|right['ids'];signals=left['signals']|right['signals']
                if len(ids)<=1 and len(signals)<=1 and signals<={'on','off','exception'}:
                    candidates.append((left['slot'],right['slot']))
        if not active:title='OFF · 배정 제외';kind='off'
        elif len(candidates)==1 and len(active)==2:title='연결 후보 · 양쪽 번호 확인';kind='pair'
        elif candidates:title='연결 후보 여러 개 · 선택 필요';kind='ambiguous'
        elif any(e['fault'] or e['occupied'] for e in active) or len({e['group'] for e in active})>1:title='미접속 · ID·신호·번호 확인';kind='review'
        elif node.get('type')=='rn':title='RN 내부포트 접속 확인';kind='open'
        else:title='미접속 · 반대편 확인';kind='open'
        # OFF-only missing allocation does not receive a warning marker.
        if kind=='off':continue
        boundaries.append(dict(node_id=nid,name=node.get('name') or nid,title=title,kind=kind,ends=ends,
            candidates=tuple(candidates),color='#a16207' if kind in ('pair','ambiguous','open') else '#c62828',
            text=(node.get('name') or nid)+' · '+title+'\n'+'\n'.join(e['text']+(' · OFF 배정 제외' if e['off'] else '') for e in ends)))
        reasons=list(dict.fromkeys([reason for e in ends for reason in net.bad.get(e['slot'],())]+blocked[nid]))
        if reasons:boundaries[-1]['text']+='\n'+'\n'.join(reasons)
    # Count distinct cable slots, not selections, port rows or geometric crossings.
    # One route may also traverse the same cable on different physical cores.
    overlaps={c for c,slots in cable_slots.items() if len(slots)>1}
    colors={c:OVERLAP_COLOR if c in overlaps else items[0]['color'] for c,items in bands.items()}
    labels={c:(f'겹침 · {len(cable_slots[c])}개 코어\n' if c in overlaps else '')+'\n'.join(item['text'] for item in items) for c,items in bands.items()}
    short_labels,legend,port_labels=compact_route_display(groups,audit['rows'],net.cables,overlaps,nodes=net.nodes)
    junctions=overlap_junctions(net,audit['rows'],by_slot,overlaps)
    summary=f'실제 접속 {len(groups)}구간 · 미접속 함체 {len(boundaries)}곳 · 겹침 케이블 {len(overlaps)}개(진분홍)'
    if junctions:summary+=f' · 코어 이어짐 안내 {len(junctions)}곳'
    return dict(junctions=junctions,groups=groups,by_slot=by_slot,bands=dict(bands),colors=colors,labels=labels,short_labels=short_labels,legend=legend,port_labels=port_labels,label_colors=label_colors,
                boundaries=boundaries,summary=summary,seed_slots=tuple(sorted(seeds)),overlaps=frozenset(overlaps))


def signal_mixed_cores(store):
    """V166: core IDs whose entered signals differ (e.g. ON and OFF). 미입력 is neutral. Read-only."""
    groups={}
    for table,owner,index in (('cores','cable_id','core_index'),('ports',"'PORT:'||node_id",'port_index')):
        for row in store.conn.execute(f"SELECT {owner} AS owner,{index} AS idx,core_id,detail,signal FROM {table} WHERE TRIM(COALESCE(core_id,''))<>'' ORDER BY core_id,owner,idx"):
            cid=str(row['core_id']).strip();group=groups.setdefault(cid,dict(counts=defaultdict(int),names=[],slots=[]))
            code=core_signal_code(row['signal']);code=code if code in ROUTE_SIGNAL_TEXT else 'unknown'
            group['counts'][code]+=1;group['slots'].append(((row['owner'],int(row['idx'])),code))
            name=str(row['detail'] or '').strip()
            if name and name not in group['names']:group['names'].append(name)
    result=[]
    order=('on','off','exception','error')
    for cid in sorted(groups):
        group=groups[cid];counts=group['counts']
        if len([c for c in counts if c!='unknown'])<2:continue
        result.append(dict(core_id=cid,detail=' / '.join(group['names']),counts=dict(counts),slots=group['slots'],
                           text='신호 섞임: '+' · '.join(f'{ROUTE_SIGNAL_SHORT[c]} {counts[c]}' for c in order if counts.get(c))))
    return result


def signal_mix_warning(store,slots,signal):
    """V166: warning text when giving `signal` to these numbers leaves their
    connected path with different entered signals; '' when it stays one signal.

    Numbers that follow the edit (same ID when the drawing changes signals by
    ID, connected temporary cores) are not counted. Read-only.
    """
    code=core_signal_code(signal)
    if code not in ROUTE_SIGNAL_TEXT or code=='unknown':return ''
    changed={tuple(s) for s in slots};by_id=not field_slot_mode(store) and completion_kind(store)!='after'
    ids={str((store.core(*s) or {}).get('core_id') or '').strip() for s in changed}-{''}
    others=defaultdict(list)
    for slot in sorted(changed):
        for other in sorted(store.component(slot)):
            other=tuple(other)
            if other in changed:continue
            row=store.core(*other)
            if not row:continue
            cid=str(row['core_id'] or '').strip()
            if cid and cid in ids and (by_id or cid.startswith('임시-')):continue
            found=core_signal_code(row['signal'])
            if found==code or found=='unknown' or found not in ROUTE_SIGNAL_TEXT:continue
            title=store._slot_title(*other)
            if title not in others[found]:others[found].append(title)
    if not others:return ''
    lines=[f'{ROUTE_SIGNAL_SHORT[c]}: '+', '.join(t[:3])+(f' 외 {len(t)-3}곳' if len(t)>3 else '') for c,t in others.items()]
    return ('연결된 다른 구간의 신호가 다릅니다.\n'+'\n'.join(lines)+
            f'\n\n{ROUTE_SIGNAL_SHORT[code]}(으)로 바꾸면 이 경로가 「신호 섞임」이 됩니다. 그래도 바꿀까요?')


def core_signal_summary_label(store,rows):
    """V168: one signal for a core in the 함체 코어내역 table, read over every
    saved position of its ID: only ON → ON, only OFF → OFF, nothing entered →
    확인필요, different entered signals → 섞임 (ON / OFF). Read-only."""
    overview=core_id_overview(store);codes=set()
    for row in rows:
        row=dict(row or {});cid=str(row.get('core_id') or '').strip()
        if cid and cid in overview:codes|={code for code,count in overview[cid]['counts'].items() if count}
        else:codes.add(core_signal_code(row.get('signal')))
    order=('on','off','exception','error')
    known=sorted(codes-{'unknown'},key=lambda c:(order.index(c) if c in order else len(order),c))
    if not known:return CORE_SIGNAL_NAMES['unknown']
    if len(known)==1:return CORE_SIGNAL_NAMES.get(known[0],known[0])
    return '섞임 ('+' / '.join(CORE_SIGNAL_NAMES.get(c,c) for c in known)+')'
