"""Pinned stage windows: isolated reads, separate detail dialogs and Windows navigation."""
import faulthandler
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from check_after_plan import code,wf


def set_stage(store,kind):
    store.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario',?)",(kind,))
    store.conn.commit()


def fixture(store):
    a=store.add_node('SYNTH 시작',1600,600)
    h=store.add_node('SYNTH 접속함체',1900,600)
    b=store.add_node('SYNTH 끝',2200,600)
    left=store.add_cable(a,h,'SYNTH-LEFT','12C','기설')
    right=store.add_cable(h,b,'SYNTH-RIGHT','12C','기설')
    return a,h,b,left,right


def save_stage(store,path,kind,ids):
    a,h,b,left,right=ids;number={'gis':7,'before':4,'after':9}[kind]
    set_stage(store,kind)
    with store.action('Synthetic '+kind+' connection'):
        store.conn.execute('DELETE FROM splices')
        store.conn.execute("UPDATE cores SET core_id='',detail='',signal=''")
        for cable,index in ((left,3),(right,number)):
            store.conn.execute("UPDATE cores SET core_id=?,detail=?,signal='on' WHERE cable_id=? AND core_index=?",
                               (kind.upper()+'-ID','SYNTH '+kind+' service',cable,index))
        first,second=sorted(((left,3),(right,number)))
        store.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(h,*first,*second))
    store.backup_to(path)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.working=code['Store'](self.home/'working.sqlite3');self.ids=fixture(self.working)
        self.path=self.home/'gis.sqlite3';save_stage(self.working,self.path,'gis',self.ids)

    def tearDown(self):
        self.working.close();self.temp.cleanup()

    def test_exact_previous_stage_mapping_has_no_gis_or_unknown_fallback(self):
        self.assertEqual(wf.reference_kind('before'),'gis')
        self.assertEqual(wf.reference_kind('after'),'before')
        self.assertIsNone(wf.reference_kind('gis'))
        self.assertIsNone(wf.reference_kind('unknown'))

    def test_source_schema_history_and_bytes_untouched_while_clone_is_read_only(self):
        # A Store constructor recreates this index. It may migrate its private
        # clone, but must never run those writes against the saved GIS source.
        conn=sqlite3.connect(self.path)
        try:conn.execute('DROP INDEX idx_cores_id');conn.commit()
        finally:conn.close()
        source=self.path.read_bytes();working=wf.stage_database_token(self.working.conn)
        snapshot=wf.ReferenceSnapshot(code['Store'],self.path);connection=snapshot.store.conn
        try:
            self.assertNotEqual(snapshot.store.path.resolve(),self.path.resolve())
            self.assertEqual(connection.execute('PRAGMA query_only').fetchone()[0],1)
            left,right=self.ids[-2:]
            self.assertEqual(snapshot.store.core(left,3)['core_id'],'GIS-ID')
            self.assertEqual(snapshot.store.component((left,3)),{(left,3),(right,7)})
            self.assertIsNotNone(connection.execute("SELECT name FROM sqlite_master WHERE name='idx_cores_id'").fetchone())
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("UPDATE cores SET detail='Forbidden reference edit'")
            self.assertEqual(self.path.read_bytes(),source)
            self.assertEqual(wf.stage_database_token(self.working.conn),working)
        finally:snapshot.close()
        with self.assertRaises(sqlite3.ProgrammingError):connection.execute('SELECT 1')
        self.assertEqual(self.path.read_bytes(),source)

    def test_snapshot_remains_isolated_until_explicit_replacement(self):
        first=wf.ReferenceSnapshot(code['Store'],self.path)
        try:
            save_stage(self.working,self.path,'before',self.ids)
            second=wf.ReferenceSnapshot(code['Store'],self.path)
            try:
                self.assertEqual(first.store.core(self.ids[-2],3)['core_id'],'GIS-ID')
                self.assertEqual(second.store.core(self.ids[-2],3)['core_id'],'BEFORE-ID')
                self.assertEqual(first.store.component((self.ids[-2],3)),{(self.ids[-2],3),(self.ids[-1],7)})
                self.assertEqual(second.store.component((self.ids[-2],3)),{(self.ids[-2],3),(self.ids[-1],4)})
            finally:second.close()
        finally:first.close()

    def test_projection_uses_actual_peers_and_keeps_shared_labels_and_memo(self):
        left,right=self.ids[-2:]
        with self.working.action('Synthetic disconnected duplicate ID'):
            self.working.conn.execute("UPDATE cores SET core_id='GIS-ID',signal='off' WHERE cable_id=? AND core_index=5",(left,))
        wf.save_annotations(self.working,(left,3),['현장 재확인'],'SYNTH 공통 메모')
        self.working.backup_to(self.path);source=self.path.read_bytes()
        snapshot=wf.ReferenceSnapshot(code['Store'],self.path)
        try:
            before=wf.stage_database_token(snapshot.store.conn)
            rows={row['slot']:dict(zip(wf.REFERENCE_COLUMNS,row['values']))
                  for row in wf.reference_core_rows(snapshot.store,'core','GIS-ID')}
            self.assertEqual(set(rows),{(left,3),(left,5),(right,7)})
            self.assertIn('SYNTH-RIGHT / 7번',rows[left,3]['end'])
            self.assertIn('SYNTH-LEFT / 3번',rows[right,7]['start'])
            for end in ('start','end'):self.assertIn('미접속',rows[left,5][end])
            self.assertEqual(rows[left,5]['signal'],'OFF')
            route=wf.reference_detail_rows(snapshot.store,'route',(left,3))
            self.assertEqual({row['slot'] for row in route},{(left,3),(right,7)})
            for row in rows.values():
                self.assertIn('현장 재확인',row['state']);self.assertIn('SYNTH 공통 메모',row['state'])
            self.assertEqual(wf.stage_database_token(snapshot.store.conn),before)
            self.assertEqual(self.path.read_bytes(),source)
        finally:snapshot.close()

    def test_detail_route_keeps_real_mismatched_peer_and_excludes_disconnected_same_id(self):
        left,right=self.ids[-2:]
        with self.working.action('Synthetic mismatched physical path'):
            self.working.conn.execute("UPDATE cores SET core_id='GIS-ID' WHERE cable_id=? AND core_index=5",(left,))
            self.working.conn.execute("UPDATE cores SET core_id='DIFFERENT-ID' WHERE cable_id=? AND core_index=7",(right,))
        self.working.backup_to(self.path);source=self.path.read_bytes()
        snapshot=wf.ReferenceSnapshot(code['Store'],self.path)
        try:
            token=wf.stage_database_token(snapshot.store.conn)
            rows=wf.reference_detail_rows(snapshot.store,'route',(left,3))
            self.assertEqual({row['slot'] for row in rows},{(left,3),(right,7)})
            self.assertEqual({row['values'][2] for row in rows},{'GIS-ID','DIFFERENT-ID'})
            self.assertEqual(wf.stage_database_token(snapshot.store.conn),token)
            self.assertEqual(self.path.read_bytes(),source)
        finally:snapshot.close()

    def test_missing_or_corrupt_source_does_not_create_or_rewrite_a_drawing(self):
        missing=self.home/'never-saved.sqlite3'
        with self.assertRaises((ValueError,OSError,sqlite3.Error)):
            wf.ReferenceSnapshot(code['Store'],missing)
        self.assertFalse(missing.exists())
        corrupt=self.home/'corrupt.sqlite3';corrupt.write_bytes(b'Not a SQLite drawing')
        with self.assertRaises((ValueError,OSError,sqlite3.Error)):
            wf.ReferenceSnapshot(code['Store'],corrupt)
        self.assertEqual(corrupt.read_bytes(),b'Not a SQLite drawing')


def tree_text(tree):
    return '\n'.join('\t'.join(map(str,tree.item(item,'values'))) for item in tree.get_children())


def pump(app,milliseconds=850):
    ready=wf.tk.BooleanVar(master=app,value=False)
    app.after(milliseconds,lambda:ready.set(True));app.wait_variable(ready);app.update()


def key(app,widget,sequence):
    widget.focus_force();app.update();widget.event_generate(sequence);app.update()


def poll(dialog):
    # Simulate a scheduled callback, consuming its old timer exactly once.
    job=dialog._poll_job
    if job:dialog.after_cancel(job)
    dialog._poll()


def detail_text(dialog):
    return '\n'.join(tree_text(tree) for tree in dialog.trees)


def populated_row(dialog,cable,index):
    for tree,mapping in dialog.row_map.items():
        for iid,row in mapping.items():
            if row['slot']==(cable,index):return tree,iid
    raise AssertionError(('Missing detail slot',cable,index))


def assert_stage_chrome(window,kind,reference=True):
    prefixes={'gis':'[GIS]','before':'[현장]','after':'[후도면]'}
    assert window.title().startswith(prefixes[kind]),window.title()
    assert window._stage_kind==kind and window._stage_reference is reference
    # The visible band is the user's primary cue even when title bars truncate.
    assert window._stage_banner.winfo_ismapped()
    assert ('참고용' if reference else '편집 중') in window._stage_banner_label.cget('text')
    return window._stage_banner.cget('bg')


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(180,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(wf.messagebox,'showinfo'),patch.object(wf.messagebox,'showwarning'), \
         patch.object(wf.messagebox,'showerror') as error,patch.object(wf.messagebox,'askyesno',return_value=True), \
         patch.object(wf.messagebox,'askyesnocancel',return_value=False):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;ids=fixture(s);a,h,b,left,right=ids
            for kind in ('gis','before','after'):save_stage(s,app.scenario_path(kind),kind,ids)
            wf.stage_restore_store(s,app.scenario_path('before'));app.scenario_saved_revision=s.data_revision()
            app.geometry('1000x720+0+0');app.update_title();app.refresh();app.update()
            assert app.dashboard_frame.place_info()['anchor']=='nw'
            config=dict(app.drawing_tools.config,enabled=app.drawing_tools.config['enabled']+['reference_drawing'])
            app.drawing_tools.apply(config);app.update()
            baseline=wf.stage_state_token(app)
            source_bytes={kind:app.scenario_path(kind).read_bytes() for kind in ('gis','before','after')}
            app.drawing_tools.buttons['reference_drawing'].invoke();app.update()
            chooser=wf.open_reference_drawing(app);app.update()
            assert isinstance(chooser,wf.ReferenceDrawingChooser) and chooser.grab_current() is None
            assert set(chooser.stage_buttons)=={'gis','before','after'}
            for button in chooser.stage_buttons.values():
                assert button.winfo_ismapped()
                assert button.winfo_rooty()+button.winfo_height()<=chooser.winfo_rooty()+chooser.winfo_height()
            viewers={}
            for kind in ('gis','before','after'):
                # Exercise the actual stage picker rather than only its helper.
                chooser=wf.open_reference_drawing(app);app.update()
                chooser.stage_buttons[kind].invoke();app.update()
                dialog=app._reference_drawings[kind];viewers[kind]=dialog
                assert dialog.source_kind==kind and Path(dialog.source_path)==app.scenario_path(kind)
                assert dialog.store is not s and dialog.reference_snapshot.store is dialog.store
                assert wf.open_reference_drawing(app,kind) is dialog
                assert dialog.grab_current() is None
                assert not hasattr(dialog,'core_tree'), 'The permanent lower ledger must be removed'
                assert dialog.dashboard_frame.place_info()['anchor']=='nw'
                dialog.geometry('960x650+20+20');app.update();dialog.fit_view();app.update()
            if chooser.winfo_exists():chooser.destroy()
            app.reference_windows_button.invoke();app.update()
            chooser=wf.open_reference_drawing(app);assert chooser.winfo_exists();chooser.destroy()
            manager=code['ScenarioDialog'](app);app.update()
            for kind,button in manager.reference_buttons.items():
                button.invoke();app.update();assert app._reference_drawings[kind] is viewers[kind]
            manager.destroy();app.update()
            assert len(app._reference_drawings)==3
            assert len({id(dialog.store) for dialog in viewers.values()})==3
            assert wf.stage_state_token(app)==baseline
            print('REFERENCE: three pinned stage drawings, full canvas, modeless stage details and visible identity',flush=True)
            colors={};details={};routes=[]
            for kind,dialog in viewers.items():
                colors[kind]=assert_stage_chrome(dialog,kind)
                dialog.select_item('node',h,center=True)
                detail=dialog.open_selected_detail();app.update();details[kind]=detail
                assert detail is wf.open_reference_detail(dialog,'node',h)
                assert detail.grab_current() is None and detail.store is dialog.store
                assert assert_stage_chrome(detail,kind)==colors[kind]
                shown=detail_text(detail)
                assert kind.upper()+'-ID' in shown and 'SYNTH '+kind+' service' in shown
                for other in set(viewers)-{kind}:assert other.upper()+'-ID' not in shown
                tree,row=populated_row(detail,left,3)
                assert 'SYNTH-RIGHT / '+str({'gis':7,'before':4,'after':9}[kind])+'번' in tree.set(row,'start')
                assert tree.set(row,'signal').upper()=='ON'
                assert all(str(entry.cget('state'))=='readonly' for entry in detail.header_entries)
                tree.selection_set(row);key(app,tree,'<Control-c>')
                assert kind.upper()+'-ID' in app.clipboard_get()
                route=detail.open_route();app.update();routes.append(route)
                assert route.grab_current() is None and route.store is dialog.store
                assert assert_stage_chrome(route,kind)==colors[kind]
                assert {r['slot'] for r in route.rows}=={(left,3),(right,{'gis':7,'before':4,'after':9}[kind])}
                key(app,tree,'<Control-f>');assert app.focus_get() is detail.find_entry
                detail.find_text.set(kind.upper()+'-ID');detail.find_next();app.update()
            assert len(set(colors.values()))==3,colors
            assert len({wf.stage_popup_position_key(d) for d in viewers.values()})==3
            assert len({wf.stage_popup_position_key(d) for d in details.values()})==3
            gis=viewers['gis'];field=viewers['before'];after=viewers['after']
            gis.select_item('cable',left);field.select_item('node',a);after.select_item('cable',right)
            other_views={kind:(d.selected_item,d.view_scale,d.canvas.xview(),d.canvas.yview())
                         for kind,d in viewers.items() if kind!='gis'}
            gis.find_text.set('GIS-ID');gis.find_next();app.update()
            gis.zoom_by(1.12,SimpleNamespace(x=320,y=180));app.update()
            gis.canvas.event_generate('<ButtonPress-3>',x=450,y=240)
            gis.canvas.event_generate('<B3-Motion>',x=340,y=240)
            gis.canvas.event_generate('<ButtonRelease-3>',x=340,y=240);app.update()
            for kind,state in other_views.items():
                d=viewers[kind];assert (d.selected_item,d.view_scale,d.canvas.xview(),d.canvas.yview())==state
            key(app,gis.canvas,'<Control-f>');assert app.focus_get() is gis.find_entry
            assert not getattr(app,'find_dialog',None)
            with patch.object(wf,'DrawingSaveDialog',side_effect=AssertionError('Reference shortcut reached main save')):
                for window in (*viewers.values(),*details.values(),*routes):
                    targets=(window.canvas,window.find_entry) if hasattr(window,'canvas') else (*window.trees,window.find_entry)
                    for widget in targets:
                        for sequence in ('<Control-s>','<Control-z>','<Control-y>'):key(app,widget,sequence)
            assert wf.stage_state_token(app)==baseline and not getattr(app,'_save_dialog',None)
            assert not errors,errors
            gis.find_text.set('copy this text');gis.find_entry.selection_range(0,4)
            key(app,gis.find_entry,'<Control-c>');assert app.clipboard_get()=='copy'
            # Each stage remembers its own position; moving GIS must not move field/after.
            for index,(kind,dialog) in enumerate(viewers.items()):
                dialog.geometry(f'960x650+{10+index*12}+{10+index*12}')
            app.update();positions={kind:d.geometry() for kind,d in viewers.items()}
            for kind in viewers:assert wf.open_reference_drawing(app,kind).geometry()==positions[kind]
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True)
                for kind in ('gis','before','after'):
                    dialog=viewers[kind];dialog.geometry('960x650+20+20');dialog.fit_view();app.update()
                    screenshot(dialog,Path('dist')/('v119-'+kind+'-drawing.png'))
                cable_detail=wf.open_reference_detail(gis,'cable',left);app.update()
                cable_detail.geometry('960x620+20+20');app.update()
                screenshot(cable_detail,Path('dist')/'v119-gis-cable-details.png')
            # Main right-drag panning and actual editing remain available while
            # references and all their child detail windows are still open.
            app.lift();app.canvas.xview_moveto(.15);old_view=app.canvas.xview()
            drawing=wf.stage_database_token(s.conn)
            app.canvas.event_generate('<ButtonPress-3>',x=500,y=80)
            app.canvas.event_generate('<B3-Motion>',x=370,y=80)
            app.canvas.event_generate('<ButtonRelease-3>',x=370,y=80);app.update()
            assert app.canvas.xview()!=old_view
            assert wf.stage_database_token(s.conn)==drawing
            app.set_mode('hamche');count=len(s.nodes())
            app.canvas.event_generate('<ButtonPress-1>',x=500,y=300)
            app.canvas.event_generate('<ButtonRelease-1>',x=500,y=300);app.update()
            assert len(s.nodes())==count+1
            key(app,app.canvas,'<Control-z>');assert len(s.nodes())==count
            editor=code['CableDialog'](app,s,left);app.update();editor.lot_var.set('Uncommitted LOT draft')
            assert_stage_chrome(editor,'before',reference=False)
            baseline=wf.stage_state_token(app);old_detail=details['gis'];old_conn=gis.store.conn
            old_snapshot_dir=Path(gis.reference_snapshot.temp.name)
            gis.reload_source(force=True);app.update()
            assert not old_detail.winfo_exists() and not routes[0].winfo_exists() and not old_snapshot_dir.exists()
            with unittest.TestCase().assertRaises(sqlite3.ProgrammingError):old_conn.execute('SELECT 1')
            assert editor.lot_var.get()=='Uncommitted LOT draft' and wf.stage_state_token(app)==baseline
            for kind,content in source_bytes.items():assert app.scenario_path(kind).read_bytes()==content
            editor.destroy();app.update()
            print('REFERENCE: pinned stages across main switch, saved-source reload, project changes and owned cleanup',flush=True)
            geometry={kind:d.geometry() for kind,d in viewers.items()}
            with patch.object(app,'field_ready_for_after',return_value=True):app.workflow_buttons['after'].invoke()
            app.update()
            assert app.scenario_kind()=='after'
            for kind,dialog in viewers.items():
                poll(dialog);app.update()
                assert dialog.source_kind==kind and dialog.geometry()==geometry[kind]
                assert dialog.store.core(left,3)['core_id']==kind.upper()+'-ID'
                assert dialog.store.component((left,3))=={(left,3),(right,{'gis':7,'before':4,'after':9}[kind])}
            # Refresh only a changed saved stage. Editing the reference itself
            # remains impossible and unrelated stage viewers keep their stores.
            field_snapshot=field.reference_snapshot;after_snapshot=after.reference_snapshot
            source=app.scenario_path('gis')
            detail=wf.open_reference_detail(gis,'cable',left);app.update();old_conn=gis.store.conn
            saved=code['Store'](source)
            try:
                with saved.action('Synthetic saved GIS source update'):
                    saved.conn.execute("UPDATE cores SET detail='SYNTH updated saved GIS' WHERE cable_id=? AND core_index=3",(left,))
            finally:saved.close()
            poll(gis);app.update()
            assert not detail.winfo_exists() and gis.store.core(left,3)['detail']=='SYNTH updated saved GIS'
            assert field.reference_snapshot is field_snapshot and after.reference_snapshot is after_snapshot
            with unittest.TestCase().assertRaises(sqlite3.ProgrammingError):old_conn.execute('SELECT 1')
            source_bytes=source.read_bytes();source.unlink();baseline=wf.stage_state_token(app)
            poll(gis);app.update()
            assert gis.source_kind=='gis' and gis.store is None and not gis._reference_details
            assert wf.stage_state_token(app)==baseline and not source.exists()
            assert field.store and after.store
            chooser=wf.open_reference_drawing(app);app.update()
            assert str(chooser.stage_buttons['gis'].cget('state'))=='disabled';chooser.destroy()
            source.write_bytes(source_bytes);gis.reload_source(force=True);app.update();assert gis.store
            # A different project cannot retain any previous-project snapshot.
            original_store=app.store;other=code['Store'](Path(temp)/'other-project.sqlite3')
            try:
                set_stage(other,'after');app.store=other;app.update_title();app.refresh()
                for dialog in viewers.values():
                    poll(dialog);app.update();assert dialog.store is None and not dialog._reference_details
            finally:
                app.store=original_store;other.close();app.update_title();app.refresh()
                for dialog in viewers.values():poll(dialog)
                app.update()
            for kind,dialog in viewers.items():
                assert dialog.source_kind==kind and dialog.store.core(left,3)['core_id']==kind.upper()+'-ID'
            # Closing one stage leaves the other windows usable; timer and DB
            # lifetime belong to the stage that opened them.
            child=wf.open_reference_detail(gis,'cable',left);app.update()
            watcher=gis._poll_job;connection=gis.store.conn;temp_path=Path(gis.reference_snapshot.temp.name)
            gis.tk.call(gis.protocol('WM_DELETE_WINDOW'));pump(app)
            assert not gis.winfo_exists() and not child.winfo_exists() and gis._poll_job is None
            assert 'gis' not in app._reference_drawings and field.winfo_exists() and after.winfo_exists()
            assert watcher not in app.tk.splitlist(app.tk.call('after','info')) and not temp_path.exists()
            with unittest.TestCase().assertRaises(sqlite3.ProgrammingError):connection.execute('SELECT 1')
            remaining=[(d,d.store.conn,Path(d.reference_snapshot.temp.name),d._poll_job) for d in (field,after)]
            wf.close_reference_drawings(app);app.update()
            for dialog,connection,path,watcher in remaining:
                assert not dialog.winfo_exists() and not path.exists()
                assert watcher not in app.tk.splitlist(app.tk.call('after','info'))
                with unittest.TestCase().assertRaises(sqlite3.ProgrammingError):connection.execute('SELECT 1')
            assert not app._reference_drawings and app.grab_current() is None
            assert not errors,errors
            assert not error.called,error.call_args
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows pinned stage windows: three modeless drawings, stage titles/colors, independent full canvases, separate exact-peer details, scoped shortcuts, unchanged sources/drafts, pinned stage/project reload and owned cleanup')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SnapshotTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
