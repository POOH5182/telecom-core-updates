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


def core_connection_highlight(store,slots):
    audit=field_slot_audit(store);net=audit['net'];seeds=set(map(tuple,slots))
    chosen={audit['by_slot'][s]['key']:audit['by_slot'][s] for s in seeds if s in audit['by_slot']}
    components=dict(chosen)
    # Expand only real identities found on the selected physical components.
    # Do not follow equal temporary tokens or recursively chase unrelated IDs.
    identities={cid for c in chosen.values() for cid in c['real_ids']}
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
    boundaries=[]
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
    # Count distinct cable slots, not selections, port rows or geometric crossings.
    # One route may also traverse the same cable on different physical cores.
    overlaps={c for c,slots in cable_slots.items() if len(slots)>1}
    colors={c:OVERLAP_COLOR if c in overlaps else items[0]['color'] for c,items in bands.items()}
    labels={c:(f'겹침 · {len(cable_slots[c])}개 코어\n' if c in overlaps else '')+'\n'.join(item['text'] for item in items) for c,items in bands.items()}
    summary=f'실제 접속 {len(groups)}구간 · 미접속 함체 {len(boundaries)}곳 · 겹침 케이블 {len(overlaps)}개(진분홍)'
    return dict(groups=groups,by_slot=by_slot,bands=dict(bands),colors=colors,labels=labels,label_colors=label_colors,
                boundaries=boundaries,summary=summary,seed_slots=tuple(sorted(seeds)),overlaps=frozenset(overlaps))
