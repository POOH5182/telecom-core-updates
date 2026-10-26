"""V154 facility compact defaults and read-only selected metadata on drawings."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code,wf

class FacilityDisplayTests(unittest.TestCase):
    def test_metadata_defaults_and_independent_migration(self):
        defaults=code['DISPLAY_DEFAULTS'];label=code['hamche_detail_text']
        h=dict(type='hamche',extra_json=json.dumps(dict(hamcheSpec='144C',hamcheId='H-123')))
        rn=dict(type='rn',extra_json=json.dumps(dict(rnId='RN-123',rnComputerNo='PC-456',rnSpec=dict(mp=4,sp=8,p=4))))
        self.assertEqual(label(h,defaults),'');self.assertEqual(label(rn,defaults),'')
        self.assertEqual(label(h,defaults,True),'규격: 144C · ID: H-123')
        self.assertEqual(label(rn,defaults,True),'규격: MP 4 / SP 8 / P 4 · ID: RN-123 · 전산화번호: PC-456')
        self.assertEqual(label(rn,dict(defaults,hamche_id=True)),'ID: RN-123')
        self.assertEqual(label(rn,dict(defaults,rn_computer=True)),'전산화번호: PC-456')
        self.assertIn('미입력',label(dict(type='rn',extra_json='{}'),defaults,True))
        self.assertEqual(label(dict(type='sub',extra_json='{}'),defaults,True),'')
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'display.json'
            path.write_text(json.dumps(dict(cable_label_policy='compact_v153',cable_id=True,hamche_id=True,hamche_spec=True,grid=False)))
            before=path.read_bytes();opts=code['read_display_options'](path)
            self.assertTrue(opts['cable_id']);self.assertFalse(opts['hamche_id']);self.assertFalse(opts['hamche_spec']);self.assertFalse(opts['grid'])
            self.assertEqual(before,path.read_bytes())
            opts.update(hamche_spec=True,hamche_id=True,rn_computer=True)
            code['save_display_options'](path,opts);self.assertEqual(code['read_display_options'](path),opts)

def windows_ui():
    if sys.platform!='win32':return
    import faulthandler
    faulthandler.dump_traceback_later(90,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;h=s.add_node('합성 함체',500,300);rn=s.add_node('합성 RN',680,300,'rn')
            s.set_hamche_details(h,'144C','H-123');s.set_rn_details(rn,'RN-123','PC-456');s.ensure_ports(rn,dict(mp=4,sp=8,p=4))
            app.refresh();app.update();before=wf.plan_snapshot(s.conn);history=s.history_rows()
            def details(view):return {view.item_to_node[i]:view.canvas.itemcget(i,'text') for i in view.canvas.find_withtag('hamche_details') if view.canvas.type(i)=='text'}
            def click(nid,state=0):
                n=s.node(nid);x=int(n['x']*app.view_scale-app.canvas.canvasx(0));y=int(n['y']*app.view_scale-app.canvas.canvasy(0))
                app.canvas.event_generate('<ButtonPress-1>',x=x,y=y,state=state);app.canvas.event_generate('<ButtonRelease-1>',x=x,y=y,state=state);app.update()
            def front(view,nid):
                order={item:i for i,item in enumerate(view.canvas.find_all())};mine=[order[i] for i in order if view.item_to_node.get(i)==nid]
                others=[order[i] for i in order if view.item_to_node.get(i) not in (nid,None)]
                assert min(mine)>max(others)
            assert details(app)=={}
            click(h);assert 'H-123' in details(app)[h] and rn not in details(app);front(app,h)
            assert 'H-123' not in app.drawing_svg()
            click(rn);assert 'MP 4 / SP 8 / P 4' in details(app)[rn] and 'PC-456' in details(app)[rn] and h not in details(app);front(app,rn)
            click(h,1);assert set(details(app))=={h,rn};front(app,h)
            click(rn,1);front(app,rn)
            app.view_scale=1.2;app.refresh();app.update();front(app,rn)
            app.view_scale=1.;app.selected.clear();app.refresh();app.update();assert not details(app)
            settings=code['DisplaySettingsDialog'](app);app.update()
            for k in ('hamche_spec','hamche_id','rn_computer'):settings.values[k].set(True)
            settings.apply();app.update();assert set(details(app))=={h,rn}
            assert 'PC-456' in app.drawing_svg()
            assert code['read_display_options'](app.display_options_path)==app.display_options
            app.display_options.update(hamche_spec=False,hamche_id=False,rn_computer=False);app.refresh();app.update()
            s.backup_to(app.scenario_path('gis'));view=wf.open_reference_drawing(app,'gis');app.update()
            assert not details(view);view.select_item('node',rn);app.update();assert 'RN-123' in details(view)[rn];front(view,rn)
            view.clear_selection();app.update();assert not details(view);view.destroy();app.update()
            assert wf.plan_snapshot(s.conn)==before and s.history_rows()==history
            click(rn)
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True);screenshot(app,Path('dist')/'v154-facility-display.png')
            assert not errors,errors
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows facility click details, front ordering, multi-selection, zoom, settings, SVG, reference and nonmutation')

if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(FacilityDisplayTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
