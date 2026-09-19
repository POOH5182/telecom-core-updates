"""Reference cable IDs and physical paths: visible mouse/keyboard regressions."""
import faulthandler
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from check_reference_drawing import code,wf,key,pump,populated_row,set_stage


STAGE_NUMBERS={'gis':(7,11),'before':(4,8),'after':(9,6)}
CORE_ID='SYNTH-CORE-ID-120-ABCDEFGHIJKL'
OTHER_ID='SYNTH-DIFFERENT-ID'


def trace_fixture(store):
    nodes=[store.add_node(name,x,y) for name,x,y in (
        ('SYNTH 시작',1000,600),('SYNTH 함체 1',1350,600),
        ('SYNTH 함체 2',1700,600),('SYNTH 끝',2050,600),
        ('SYNTH 별도 시작',1350,1050),('SYNTH 별도 끝',1700,1050))]
    cables=[store.add_cable(nodes[a],nodes[b],name,'12C','기설') for a,b,name in (
        (0,1,'SYNTH-LEFT'),(1,2,'SYNTH-MIDDLE'),(2,3,'SYNTH-RIGHT'),
        (4,5,'SYNTH-DISCONNECTED'))]
    return nodes,cables


def save_trace_stage(store,path,kind,fixture):
    nodes,cables=fixture;left,middle,right,detached=cables
    middle_number,right_number=STAGE_NUMBERS[kind]
    set_stage(store,kind)
    # Use a real action so history triggers remain active. This explicit layout
    # edit also suppresses automatic ID joins while installing intentional gaps.
    with store.action('후도면 선번 연결도 변경'):
        store.conn.execute('DELETE FROM splices')
        store.conn.execute("UPDATE cores SET core_id='',detail='',signal=''")
        for cable,index,identity in ((left,3,CORE_ID),(left,5,CORE_ID),
                                     (left,6,'임시-17'),
                                     (middle,middle_number,''),(right,right_number,OTHER_ID),
                                     (detached,1,CORE_ID)):
            store.conn.execute('UPDATE cores SET core_id=?,detail=?,signal=? WHERE cable_id=? AND core_index=?',
                               (identity,'SYNTH '+kind+' 내역','on',cable,index))
        for node,a,b in ((nodes[1],(left,3),(middle,middle_number)),
                         (nodes[2],(middle,middle_number),(right,right_number))):
            a,b=sorted((a,b))
            store.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(node,*a,*b))
    wf.save_annotations(store,(left,3),['현장 재확인'],'SYNTH 긴 메모 '+('확인 기록 / '*18))
    expected={(left,3),(middle,middle_number),(right,right_number)}
    assert store.component((left,3))==expected
    store.backup_to(path)
    return expected


class ReferenceTraceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.store=code['Store'](self.home/'working.sqlite3');self.fixture=trace_fixture(self.store)

    def tearDown(self):self.store.close();self.temp.cleanup()

    def test_same_clicked_number_traces_each_saved_stage_without_identity_guessing(self):
        left,middle,right,detached=self.fixture[1]
        snapshots=[];sources={}
        try:
            for kind in STAGE_NUMBERS:
                path=self.home/(kind+'.sqlite3')
                expected=save_trace_stage(self.store,path,kind,self.fixture)
                sources[path]=path.read_bytes()
                snapshots.append((kind,wf.ReferenceSnapshot(code['Store'],path),expected))
            for kind,snapshot,expected in snapshots:
                token=wf.stage_database_token(snapshot.store.conn)
                rows=wf.reference_detail_rows(snapshot.store,'route',(left,3))
                self.assertEqual({row['slot'] for row in rows},expected)
                self.assertEqual({row['values'][2] for row in rows},{CORE_ID,'',OTHER_ID})
                self.assertNotIn((left,5),expected);self.assertNotIn((detached,1),expected)
                self.assertEqual(wf.stage_database_token(snapshot.store.conn),token)
            for path,content in sources.items():self.assertEqual(path.read_bytes(),content)
        finally:
            for kind,snapshot,expected in snapshots:snapshot.close()

    def test_ids_and_long_shared_memo_are_independent_display_values(self):
        left=self.fixture[1][0];path=self.home/'gis.sqlite3'
        save_trace_stage(self.store,path,'gis',self.fixture)
        snapshot=wf.ReferenceSnapshot(code['Store'],path)
        try:
            token=wf.stage_database_token(snapshot.store.conn)
            rows={r['slot']:dict(zip(wf.REFERENCE_COLUMNS,r['values']))
                  for r in wf.reference_detail_rows(snapshot.store,'cable',left)}
            self.assertEqual(rows[left,3]['core_id'],CORE_ID)
            self.assertEqual(rows[left,5]['core_id'],CORE_ID)
            self.assertIn('긴 메모',rows[left,3]['state'])
            self.assertGreater(len(rows[left,3]['state']),150)
            self.assertIn('7번',rows[left,3]['end'])
            self.assertIn('미접속',rows[left,5]['end'])
            self.assertEqual(wf.stage_database_token(snapshot.store.conn),token)
        finally:snapshot.close()

    def test_highlight_follows_physical_transit_and_never_adds_same_id_gaps(self):
        left,middle,right,detached=self.fixture[1];path=self.home/'gis.sqlite3'
        expected=save_trace_stage(self.store,path,'gis',self.fixture)
        snapshot=wf.ReferenceSnapshot(code['Store'],path)
        try:
            source=path.read_bytes();token=wf.stage_database_token(snapshot.store.conn)
            model=wf.reference_slot_highlight(snapshot.store,[(left,3)])
            self.assertEqual(set(model['slots']),expected)
            self.assertEqual(set(model['colors']),{left,middle,right})
            self.assertEqual(set(model['labels']),{left,middle,right})
            self.assertIn(CORE_ID,'\n'.join(model['labels'].values()))
            self.assertIn(OTHER_ID,'\n'.join(model['labels'].values()))
            for cable,number in expected:self.assertIn(str(number),model['labels'][cable])
            isolated=wf.reference_slot_highlight(snapshot.store,[(left,5)])
            self.assertEqual(set(isolated['slots']),{(left,5)})
            self.assertEqual(set(isolated['colors']),{left})
            combined=wf.reference_slot_highlight(snapshot.store,[(left,3),(left,5),(detached,1),(left,3)])
            self.assertEqual(set(combined['slots']),expected|{(left,5),(detached,1)})
            self.assertEqual(len(combined['groups']),3)
            self.assertEqual(wf.stage_database_token(snapshot.store.conn),token)
            self.assertEqual(path.read_bytes(),source)
        finally:snapshot.close()

    def test_read_created_empty_wal_does_not_invalidate_open_details_but_real_edits_do(self):
        path=self.home/'gis.sqlite3';left=self.fixture[1][0]
        save_trace_stage(self.store,path,'gis',self.fixture)
        fake=SimpleNamespace(source_kind='gis',app=SimpleNamespace(store=self.store,scenario_path=lambda kind:path))
        token=lambda:wf.ReferenceDrawingDialog._token(fake)
        before=token();content=path.read_bytes()
        snapshot=wf.ReferenceSnapshot(code['Store'],path)
        try:
            # Opening this WAL-mode saved drawing read-only can create empty
            # SQLite sidecars. That is not a changed drawing and must not close
            # the cable detail at the next 700ms source watcher tick.
            self.assertEqual(token(),before)
            self.assertEqual(path.read_bytes(),content)
            writer=code['Store'](path)
            try:
                with writer.action('Synthetic saved-stage detail change'):
                    writer.conn.execute("UPDATE cores SET detail='SYNTH changed saved source' WHERE cable_id=? AND core_index=3",(left,))
                self.assertNotEqual(token(),before)
            finally:writer.close()
            self.assertNotEqual(token(),before)
        finally:snapshot.close()


def click_id(app,dialog,slot):
    """A user clicks the actual visible ID cell; no selection helper bypass."""
    tree,iid=populated_row(dialog,*slot)
    dialog.deiconify();dialog.lift();tree.see(iid);tree.xview_moveto(0);app.update()
    bounds=tree.bbox(iid,'core_id')
    assert bounds,('Core ID cell not mapped',slot)
    x,y,width,height=bounds
    assert width>30 and x>=0 and x+min(width,80)<tree.winfo_width(),(bounds,tree.winfo_width())
    tree.focus_force();tree.event_generate('<ButtonPress-1>',x=x+min(width//2,60),y=y+height//2)
    tree.event_generate('<ButtonRelease-1>',x=x+min(width//2,60),y=y+height//2);app.update()
    assert iid in tree.selection(),(slot,tree.selection())
    assert CORE_ID in dialog.selection_text.get() or slot[1]!=3,dialog.selection_text.get()
    return tree,iid


def canvas_text(view):
    return '\n'.join(view.canvas.itemcget(item,'text') for item in view.canvas.find_all()
                     if view.canvas.type(item)=='text')


def assert_route(view,expected):
    owners={owner for owner,index in expected if not owner.startswith('PORT:')}
    assert view.highlight_cables==owners,(view.highlight_cables,owners)
    assert set(view.highlight_connection_model['slots'])==expected
    visible=canvas_text(view)
    for owner,index in expected:
        assert str(index) in visible,(index,visible)
    assert CORE_ID in visible,visible
    assert view.canvas.find_withtag('core_path_number'),'No visible route labels'


def window_state(view):
    return (view.selected_item,view.view_scale,view.canvas.xview(),view.canvas.yview(),
            frozenset(view.highlight_cables),dict(view.highlight_core_labels))


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(180,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(wf.messagebox,'showinfo'),patch.object(wf.messagebox,'showwarning'), \
         patch.object(wf.messagebox,'showerror') as errors_popup, \
         patch.object(wf.messagebox,'askyesno',return_value=True), \
         patch.object(wf.messagebox,'askyesnocancel',return_value=False):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            store=app.store;fixture=trace_fixture(store);nodes,cables=fixture
            left,middle,right,detached=cables;expected={}
            for kind in STAGE_NUMBERS:
                expected[kind]=save_trace_stage(store,app.scenario_path(kind),kind,fixture)
            wf.stage_restore_store(store,app.scenario_path('before'))
            app.scenario_saved_revision=store.data_revision();app.geometry('960x700+10+10');app.refresh();app.update()
            viewers={kind:wf.open_reference_drawing(app,kind) for kind in STAGE_NUMBERS}
            for view in viewers.values():
                view.geometry('960x680+10+10');view.toggle_dashboard();view.fit_view()
            app.update()
            baseline=wf.stage_state_token(app)
            saved={kind:app.scenario_path(kind).read_bytes() for kind in STAGE_NUMBERS}
            private={kind:wf.stage_database_token(view.store.conn) for kind,view in viewers.items()}
            main=(frozenset(app.selected),frozenset(app.highlight_cables),app.highlight_blink_job,
                  app.view_scale,app.canvas.xview(),app.canvas.yview())
            details={}
            for kind,view in viewers.items():
                others={name:window_state(other) for name,other in viewers.items() if name!=kind}
                detail=wf.open_reference_detail(view,'cable',left);details[kind]=detail
                detail.geometry('780x600+10+10');app.update()
                tree,iid=click_id(app,detail,(left,3))
                assert tree.set(iid,'core_id')==CORE_ID
                assert CORE_ID in detail.selection_text.get()
                assert_route(view,expected[kind])
                for name,state in others.items():assert window_state(viewers[name])==state
                assert main==(frozenset(app.selected),frozenset(app.highlight_cables),app.highlight_blink_job,
                              app.view_scale,app.canvas.xview(),app.canvas.yview())
                key(app,tree,'<Control-c>');assert CORE_ID in app.clipboard_get()
                detail.copy_selected(column='core_id');assert app.clipboard_get()==CORE_ID
                detail.find_text.set('copy this text');detail.find_entry.selection_range(0,4)
                key(app,detail.find_entry,'<Control-c>');assert app.clipboard_get()=='copy'
                detail.find_next(direction=0)  # Consume its debounce before the next mouse action.
                # Real sorted-heading command, then another physical cell click.
                tree.tk.call(tree.heading('number','command'));app.update()
                tree.tk.call(tree.heading('number','command'));app.update()
                click_id(app,detail,(left,3));assert_route(view,expected[kind])
                key(app,tree,'<Control-f>');assert app.focus_get() is detail.find_entry
                detail.find_text.set(CORE_ID);key(app,detail.find_entry,'<Return>')
                assert detail.row_map[tree][tree.selection()[0]]['slot']==(left,3)
                assert_route(view,expected[kind])
                key(app,detail.find_entry,'<Return>')
                assert detail.row_map[tree][tree.selection()[0]]['slot']==(left,5)
                assert view.highlight_cables=={left},'An isolated same-ID row must not highlight its sibling route'
                click_id(app,detail,(left,3));route=detail.open_route();app.update()
                assert {r['slot'] for r in route.rows}==expected[kind]
                route.destroy();app.update()
                click_id(app,detail,(left,3));detail.show_on_drawing();app.update()
                assert_route(view,expected[kind])
            assert not errors,errors
            print('REFERENCE TRACE: real core-ID clicks, narrow/long-memo readability, sorted rows, clipboard and Ctrl+F on GIS/field/after',flush=True)
            gis=viewers['gis'];detail=details['gis']
            # The smaller two-pane enclosure view keeps IDs reachable as well.
            node_detail=wf.open_reference_detail(gis,'node',nodes[1])
            node_detail.geometry('780x600+10+10');app.update()
            click_id(app,node_detail,(left,3));assert_route(gis,expected['gis'])
            key(app,node_detail.active_tree,'<Control-f>')
            node_detail.find_text.set('임시코어17');key(app,node_detail.find_entry,'<Return>')
            temp_tree,temp_iid=populated_row(node_detail,left,6)
            assert temp_iid in temp_tree.selection()
            assert temp_tree.set(temp_iid,'core_id')=='임시코어17'
            node_detail.copy_selected(column='core_id');assert app.clipboard_get()=='임시-17'
            assert set(gis.highlight_connection_model['slots'])=={(left,6)}
            node_detail.destroy();app.update()
            click_id(app,detail,(left,3));assert_route(gis,expected['gis'])
            old_job=gis.highlight_blink_job
            assert old_job in app.tk.splitlist(app.tk.call('after','info'))
            before_blink=gis.highlight_blink_on
            for attempt in range(8):
                pump(app,80)
                if gis.highlight_blink_on!=before_blink:break
            assert gis.highlight_blink_on!=before_blink,'Selected physical path is not blinking'
            # A newer detail owns its route; closing the old cable must leave it.
            newer=wf.open_reference_detail(gis,'cable',right);newer.geometry('780x600+10+10');app.update()
            click_id(app,newer,(right,STAGE_NUMBERS['gis'][1]));assert_route(gis,expected['gis'])
            detail.destroy();app.update();assert_route(gis,expected['gis'])
            owned_job=gis.highlight_blink_job
            key(app,newer.tree,'<Escape>');app.update()
            assert not newer.winfo_exists() and not gis.highlight_cables
            assert gis.highlight_blink_job is None and not gis.canvas.find_withtag('core_path_number')
            assert owned_job not in app.tk.splitlist(app.tk.call('after','info'))
            # Drawing-wide ID search may show all disconnected occurrences but
            # must also include their physically connected blank/different IDs.
            gis.find_text.set(CORE_ID);gis.find_next();app.update()
            assert gis.highlight_cables==set(cables)
            assert CORE_ID in canvas_text(gis)
            job=gis.highlight_blink_job;key(app,gis.canvas,'<Escape>')
            assert not gis.highlight_cables and gis.highlight_blink_job is None
            assert job not in app.tk.splitlist(app.tk.call('after','info'))
            # Save/reload closes descendants and their timers before old data dies.
            detail=wf.open_reference_detail(gis,'cable',left);detail.geometry('780x600+10+10');app.update()
            click_id(app,detail,(left,3));job=gis.highlight_blink_job
            gis.reload_source(force=True);app.update()
            assert not detail.winfo_exists() and not gis.highlight_cables and gis.highlight_blink_job is None
            assert job not in app.tk.splitlist(app.tk.call('after','info'))
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True)
                detail=wf.open_reference_detail(gis,'cable',left);detail.geometry('960x620+10+10');app.update()
                click_id(app,detail,(left,3));detail.show_on_drawing();gis.geometry('960x680+10+10');app.update()
                screenshot(gis,Path('dist')/'v120-reference-core-route.png')
                screenshot(detail,Path('dist')/'v120-reference-core-id.png')
            for kind,view in viewers.items():
                assert wf.stage_database_token(view.store.conn)==private[kind]
                assert app.scenario_path(kind).read_bytes()==saved[kind]
            assert wf.stage_state_token(app)==baseline
            jobs=[v.highlight_blink_job for v in viewers.values() if v.highlight_blink_job is not None]
            wf.close_reference_drawings(app);pump(app,400)
            pending=app.tk.splitlist(app.tk.call('after','info'))
            assert all(job not in pending for job in jobs)
            assert all(v.highlight_blink_job is None for v in viewers.values())
            assert not errors,errors
            assert not errors_popup.called,errors_popup.call_args
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows reference core trace: visible IDs, actual sorted clicks/search/clipboard, stage-specific physical paths, neutral and mismatched transit, disconnected negatives, viewer/main isolation and owned timer/source cleanup')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReferenceTraceTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
