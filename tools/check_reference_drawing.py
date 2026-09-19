"""Previous-stage reference: isolated reads and real modeless Windows navigation."""
import faulthandler
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
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
    a,h,b,left,right=ids;number=7 if kind=='gis' else 4
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
            for row in rows.values():
                self.assertIn('현장 재확인',row['state']);self.assertIn('SYNTH 공통 메모',row['state'])
            self.assertEqual(wf.stage_database_token(snapshot.store.conn),before)
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


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(150,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(wf.messagebox,'showinfo'),patch.object(wf.messagebox,'showwarning'), \
         patch.object(wf.messagebox,'showerror') as error,patch.object(wf.messagebox,'askyesno',return_value=True), \
         patch.object(wf.messagebox,'askyesnocancel',return_value=False):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            s=app.store;ids=fixture(s);a,h,b,left,right=ids
            for kind in ('gis','before','after'):save_stage(s,app.scenario_path(kind),kind,ids)
            wf.stage_restore_store(s,app.scenario_path('before'));app.scenario_saved_revision=s.data_revision()
            app.geometry('1180x760+0+0');app.refresh();app.update()
            config=dict(app.drawing_tools.config,enabled=app.drawing_tools.config['enabled']+['reference_drawing'])
            app.drawing_tools.apply(config);app.update()
            baseline=wf.stage_state_token(app);previous_grab=app.grab_current()
            app.drawing_tools.buttons['reference_drawing'].invoke();app.update();dialog=app._reference_drawing
            assert dialog and dialog.winfo_exists() and dialog.grab_current() is previous_grab is None
            assert dialog.source_kind=='gis' and Path(dialog.source_path)==app.scenario_path('gis')
            assert dialog.store is not s and dialog.reference_snapshot.store is dialog.store
            assert wf.open_reference_drawing(app) is dialog
            app.drawing_tools.buttons['reference_drawing'].invoke();app.update()
            assert len([w for w in app.winfo_children() if isinstance(w,wf.ReferenceDrawingDialog)])==1
            assert wf.stage_state_token(app)==baseline
            dialog.geometry('1100x720+90+30');app.update();dialog.fit_view();app.update()
            print('REFERENCE: real toolbar, reusable modeless GIS source, exact saved peers and copy',flush=True)
            dialog.follow_selection.set(False);dialog.select_item('node',h,center=True);app.update()
            displayed=tree_text(dialog.core_tree)
            assert 'GIS-ID' in displayed and 'SYNTH gis service' in displayed
            assert 'SYNTH-LEFT' in displayed and 'SYNTH-RIGHT' in displayed
            assert 'BEFORE-ID' not in displayed and 'AFTER-ID' not in displayed
            rows=dialog.core_tree.get_children();assert rows
            populated=next(row for row in rows if dialog.core_tree.set(row,'cable')=='SYNTH-LEFT' and dialog.core_tree.set(row,'number')=='3번')
            assert 'SYNTH-RIGHT / 7번' in dialog.core_tree.set(populated,'end')
            assert dialog.core_tree.set(populated,'signal').upper()=='ON'
            dialog.core_tree.selection_set(populated);key(app,dialog.core_tree,'<Control-c>')
            assert 'GIS-ID' in app.clipboard_get()
            dialog.find_text.set('GIS-ID');dialog.find_next();app.update()
            assert dialog.core_tree.get_children() and dialog.canvas.find_all()
            key(app,dialog.canvas,'<Control-f>');assert app.focus_get() is dialog.find_entry
            assert not getattr(app,'find_dialog',None)
            with patch.object(wf,'DrawingSaveDialog',side_effect=AssertionError('Reference Ctrl+S escaped to drawing save')):
                for widget in (dialog.canvas,dialog.core_tree,dialog.find_entry):
                    for sequence in ('<Control-s>','<Control-z>','<Control-y>'):key(app,widget,sequence)
            assert not errors,errors
            assert wf.stage_state_token(app)==baseline and not getattr(app,'_save_dialog',None)
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True);dialog.select_item('node',h,center=True);app.update()
                screenshot(dialog,Path('dist')/'v118-reference-drawing.png')
            # Normal text copy must remain scoped to the entry, not the ledger.
            dialog.find_text.set('copy this text');dialog.find_entry.selection_range(0,4)
            key(app,dialog.find_entry,'<Control-c>');assert app.clipboard_get()=='copy'
            # Main right-drag panning and actual editing remain available.
            app.canvas.xview_moveto(.15);old_view=app.canvas.xview();drawing=wf.stage_database_token(s.conn)
            app.canvas.event_generate('<ButtonPress-3>',x=500,y=80)
            app.canvas.event_generate('<B3-Motion>',x=370,y=80)
            app.canvas.event_generate('<ButtonRelease-3>',x=370,y=80);app.update()
            assert app.canvas.xview()!=old_view and dialog.winfo_exists()
            assert wf.stage_database_token(s.conn)==drawing
            app.set_mode('hamche');count=len(s.nodes())
            app.canvas.event_generate('<ButtonPress-1>',x=70,y=70)
            app.canvas.event_generate('<ButtonRelease-1>',x=70,y=70);app.update()
            assert len(s.nodes())==count+1 and dialog.winfo_exists()
            key(app,app.canvas,'<Control-z>');assert len(s.nodes())==count
            # Opening, navigation, reload and source refresh preserve a dirty
            # real cable header and do not capture it into either drawing.
            editor=code['CableDialog'](app,s,left);app.update();editor.lot_var.set('Uncommitted LOT draft')
            baseline=wf.stage_state_token(app);dialog.reload_source(force=True);app.update()
            assert editor.lot_var.get()=='Uncommitted LOT draft' and wf.stage_state_token(app)==baseline
            dialog.follow_selection.set(True);app.selected={right};pump(app)
            assert dialog.selected_item==('cable',right)
            assert 'GIS-ID' in tree_text(dialog.core_tree)
            dialog.follow_selection.set(False);app.selected={a};poll(dialog);app.update()
            assert dialog.selected_item==('cable',right)
            editor.destroy();app.update()
            print('REFERENCE: stage/project changes, missing source, source reload, geometry and cleanup',flush=True)
            geometry=dialog.geometry();old_snapshot=dialog.reference_snapshot;old_connection=old_snapshot.store.conn
            # Source switching is independent of the already-covered field
            # handoff validator; use the real stage button with its gate accepted.
            with patch.object(app,'field_ready_for_after',return_value=True):app.workflow_buttons['after'].invoke()
            app.update();poll(dialog);app.update()
            assert app.scenario_kind()=='after' and app._reference_drawing is dialog
            assert dialog.source_kind=='before' and dialog.geometry()==geometry
            dialog.select_item('cable',left,center=True);app.update()
            assert 'BEFORE-ID' in tree_text(dialog.core_tree) and 'GIS-ID' not in tree_text(dialog.core_tree)
            assert dialog.store.component((left,3))=={(left,3),(right,4)}
            with unittest.TestCase().assertRaises(sqlite3.ProgrammingError):old_connection.execute('SELECT 1')
            source=app.scenario_path('before');source_bytes=source.read_bytes();source.unlink()
            baseline=wf.stage_state_token(app);poll(dialog);app.update()
            assert dialog.store is None and not dialog.core_tree.get_children()
            assert wf.stage_state_token(app)==baseline and not source.exists()
            source.write_bytes(source_bytes);dialog.reload_source(force=True);app.update();assert dialog.store
            assert app.load_scenario('gis');app.update();poll(dialog);app.update()
            assert dialog.source_kind is None and dialog.store is None and not dialog.core_tree.get_children()
            assert dialog.geometry()==geometry and app._reference_drawing is dialog
            assert app.load_scenario('before');app.update();poll(dialog);app.update()
            assert dialog.source_kind=='gis' and dialog.store.core(left,3)['core_id']=='GIS-ID'
            # A different project must not keep showing the previous project's
            # saved GIS, even when the active stage name is unchanged.
            original_store=app.store;other=code['Store'](Path(temp)/'other-project.sqlite3')
            try:
                set_stage(other,'before');app.store=other;app.refresh();poll(dialog);app.update()
                assert dialog.store is None and not dialog.core_tree.get_children()
            finally:app.store=original_store;other.close();app.refresh();poll(dialog);app.update()
            assert dialog.store and dialog.store.core(left,3)['core_id']=='GIS-ID'
            watcher=dialog._poll_job;connection=dialog.store.conn
            dialog.tk.call(dialog.protocol('WM_DELETE_WINDOW'));pump(app)
            assert not dialog.winfo_exists() and dialog._poll_job is None
            assert app._reference_drawing is None
            assert watcher not in app.tk.splitlist(app.tk.call('after','info'))
            with unittest.TestCase().assertRaises(sqlite3.ProgrammingError):connection.execute('SELECT 1')
            assert app.grab_current() is None and not errors,errors
            assert not error.called,error.call_args
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows previous-stage reference: modeless singleton, exact peers, copy/search, live source, stage/project switches, drafts, scoped shortcuts, main panning/editing and timer cleanup')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(SnapshotTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
