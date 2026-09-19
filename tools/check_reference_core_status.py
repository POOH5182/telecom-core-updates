"""Reference cable completion/signal panel: saved-stage truth and native selection."""
import faulthandler
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from check_reference_core_trace import (
    code,wf,key,STAGE_NUMBERS,CORE_ID,trace_fixture,save_trace_stage,
    click_id,window_state,
)


STAGE_SIGNALS={'gis':('on','off','off'),'before':('off','off','off'),
               'after':('unknown','on','on')}
PANEL_VALUES=('completion_title','completion_reason','completion_signal','completion_signal_detail')


def save_status_stage(store,path,kind,fixture):
    route=save_trace_stage(store,path,kind,fixture)
    left,middle,right,detached=fixture[1]
    with store.action('후도면 선번 연결도 변경'):
        for slot,signal in zip(((left,3),(left,5),(detached,1)),STAGE_SIGNALS[kind]):
            store.conn.execute('UPDATE cores SET signal=? WHERE cable_id=? AND core_index=?',(signal,*slot))
        store.conn.execute("UPDATE cores SET signal='off' WHERE cable_id=? AND core_index=4",(left,))
    store.backup_to(path)
    return route


class ReferenceStatusTests(unittest.TestCase):
    def test_identical_ids_have_independent_saved_signal_counts_and_read_only_reasons(self):
        with tempfile.TemporaryDirectory() as temp:
            home=Path(temp);store=code['Store'](home/'working.sqlite3');snapshots=[]
            try:
                fixture=trace_fixture(store);left=fixture[1][0];sources={}
                for kind in STAGE_NUMBERS:
                    path=home/(kind+'.sqlite3');save_status_stage(store,path,kind,fixture)
                    sources[path]=path.read_bytes()
                    snapshots.append((kind,wf.ReferenceSnapshot(code['Store'],path)))
                working=wf.stage_database_token(store.conn)
                for kind,snapshot in snapshots:
                    before=wf.stage_database_token(snapshot.store.conn)
                    signal=wf.core_id_signal_summary(snapshot.store,(left,3))
                    expected={value:STAGE_SIGNALS[kind].count(value) for value in set(STAGE_SIGNALS[kind])}
                    self.assertEqual(signal['core_id'],CORE_ID)
                    self.assertEqual(signal['counts'],expected)
                    self.assertEqual(signal['signal'],{'gis':'mixed','before':'off','after':'on'}[kind])
                    self.assertEqual(signal['local_signal'],STAGE_SIGNALS[kind][0])
                    # A blank ID is local even though other anonymous slots have
                    # ON and unknown signals elsewhere in the same snapshot.
                    anonymous=wf.core_id_signal_summary(snapshot.store,(left,4))
                    self.assertEqual(anonymous['counts'],{'off':1})
                    self.assertEqual(anonymous['core_id'],'')
                    self.assertEqual(anonymous['total'],1)
                    for slot in ((left,3),(left,4),(left,5),(left,6)):
                        self.assertTrue(wf.core_completion_brief(snapshot.store,slot)[0])
                        self.assertIsInstance(wf.core_completion_locations(snapshot.store,slot),str)
                    self.assertEqual(wf.stage_database_token(snapshot.store.conn),before)
                self.assertEqual(wf.stage_database_token(store.conn),working)
                for path,content in sources.items():self.assertEqual(path.read_bytes(),content)
            finally:
                for kind,snapshot in snapshots:snapshot.close()
                store.close()


def panel_values(dialog):
    return tuple(getattr(dialog,name).get() for name in PANEL_VALUES)


def assert_panel(dialog,slot,multiple=1):
    status,reason=wf.core_completion_brief(dialog.store,slot)
    signal=wf.core_id_signal_summary(dialog.store,slot)
    title=dialog.completion_title.get()
    assert title.startswith(f'{slot[1]} · {status}'),(slot,title,status)
    if multiple>1:assert str(multiple) in title,title
    assert dialog.completion_reason.get()==(reason or status)
    prefix='전체 신호: ' if signal['core_id'] else '선택 번호 신호: '
    assert dialog.completion_signal.get()==prefix+signal['label']
    assert dialog.completion_signal_detail.get()==signal['detail']
    assert not dialog.completion_details_button.instate(['disabled'])
    expected_color={'on':'#d00000','off':'#475569','mixed':'#c62828',
                    'error':'#c62828','exception':'#1769aa'}.get(signal['signal'],'#666666')
    assert str(dialog.completion_signal_label.cget('foreground'))==expected_color


def assert_empty_panel(dialog):
    assert panel_values(dialog)==('선택 코어 · 미완료 이유','코어를 선택하세요.','',''),panel_values(dialog)
    assert dialog.completion_details_button.instate(['disabled'])


def assert_inside(widget,parent):
    assert widget.winfo_ismapped(),str(widget)
    wx,wy=widget.winfo_rootx(),widget.winfo_rooty()
    px,py=parent.winfo_rootx(),parent.winfo_rooty()
    assert px<=wx and py<=wy,(str(widget),'outside top/left')
    assert wx+widget.winfo_width()<=px+parent.winfo_width()+1,(str(widget),'clipped right')
    assert wy+widget.winfo_height()<=py+parent.winfo_height()+1,(str(widget),'clipped bottom')


def assert_panel_layout(dialog):
    box=dialog.completion_box;fields=dialog.header_fields;header=dialog.header_frame
    assert_inside(header,dialog);assert_inside(fields,header);assert_inside(box,header)
    assert box.winfo_rootx()>=fields.winfo_rootx()+fields.winfo_width(), 'Panel must be beside cable fields at the upper right'
    assert abs(box.winfo_rooty()-fields.winfo_rooty())<20
    for widget in (dialog.completion_title_label,dialog.completion_reason_label,dialog.completion_signal_label,
                   dialog.completion_signal_detail_label,dialog.completion_details_button):
        assert_inside(widget,box)
    assert dialog.tree.winfo_height()>=80,('Table lost its usable rows',dialog.tree.winfo_height())
    assert_inside(dialog.tree,dialog)


def windows_ui():
    if sys.platform!='win32':return
    faulthandler.dump_traceback_later(180,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp), \
         patch.object(wf.messagebox,'showinfo') as info,patch.object(wf.messagebox,'showwarning'), \
         patch.object(wf.messagebox,'showerror') as error_popup, \
         patch.object(wf.messagebox,'askyesno',return_value=True), \
         patch.object(wf.messagebox,'askyesnocancel',return_value=False):
        app=code['App']();errors=[];app.report_callback_exception=lambda *args:errors.append(args)
        try:
            store=app.store;fixture=trace_fixture(store);left,middle,right,detached=fixture[1]
            routes={kind:save_status_stage(store,app.scenario_path(kind),kind,fixture) for kind in STAGE_NUMBERS}
            wf.stage_restore_store(store,app.scenario_path('before'))
            app.scenario_saved_revision=store.data_revision();app.geometry('960x700+10+10');app.refresh();app.update()
            viewers={kind:wf.open_reference_drawing(app,kind) for kind in STAGE_NUMBERS}
            for view in viewers.values():
                view.geometry('960x680+10+10');view.toggle_dashboard();view.fit_view()
            app.update()
            baseline=wf.stage_state_token(app)
            sources={kind:app.scenario_path(kind).read_bytes() for kind in STAGE_NUMBERS}
            private={kind:wf.stage_database_token(view.store.conn) for kind,view in viewers.items()}
            main=(frozenset(app.selected),frozenset(app.highlight_cables),app.highlight_blink_job,
                  app.view_scale,app.canvas.xview(),app.canvas.yview())
            details={}
            for kind,view in viewers.items():
                others={name:window_state(other) for name,other in viewers.items() if name!=kind}
                previous={name:panel_values(detail) for name,detail in details.items()}
                detail=wf.open_reference_detail(view,'cable',left);details[kind]=detail
                detail.geometry('780x600+10+10');app.update();assert_empty_panel(detail)
                tree,iid=click_id(app,detail,(left,3));assert_panel(detail,(left,3));assert_panel_layout(detail)
                assert set(view.highlight_connection_model['slots'])==routes[kind]
                assert wf.core_id_signal_summary(detail.store,(left,3))['signal']=={'gis':'mixed','before':'off','after':'on'}[kind]
                for name,state in others.items():assert window_state(viewers[name])==state
                for name,state in previous.items():assert panel_values(details[name])==state
                assert main==(frozenset(app.selected),frozenset(app.highlight_cables),app.highlight_blink_job,
                              app.view_scale,app.canvas.xview(),app.canvas.yview())
                # The read-only drill-down must use this snapshot and this window.
                info.reset_mock();detail.completion_details_button.invoke();app.update()
                args,kwargs=info.call_args
                assert args[1]==wf.core_completion_locations(view.store,(left,3))
                assert '3번' in args[0] and wf.core_completion_brief(view.store,(left,3))[0] in args[0]
                assert kwargs.get('parent') is detail
                # Sorting changes visual order, never the selected physical slot.
                tree.tk.call(tree.heading('number','command'));app.update()
                click_id(app,detail,(left,4));assert_panel(detail,(left,4));assert_panel_layout(detail)
                assert detail.completion_signal.get()=='선택 번호 신호: OFF'
                key(app,tree,'<Control-f>');assert app.focus_get() is detail.find_entry
                detail.find_text.set(CORE_ID);key(app,detail.find_entry,'<Return>');assert_panel(detail,(left,3))
                key(app,detail.find_entry,'<Return>');assert_panel(detail,(left,5))
                assert set(view.highlight_connection_model['slots'])=={(left,5)}
                detail.copy_selected(column='core_id');assert app.clipboard_get()==CORE_ID
                detail.find_entry.selection_range(0,5);key(app,detail.find_entry,'<Control-c>')
                assert app.clipboard_get()==CORE_ID[:5]
                click_id(app,detail,(left,6));assert_panel(detail,(left,6))
                detail.copy_selected(column='core_id');assert app.clipboard_get()=='임시-17'
                key(app,tree,'<Control-a>')
                selected=tree.selection();slot=detail.row_map[tree][selected[0]]['slot']
                assert len(selected)==12;assert_panel(detail,slot,multiple=12)
                tree.selection_remove(*selected);app.update();assert_empty_panel(detail)
                assert not view.highlight_cables and view.highlight_blink_job is None
                click_id(app,detail,(left,3));detail.geometry('960x680+10+10');app.update()
                assert_panel(detail,(left,3));assert_panel_layout(detail)
            print('REFERENCE STATUS: actual clicks, sort, Ctrl+F, multi/empty selections, full and local signals, reasons and native copy on three saved stages',flush=True)
            gis=viewers['gis'];old=details['gis'];old_values=panel_values(old)
            newer=wf.open_reference_detail(gis,'cable',right);newer.geometry('780x600+10+10');app.update()
            click_id(app,newer,(right,STAGE_NUMBERS['gis'][1]));assert_panel(newer,(right,STAGE_NUMBERS['gis'][1]))
            assert panel_values(old)==old_values
            old.destroy();app.update()
            assert gis.highlight_owner is newer and set(gis.highlight_connection_model['slots'])==routes['gis']
            newer.destroy();app.update();assert gis.highlight_blink_job is None
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True)
                detail=wf.open_reference_detail(gis,'cable',left);detail.geometry('960x680+10+10');app.update()
                click_id(app,detail,(left,3));assert_panel_layout(detail)
                screenshot(detail,Path('dist')/'v121-reference-core-status.png')
            for kind,view in viewers.items():
                assert wf.stage_database_token(view.store.conn)==private[kind]
                assert app.scenario_path(kind).read_bytes()==sources[kind]
            assert wf.stage_state_token(app)==baseline
            wf.close_reference_drawings(app);app.update()
            assert not errors,errors
            assert not error_popup.called,error_popup.call_args
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows reference core status: upper-right readable completion/signal panel, source-specific reasons and read-only details, real selection/search/clear, stage/main isolation, route and clipboard preserved')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ReferenceStatusTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
