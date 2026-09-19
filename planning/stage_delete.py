"""Reviewed current-stage removal, previous-stage activation and local recovery."""
STAGE_ORDER=('gis','before','after')
STAGE_NAMES={'gis':'GIS 도면','before':'현장반영 도면','after':'후도면'}


def stage_database_token(conn):
    tables=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    values={}
    for table in tables:
        name='"'+table.replace('"','""')+'"'
        values[table]=sorted([list(r) for r in conn.execute('SELECT * FROM '+name)],key=lambda r:json.dumps(r,ensure_ascii=False,default=str))
    return digest(values)


def stage_file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def stage_state_token(app):
    return dict(owner=str(app.store.path.resolve()),kind=app.scenario_kind(),working=stage_database_token(app.store.conn),
                snapshots={kind:stage_file_hash(app.scenario_path(kind)) for kind in STAGE_ORDER})


def stage_require_idle(app,check_locks=True):
    store=app.store
    if store.conn.hold_commit or store._history_depth or getattr(app,'pending_drag',None) or getattr(app,'_saving_now',False):
        raise ValueError('진행 중인 편집이나 저장을 마친 뒤 다시 실행하세요.')
    cloud=getattr(app,'cloud',None)
    if cloud and getattr(getattr(cloud,'jobs',None),'busy',False):raise ValueError('클라우드 동기화가 끝난 뒤 다시 실행하세요.')
    if check_locks and (locked(store) or any_node_locked(store)):raise ValueError('현재 도면의 편집 잠금과 함체 잠금을 해제한 뒤 실행하세요.')


def stage_delete_preview(app):
    stage_require_idle(app);kind=app.scenario_kind()
    if kind not in STAGE_ORDER:raise ValueError('현재 도면 단계를 확인할 수 없습니다.')
    previous=STAGE_ORDER[STAGE_ORDER.index(kind)-1] if kind!='gis' else None
    if previous and not app.scenario_path(previous).exists():
        raise ValueError(STAGE_NAMES[previous]+' 저장본이 없어 이전 단계로 돌아갈 수 없습니다. 이전 도면을 먼저 확인하세요. 현재 도면은 유지됩니다.')
    if previous:
        conn=sqlite3.connect(app.scenario_path(previous).resolve().as_uri()+'?mode=ro',uri=True)
        try:
            if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('이전 단계 저장본을 읽을 수 없습니다. 삭제를 중단합니다.')
            # Refuse a non-drawing SQLite file before making any change.
            conn.execute('SELECT id FROM nodes LIMIT 1');conn.execute('SELECT key FROM workflow_state LIMIT 1')
        finally:conn.close()
    return dict(kind=kind,previous=previous,token=stage_state_token(app),generation=app.store._view_generation,
                counts={t:app.store.conn.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('nodes','cables','cores','splices')})


def stage_recovery_root(app):
    return app.scenario_folder().parent.parent/'backup'/'stage_deletions'/app.store.path.stem


def stage_recovery_marker(app):return app.scenario_folder()/'stage_delete_undo.json'


def stage_write_json(path,value):
    cloud_atomic(path,json.dumps(value,ensure_ascii=False,sort_keys=True).encode('utf-8'))


def stage_restore_store(store,path):
    store.conn.commit();source=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:source.backup(store.conn)
    finally:source.close()
    store.create_schema()
    for name in ('_warning_cache','_cable_warning_cache','_trace_context_cache','_trace_context_revision','_annotation_stamp','_phase_stamp'):
        setattr(store,name,None)


def stage_backup(app,label):
    folder=stage_recovery_root(app)/(datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'_'+uuid.uuid4().hex[:8]+'_'+label)
    folder.mkdir(parents=True,exist_ok=False);app.store.backup_to(folder/'working.sqlite3')
    for kind in STAGE_ORDER:
        source=app.scenario_path(kind)
        if source.exists():shutil.copy2(source,folder/(kind+'.sqlite3'))
    return folder


def stage_delete_commit(app,preview):
    current=stage_delete_preview(app)
    if current!=preview:raise ValueError('검토 중 도면이나 저장본이 바뀌었습니다. 삭제 내용을 다시 확인하세요.')
    store=app.store;store.conn.commit();old_revision=store.data_revision();folder=stage_backup(app,preview['kind'])
    marker=stage_recovery_marker(app);old_marker=marker.read_bytes() if marker.exists() else None
    deleted=app.scenario_path(preview['kind']);moved=folder/'removed_snapshot.sqlite3';removed=False;changed=False
    info=dict(schema=1,owner=str(store.path.resolve()),kind=preview['kind'],previous=preview['previous'],
              had_snapshot=deleted.exists(),hashes={p.name:stage_file_hash(p) for p in folder.glob('*.sqlite3')})
    # A durable recovery record exists before the first destructive operation.
    stage_write_json(folder/'recovery.json',info)
    try:
        if deleted.exists():os.replace(deleted,moved);removed=True
        changed=True
        if preview['previous']:
            stage_restore_store(store,folder/(preview['previous']+'.sqlite3'))
        else:
            blank=type(store)(folder/'blank.sqlite3')
            try:blank.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','gis')");blank.conn.commit()
            finally:blank.close()
            stage_restore_store(store,folder/'blank.sqlite3')
        kind=preview['previous'] or 'gis'
        store.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario',?)",(kind,))
        store.conn.execute("INSERT OR REPLACE INTO meta VALUES('data_revision',?)",(str(max(old_revision,store.data_revision())+1),));store.conn.commit()
        info['post']=stage_state_token(app);stage_write_json(folder/'recovery.json',info)
        stage_write_json(marker,dict(schema=1,folder=folder.name,owner=info['owner']))
    except Exception:
        if changed:stage_restore_store(store,folder/'working.sqlite3')
        if removed:os.replace(moved,deleted)
        if old_marker is None:marker.unlink(missing_ok=True)
        else:cloud_atomic(marker,old_marker)
        raise
    return folder


def stage_restore_preview(app):
    # A previous snapshot can itself contain locks. Exact post-state equality
    # below permits reversal of that switch without editing/unlocking it first.
    stage_require_idle(app,check_locks=False);marker=stage_recovery_marker(app)
    if not marker.exists():raise ValueError('되돌릴 단계 삭제 기록이 없습니다.')
    pointer=json.loads(marker.read_text(encoding='utf-8'))
    if not isinstance(pointer,dict) or pointer.get('schema')!=1:raise ValueError('삭제 백업 정보가 올바르지 않습니다.')
    name=pointer.get('folder','')
    if not isinstance(name,str) or not name or Path(name).name!=name or pointer.get('owner')!=str(app.store.path.resolve()):raise ValueError('현재 도면의 삭제 백업이 아닙니다.')
    folder=stage_recovery_root(app)/name
    if folder.resolve().parent!=stage_recovery_root(app).resolve():raise ValueError('삭제 백업 경로가 올바르지 않습니다.')
    info=json.loads((folder/'recovery.json').read_text(encoding='utf-8'))
    if not isinstance(info,dict) or info.get('schema')!=1 or info.get('owner')!=pointer['owner'] or info.get('kind') not in STAGE_ORDER:raise ValueError('삭제 백업 정보가 올바르지 않습니다.')
    hashes=info.get('hashes');allowed={'working.sqlite3'}|{k+'.sqlite3' for k in STAGE_ORDER}
    required={'working.sqlite3'}|({info['kind']+'.sqlite3'} if info.get('had_snapshot') else set())
    if not isinstance(info.get('had_snapshot'),bool) or not isinstance(hashes,dict) or not required<=set(hashes)<=allowed or any(not isinstance(v,str) or len(v)!=64 for v in hashes.values()):raise ValueError('삭제 백업 파일 정보가 올바르지 않습니다.')
    if info.get('post')!=stage_state_token(app):raise ValueError('단계 삭제 후 도면이나 저장본이 변경되었습니다. 현재 작업을 보호하기 위해 바로 되돌리기를 중단합니다. 삭제 전 백업은 backup/stage_deletions에 보관되어 있습니다.')
    if any(stage_file_hash(folder/name)!=value for name,value in hashes.items()):raise ValueError('삭제 백업 파일이 변경되어 복원을 중단합니다.')
    return dict(folder=str(folder),info=info,generation=app.store._view_generation)


def stage_restore_commit(app,preview):
    if stage_restore_preview(app)!=preview:raise ValueError('복원 검토 중 도면이 변경되었습니다. 다시 확인하세요.')
    folder=Path(preview['folder']);info=preview['info'];target=app.scenario_path(info['kind']);rollback=stage_backup(app,'before_restore')
    marker=stage_recovery_marker(app);old_marker=marker.read_bytes();restored=False
    try:
        if info['had_snapshot']:cloud_atomic(target,(folder/(info['kind']+'.sqlite3')).read_bytes());restored=True
        stage_restore_store(app.store,folder/'working.sqlite3')
        marker.unlink()
    except Exception:
        stage_restore_store(app.store,rollback/'working.sqlite3')
        if restored:target.unlink(missing_ok=True)
        cloud_atomic(marker,old_marker)
        raise
    return folder


def stage_open_editors(app):
    # Do not discard an editor's private, not-yet-saved draft during a reset.
    return [w for w in app.winfo_children() if isinstance(w,tk.Toplevel) and
            (getattr(w,'store',None) is app.store or getattr(getattr(w,'service',None),'store',None) is app.store)]


def stage_check_editors(app):
    if stage_open_editors(app):raise ValueError('열린 케이블·함체·코어 편집창을 먼저 저장하거나 닫아 주세요. 입력 중인 내용은 유지됩니다.')


def stage_refresh_app(app):
    panel=getattr(app,'_map_allocation_panel',None)
    if panel is not None:panel.destroy(restore_editor=False)
    app.stop_highlight_blink(clear=True);app.selected.clear();app.preview_positions={};app.set_mode('select')
    for name in ('_work_report_key','work_progress_cache_key','work_progress_cache_value','error_core_cache_key'):
        setattr(app,name,None)
    app.error_core_cache_value=0;app.scenario_saved_revision=app.store.data_revision();app.update_title();app.refresh()
    if getattr(app,'cloud',None):app.after_idle(app.cloud.sync_now)


class StageDeleteDialog(RememberedToplevel):
    def __init__(self,app,parent=None):
        stage_check_editors(app);preview=stage_delete_preview(app)
        super().__init__(parent or app);self.app=app;self.preview=preview
        self.title('현재 단계 삭제 · 이전 단계로');self.geometry('640x430');self.minsize(560,380);self.transient(parent or app)
        body=ttk.Frame(self,padding=16);body.pack(fill='both',expand=True)
        name=STAGE_NAMES[preview['kind']];destination=STAGE_NAMES[preview['previous']] if preview['previous'] else '빈 GIS 화면'
        ttk.Label(body,text=name+' 삭제',style='Title.TLabel').pack(anchor='w',pady=(0,12))
        self.explanation=(f'삭제 대상: 현재 {name}와 해당 단계 저장본\n복귀 화면: {destination}\n\n'
                          f"시설 {preview['counts']['nodes']}개 · 케이블 {preview['counts']['cables']}개 · 접속 {preview['counts']['splices']}개\n\n"
                          '다른 단계의 저장 도면은 그대로 유지합니다.\n삭제 전 현재 작업과 단계별 저장본을 자동 백업합니다.\n삭제 직후에는 「단계 삭제 되돌리기」로 복원할 수 있습니다.\n복귀 후 도면을 수정·저장하면 바로 되돌리기는 중단됩니다.')
        ttk.Label(body,text=self.explanation,justify='left',wraplength=580).pack(fill='x')
        self.notice=tk.StringVar();ttk.Label(body,textvariable=self.notice,foreground='#b91c1c',wraplength=580).pack(fill='x',pady=10)
        actions=ttk.Frame(body);actions.pack(side='bottom',fill='x',pady=8)
        self.apply_button=ttk.Button(actions,text='백업 후 현재 단계 삭제',style='Danger.TButton',command=self.apply);self.apply_button.pack(side='right')
        self.cancel_button=ttk.Button(actions,text='취소',command=self.destroy);self.cancel_button.pack(side='right',padx=8)
        self.bind('<Escape>',lambda e:self.destroy());self.grab_set();self.cancel_button.focus_set()

    def apply(self):
        try:
            stage_check_editors(self.app);folder=stage_delete_commit(self.app,self.preview)
        except (ValueError,sqlite3.Error,OSError) as error:self.notice.set(str(error));return
        app=self.app;kind=self.preview['kind'];previous=self.preview['previous'];self.destroy();stage_refresh_app(app)
        app.status.set(STAGE_NAMES[kind]+' 삭제 완료 · '+(STAGE_NAMES[previous] if previous else '빈 GIS 화면')+'으로 복귀 · 단계 삭제 되돌리기 가능')


def open_stage_delete(app,parent=None):
    try:return StageDeleteDialog(app,parent)
    except (ValueError,sqlite3.Error,OSError) as error:messagebox.showinfo('현재 단계 삭제',str(error),parent=parent or app)


def restore_stage_delete(app,parent=None):
    try:
        stage_check_editors(app);preview=stage_restore_preview(app)
        if not messagebox.askyesno('단계 삭제 되돌리기',STAGE_NAMES[preview['info']['kind']]+' 삭제 직전의 작업과 저장본을 복원할까요?',parent=parent or app):return
        stage_restore_commit(app,preview);stage_refresh_app(app);app.status.set('단계 삭제를 되돌렸습니다. 삭제 전 도면·수정 이력·단계 저장본을 복원했습니다.')
    except (ValueError,sqlite3.Error,OSError) as error:messagebox.showinfo('단계 삭제 되돌리기',str(error),parent=parent or app)
