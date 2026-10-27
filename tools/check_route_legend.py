"""V133: core-number-only cable labels, a blinking route legend and click-to-trace in the work list."""
import os
import sys
import unittest
from unittest.mock import patch
from check_connection_highlight import HighlightTests
from check_field_slots import code,wf


LONG_NAME='장성 21-2 (1-8:4 RN) IN 방향 끝까지 잘리지 않고 보여야 하는 아주 긴 코어명 확인용 문구'


class RouteLegendTests(unittest.TestCase):
    setUp=HighlightTests.setUp
    tearDown=HighlightTests.tearDown
    slot=HighlightTests.slot
    set=HighlightTests.set
    apply=HighlightTests.apply
    connect_all=HighlightTests.connect_all
    snapshot=HighlightTests.snapshot
    model=HighlightTests.model

    def test_short_labels_hold_only_core_numbers(self):
        self.connect_all();self.set(1,1,'OTHER-ID');model=self.model()
        self.assertEqual(set(model['short_labels']),set(model['labels']))
        for cable in self.cables:self.assertEqual(model['short_labels'][cable],'1번')
        # Full text stays available for existing callers; the legend carries IDs and faults.
        self.assertIn('1 · OTHER-ID',model['labels'][self.cables[1]])
        segment=[row for row in model['legend'] if row['kind']=='segment']
        self.assertEqual(len(segment),len(model['groups']))
        self.assertEqual([row['color'] for row in segment],[g['color'] for g in model['groups']])
        text=' '.join(row['core_text']+' '+row['cable_text']+' '+row['fault'] for row in segment)
        self.assertIn('OTHER-ID',text);self.assertIn('A 1번',text);self.assertIn('코어ID 다름',text)

    def test_overlap_numbers_and_legend_row(self):
        self.set(0,2,'CORE-A');model=self.model()
        self.assertEqual(model['short_labels'][self.cables[0]],'1·2번')
        overlap=[row for row in model['legend'] if row['kind']=='overlap']
        self.assertEqual(len(overlap),1);self.assertEqual(overlap[0]['color'],wf.OVERLAP_COLOR);self.assertIn('A',overlap[0]['cable_text'])

    def rn_fixture(self):
        rn=self.s.add_node('RN-1',900,260,'rn');self.s.ensure_ports(rn,{'mp':1,'sp':4,'p':1})
        cable=self.s.add_cable(self.nodes[2],rn,'RN-C','12C','기설')
        self.s.update_core(cable,2,('CORE-A','','normal','','unknown'))
        self.s.connect(rn,(cable,2),('PORT:'+rn,3))
        return rn,cable

    def test_rn_port_assignment_is_shown_at_rn_and_legend(self):
        rn,cable=self.rn_fixture();before=self.snapshot();history=self.s.history_rows()
        model=self.model((cable,2))
        self.assertEqual(model['port_labels'][rn]['ports'],('SP1',));self.assertEqual(model['port_labels'][rn]['text'],'RN-1 · SP1')
        group=model['by_slot'][(cable,2)];self.assertEqual(model['port_labels'][rn]['color'],group['color'])
        self.assertTrue(any('RN-C 2번' in r['cable_text'] and 'RN-1 SP1' in r['cable_text'] for r in model['legend']))
        self.assertEqual(model['short_labels'][cable],'2번')
        ref=wf.reference_slot_highlight(self.s,[(cable,2)]);self.assertEqual(ref['port_labels'][rn]['ports'],('SP1',))
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.s.history_rows(),history)

    def test_reference_model_and_reads_do_not_change_data(self):
        self.connect_all();before=self.snapshot();history=self.s.history_rows()
        model=wf.reference_slot_highlight(self.s,[self.slot(0)])
        self.assertEqual(set(model['short_labels']),set(self.cables))
        self.assertTrue(all(v=='1번' for v in model['short_labels'].values()))
        self.assertEqual(len([r for r in model['legend'] if r['kind']=='segment']),len(model['groups']))
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.s.history_rows(),history)

    def test_legend_rows_carry_full_core_names(self):
        self.connect_all();self.s.update_core(self.cables[0],1,('CORE-A',LONG_NAME,'normal','','unknown'))
        model=self.model();row=next(r for r in model['legend'] if r['kind']=='segment' and 'CORE-A' in r['core_text'])
        self.assertIn(LONG_NAME,row['name_text'])

    def segment_rows(self):return [r for r in self.model()['legend'] if r['kind']=='segment']

    def test_v162_legend_row_shows_saved_signal(self):
        self.connect_all()
        for signal,text in (('on','신호 있음 (ON)'),('off','신호 없음 (OFF)'),('unknown','신호 미입력'),('','신호 미입력')):
            for i in range(len(self.cables)):self.set(i,1,'CORE-A',signal=signal)
            before=self.snapshot();history=self.s.history_rows()
            rows=self.segment_rows();row=next(r for r in rows if 'CORE-A' in r['core_text'])
            self.assertEqual(row['signal_text'],text,(signal,rows));self.assertTrue(row['signal_color'].startswith('#'))
            # Reading the legend never changes the drawing.
            self.assertEqual(self.snapshot(),before);self.assertEqual(self.s.history_rows(),history)

    def test_v162_mixed_signal_counts_each_slot(self):
        rows={('a',1):{'signal':'on'},('b',1):{'signal':'on'},('c',1):{'signal':''},('PORT:x',1):{'signal':'확인필요'}}
        self.assertEqual(wf.route_signal_state(rows,[('a',1),('b',1)]),('on','신호 있음 (ON)'))
        # V165: 미입력 is neutral, so ON + 미입력 is ON; only ON with OFF is mixed.
        self.assertEqual(wf.route_signal_state(rows,list(rows)),('on','신호 있음 (ON) · 미입력 2'))
        rows[('d',1)]={'signal':'off'}
        self.assertEqual(wf.route_signal_state(rows,list(rows)),('mixed','신호 섞임: ON 2 · OFF 1 · 미입력 2'))
        self.assertEqual(wf.route_signal_state(rows,[('c',1),('d',1)]),('off','신호 없음 (OFF) · 미입력 1'))
        self.assertEqual(wf.route_signal_state(rows,[('c',1),('PORT:x',1)]),('unknown','신호 미입력'))
        self.assertEqual(wf.route_signal_state({},[('z',1)])[1],'신호 미입력')


def windows_ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    case=RouteLegendTests();case.setUp()
    try:
        (case.home/'ui').mkdir()
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error, \
             patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showwarning'):
            case.connect_all();case.set(1,1,'OTHER-ID')
            rn,rn_cable=case.rn_fixture()
            case.s.update_core(case.cables[0],1,('CORE-A',LONG_NAME,'normal','','unknown'))
            app=code['App']();app.store.close();app.store=case.s;errors=[]
            app.report_callback_exception=lambda *args:errors.append(str(args[1]))
            try:
                for i,nid in enumerate(case.nodes):case.s.update_node_pos(nid,150+i*300,260)
                app.refresh();app.update()
                before=case.snapshot();history=case.s.history_rows()
                dialog=code['CoreCheckDialog'](app,case.s);dialog.kind.set('전체코어');dialog.reload();app.update()
                iid=next(i for i,key in dialog.row_meta.items() if key[0]=='CORE-A')
                # Native single click on the row: no double-click, no extra window.
                dialog.lift();dialog.tree.see(iid);dialog.tree.focus_force();app.update()
                x,y,w,h=dialog.tree.bbox(iid,'id')
                dialog.tree.event_generate('<ButtonPress-1>',x=x+5,y=y+h//2);dialog.tree.event_generate('<ButtonRelease-1>',x=x+5,y=y+h//2);app.update()
                assert dialog.tree.selection()==(iid,),dialog.tree.selection()
                assert app.highlight_owner is dialog and app.highlight_cables==set(case.cables)|{rn_cable},app.highlight_cables
                assert not [w for w in app.winfo_children() if isinstance(w,code['TraceDialog'])]
                assert '경로 표시 중' in dialog.route_info.get()
                texts=[app.canvas.itemcget(i,'text') for i in app.canvas.find_withtag('core_path_number') if app.canvas.type(i)=='text']
                assert texts and set(texts)<={'1번','2번'},texts
                legend=app._route_legend;assert legend.winfo_ismapped() or legend.winfo_manager()=='place'
                words=code['route_legend_text'](app)
                assert 'CORE-A' in words and 'OTHER-ID' in words and '코어ID 다름' in words,words
                colors={c for _,c in app._route_legend_swatches}
                assert colors=={g['color'] for g in app.highlight_connection_model['groups']}
                # V134: the RN shows which internal port the core is assigned to.
                dialog.tree.selection_set(next(i for i,key in dialog.row_meta.items() if key[0]=='CORE-A'));app.update()
                ports=[app.canvas.itemcget(i,'text') for i in app.canvas.find_withtag('core_path_port') if app.canvas.type(i)=='text']
                assert ports==['RN-1 · SP1'],ports
                item=next(i for i in app.canvas.find_withtag('core_path_port') if app.canvas.type(i)=='text');assert app.item_to_node[item]==rn
                # V143: the legend lists only color · core ID · full core name.
                words=code['route_legend_text'](app)
                assert 'RN-1 SP1' not in words and '1번' not in words,words
                assert LONG_NAME in words,words
                # V162: each route row says whether the core has a signal (CORE-A is not entered yet).
                assert '신호 미입력' in words,words
                badge=next(w for w in app._route_legend.winfo_children() if isinstance(w,code['tk'].Label) and w.cget('text')=='신호 미입력')
                assert int(badge.grid_info()['column'])==2 and badge.winfo_manager()=='grid'
                # V144: the full name is visible (wrapped) and can be dragged and copied.
                name=next(w for w in app._route_legend.winfo_children() if isinstance(w,code['tk'].Text) and LONG_NAME in w.get('1.0','end'))
                app.update_idletasks();assert name.count('1.0','end','displaylines')[0]<=int(name.cget('height')),'core name is cut'
                name.event_generate('<Button-1>',x=2,y=4);app.update();assert app.focus_get() is name
                name.focus_force();app.update();name.tag_add('sel','1.0','1.5');name.event_generate('<Control-c>');app.update()
                assert app.clipboard_get()==name.get('1.0','1.5'),(app.clipboard_get(),name.get('1.0','1.5'))
                ident=next(w for w in app._route_legend.winfo_children() if isinstance(w,code['tk'].Entry) and w.get()=='CORE-A')
                ident.event_generate('<Button-1>',x=2,y=4);app.update();ident.focus_force();app.update();ident.selection_range(0,'end');ident.event_generate('<Control-c>');app.update()
                assert app.clipboard_get()=='CORE-A',app.clipboard_get()
                ident.selection_clear();ident.event_generate('<Button-3>',x=2,y=4);app.update();assert app.clipboard_get()=='CORE-A'
                # Swatches stay steady while the cables keep blinking.
                seen=set();states=set();done=code['tk'].BooleanVar(master=app,value=False)
                def sample():
                    seen.add(app._route_legend_swatches[0][0].cget('bg'));states.add(app.highlight_blink_on)
                    if len(states)>=2 and len(seen)==1:done.set(True)
                    else:app.after(60,sample)
                app.after(60,sample);timeout=app.after(2500,lambda:done.set(True));app.wait_variable(done);app.after_cancel(timeout)
                assert len(states)>=2 and seen=={app._route_legend_swatches[0][1]},(seen,states)
                # A list reload must not take the map back from another owner.
                other=object();app.start_highlight_blink({case.cables[0]:'#ff7a00'},owner=other,core_slots=[case.slot(0)])
                dialog.reload();app.update();assert app.highlight_owner is other
                app.stop_highlight_blink(clear=True);app.update();assert not hasattr(app,'_route_legend') or '_route_legend' not in app.__dict__
                # Choosing again then closing the list clears the map and the legend.
                other_iid=next(i for i,key in dialog.row_meta.items() if key[0]=='OTHER-ID')
                dialog.tree.selection_set(other_iid);app.update();assert app.highlight_owner is dialog
                dialog.destroy();app.update()
                assert not app.highlight_cables and '_route_legend' not in app.__dict__ and not app.canvas.find_withtag('core_path_number')
                assert case.snapshot()==before and case.s.history_rows()==history
                assert not errors,errors;assert not error.called,error.call_args
            finally:app.on_close()
        print('PASS Windows work-list single click route, core-number-only cable labels, blinking legend, owner safety and close cleanup')
    finally:case.tearDown()


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RouteLegendTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
