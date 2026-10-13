"""V133: core-number-only cable labels, a blinking route legend and click-to-trace in the work list."""
import os
import sys
import unittest
from unittest.mock import patch
from check_connection_highlight import HighlightTests
from check_field_slots import code,wf


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


def windows_ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    case=RouteLegendTests();case.setUp()
    try:
        (case.home/'ui').mkdir()
        with patch.dict(os.environ,{'TELECOM_APP_HOME':str(case.home/'ui')}),patch.object(code['messagebox'],'showerror') as error, \
             patch.object(code['messagebox'],'showinfo'),patch.object(code['messagebox'],'showwarning'):
            case.connect_all();case.set(1,1,'OTHER-ID')
            rn,rn_cable=case.rn_fixture()
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
                words=' '.join(w.cget('text') for w in legend.winfo_children())
                assert 'CORE-A' in words and 'OTHER-ID' in words and '코어ID 다름' in words,words
                colors={c for _,c in app._route_legend_swatches}
                assert colors=={g['color'] for g in app.highlight_connection_model['groups']}
                # V134: the RN shows which internal port the core is assigned to.
                dialog.tree.selection_set(next(i for i,key in dialog.row_meta.items() if key[0]=='CORE-A'));app.update()
                ports=[app.canvas.itemcget(i,'text') for i in app.canvas.find_withtag('core_path_port') if app.canvas.type(i)=='text']
                assert ports==['배정 RN-1 · SP1'],ports
                item=next(i for i in app.canvas.find_withtag('core_path_port') if app.canvas.type(i)=='text');assert app.item_to_node[item]==rn
                assert 'RN-1 SP1' in ' '.join(w.cget('text') for w in app._route_legend.winfo_children())
                # The legend swatches blink with the actual cable timer.
                seen=set();done=code['tk'].BooleanVar(master=app,value=False)
                def sample():
                    seen.add(app._route_legend_swatches[0][0].cget('bg'))
                    if len(seen)>=2:done.set(True)
                    else:app.after(60,sample)
                app.after(60,sample);timeout=app.after(2500,lambda:done.set(True));app.wait_variable(done);app.after_cancel(timeout)
                assert len(seen)>=2,seen
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
