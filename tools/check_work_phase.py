"""V206: 작업차수 on a whole cable (all its cores) or on single cores.
A core's own phase beats its cable's phase, and the phase follows the core ID
through every cable it passes. Shown on the drawing label and in the cable
window's 상태 column."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_field_survey import code,wf


class WorkPhaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();s=self.s=code['Store'](Path(self.temp.name)/'p.sqlite3')
        a=s.add_node('MDF',0,0);j=s.add_node('함체 J',240,0);x=s.add_node('함체 X',480,0)
        self.f=s.add_cable(a,j,'F','12C','기설');self.d=s.add_cable(j,x,'D','12C','기설')
        for i,cid in ((1,'CORE-1'),(2,'CORE-2'),(3,'CORE-3')):s.update_core(self.f,i,(cid,'F','normal','','on'))
        s.update_core(self.d,5,('CORE-1','D','normal','','on'));s.update_core(self.d,6,('ONLY-D','D','normal','','on'))
    def tearDown(self):self.s.close();self.temp.cleanup()

    def names(self,core_id):return wf.phase_names(self.s,{'core_id':core_id})

    def test_cable_phase_marks_all_cores_and_follows_core(self):
        s=self.s
        self.assertEqual(wf.set_cable_phase(s,[self.f],'1차작업'),1)
        self.assertEqual(wf.cable_phase_name(s,self.f),'1차작업');self.assertEqual(wf.cable_phase_name(s,self.d),'')
        for cid in ('CORE-1','CORE-2','CORE-3'):self.assertEqual(self.names(cid),['1차작업'])
        self.assertEqual(self.names('ONLY-D'),[])
        self.assertIn('[1차작업]',wf.annotation_text(s,s.core(self.d,5)))
        tags=wf.cable_phase_tags(s)
        self.assertEqual(tags[self.f],['1차작업']);self.assertEqual(tags[self.d],['1차작업'])
        self.assertEqual(wf.cable_phase_label(s,self.f),'[1차]')
        # Moving the cable to another phase replaces it; '' clears it.
        wf.set_cable_phase(s,[self.f],'2차작업');self.assertEqual(self.names('CORE-2'),['2차작업'])
        wf.set_cable_phase(s,[self.f],'');self.assertEqual(self.names('CORE-2'),[]);self.assertEqual(wf.cable_phase_tags(s),{})
        s.undo();self.assertEqual(self.names('CORE-2'),['2차작업'])
        with self.assertRaises(ValueError):wf.set_cable_phase(s,[self.f],'없는차수')
        print('PASS cable phase marks every core in the cable and follows the core ID')

    def test_core_phase_beats_cable_phase(self):
        s=self.s;wf.set_cable_phase(s,[self.f],'1차작업')
        self.assertEqual(wf.set_core_phase(s,['CORE-1'],'2차작업'),1)
        self.assertEqual(self.names('CORE-1'),['2차작업']);self.assertEqual(self.names('CORE-2'),['1차작업'])
        self.assertEqual(wf.core_phase_source(s,'CORE-1'),('core',['2차작업']))
        self.assertEqual(wf.core_phase_source(s,'CORE-2'),('cable',['1차작업']))
        tags=wf.cable_phase_tags(s)
        self.assertEqual(tags[self.f],['1차작업','2차작업']);self.assertEqual(tags[self.d],['2차작업'])
        self.assertIn('[2차작업]',wf.annotation_text(s,s.core(self.d,5)))
        self.assertNotIn('1차작업',wf.annotation_text(s,s.core(self.d,5)))
        # Clearing the core's own phase brings back the cable phase.
        wf.set_core_phase(s,['CORE-1'],'');self.assertEqual(self.names('CORE-1'),['1차작업'])
        self.assertEqual(wf.core_phase_source(s,'CORE-1'),('cable',['1차작업']))
        # A core alone (no cable phase) shows its phase in every cable it uses.
        wf.set_cable_phase(s,[self.f],'');wf.set_core_phase(s,['CORE-1','ONLY-D'],'3차작업')
        self.assertEqual(wf.cable_phase_tags(s),{self.f:['3차작업'],self.d:['3차작업']})
        self.assertEqual(wf.set_core_phase(s,['',' '],'3차작업'),0)
        print('PASS core phase beats cable phase and clears back to it')


def windows_ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    import faulthandler
    faulthandler.dump_traceback_later(120,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;a=s.add_node('PHASE A',380,220);b=s.add_node('PHASE B',900,220);c=s.add_node('PHASE C',900,520)
            f=s.add_cable(a,b,'PF','12C','기설',lot_no='1');d=s.add_cable(b,c,'PD','12C','기설',lot_no='2')
            s.update_core(f,1,('PH-1','F','normal','','on'));s.update_core(f,2,('PH-2','F','normal','','on'));s.update_core(d,4,('PH-1','D','normal','','on'))
            app.refresh();app.update()
            def label_texts():return [app.canvas.itemcget(i,'text') for i in app.canvas.find_all() if app.canvas.type(i)=='text']
            assert not any('[1차]' in t for t in label_texts())
            event=type('E',(),{'x_root':10,'y_root':10})()
            with patch.object(code['tk'].Menu,'tk_popup',lambda *a,**k:None):app.selected={f};app.show_status_menu('cable',f,event)
            labels=[app._phase_menu.entrycget(i,'label').strip() for i in range(app._phase_menu.index('end')+1) if app._phase_menu.type(i)=='command']
            assert labels[:4]==['✓ 차수 없음','1차작업','2차작업','3차작업'],labels
            app.apply_context_phase([f],'1차작업');app.update()
            texts=label_texts();assert sum('[1차]' in t for t in texts)==2,texts
            dialog=code['CableDialog'](app,s,cable_id=f);app.update()
            values={item:dialog.tree.item(item,'values') for item in dialog.tree.get_children()}
            assert '[1차작업]' in values['1'][0] and '[1차작업]' in values['2'][0],values
            dialog.tree.selection_set('1');app.update()
            menu=dialog.build_phase_menu();assert dialog._phase_core_menu.index('end')>=3
            dialog.apply_core_phase('2차작업');app.update()
            values={item:dialog.tree.item(item,'values') for item in dialog.tree.get_children()}
            assert '[2차작업]' in values['1'][0] and '1차작업' not in values['1'][0],values
            assert '[1차작업]' in values['2'][0],values
            texts=label_texts();assert any('[1차·2차]' in t for t in texts) and any('[2차]' in t for t in texts),texts
            dialog.apply_cable_phase('');app.update()
            values={item:dialog.tree.item(item,'values') for item in dialog.tree.get_children()}
            assert '2차작업' in values['1'][0] and '차작업' not in values['2'][0],values
            assert dialog.tree.winfo_height()>200,dialog.tree.winfo_height()
            assert dialog.status_menu.entrycget(0,'label')=='작업차수 지정…'
            dialog.destroy();app.update()
            assert not errors,errors
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS Windows work phase menu, drawing label and cable window column')


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WorkPhaseTests))
    if not result.wasSuccessful():raise SystemExit(1)
    windows_ui()
