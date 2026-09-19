"""Stage ownership, stable labels and monitor-safe per-stage popup preferences."""
from pathlib import Path
from types import SimpleNamespace
import os
import tempfile
import unittest
from unittest.mock import patch
from check_after_plan import code,wf


class StageWindowTests(unittest.TestCase):
    def test_fixed_owner_context_survives_main_stage_change(self):
        main=SimpleNamespace(scenario_kind=lambda:'after')
        reference=SimpleNamespace(master=main,_stage_kind='gis',_stage_reference=True)
        child=SimpleNamespace(master=reference)
        self.assertEqual(wf.stage_window_context(child),('gis',True))
        self.assertEqual(wf.stage_window_context(main),('after',False))
        self.assertEqual(wf.stage_window_context(None),(None,False))
        field=SimpleNamespace(master=main,source_kind='before',reference_context=True)
        self.assertEqual(wf.stage_window_context(field),('before',True))

    def test_titles_are_readable_idempotent_and_change_stage(self):
        title=wf.stage_window_title('함체 TEST 내역','gis',True)
        self.assertEqual(title,'[GIS] 함체 TEST 내역 · 참고용')
        self.assertEqual(wf.stage_window_title(title,'gis',True),title)
        self.assertEqual(wf.stage_window_title(title,'before',False),'[현장] 함체 TEST 내역 · 편집 중')
        self.assertEqual(wf.stage_window_title('통신도면 V119','after',False),'[후도면] 통신도면 V119 · 편집 중')

    def test_saved_positions_separate_stage_role_and_dialog_family(self):
        with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
            keys=[]
            for index,(kind,reference,family) in enumerate((('gis',True,'CableDialog'),('before',True,'CableDialog'),('after',True,'CableDialog'),('after',False,'CableDialog'),('after',False,'NodeDialog'))):
                window=SimpleNamespace(_stage_kind=kind,_stage_reference=reference,_popup_family=family)
                key=wf.stage_popup_position_key(window);keys.append(key)
                wf.save_dialog_position(wf.stage_popup_position_path(),key,index*100,index*50)
            self.assertEqual(len(set(keys)),5)
            for index,key in enumerate(keys):
                self.assertEqual(wf.popup_position(wf.stage_popup_position_path(),key),(index*100,index*50))
            self.assertFalse((Path(temp)/'data'/'popup_positions.json').exists())

    def test_independent_drawing_remembers_other_connected_monitor(self):
        owner=SimpleNamespace()
        window=SimpleNamespace(_stage_kind='gis',_stage_reference=True,_stage_independent=True,_popup_family='Drawing',master=owner,winfo_exists=lambda:True,update_idletasks=lambda:None)
        left=(-1920,0,1920,1040);center=(0,0,2560,1400)
        with patch.object(wf,'popup_monitor_bounds',return_value=center),patch.object(wf,'popup_position',return_value=(-1800,100)),patch.object(wf,'popup_outer_geometry',return_value=(0,0,1100,800)),patch.object(wf,'saved_popup_monitor_bounds',return_value=left) as connected,patch.object(wf,'set_popup_position') as move:
            wf.restore_stage_popup_position(window,owner)
            connected.assert_called_once_with((-1800,100),window)
            move.assert_called_once_with(window,-1800,100)
        window._stage_independent=False
        with patch.object(wf,'popup_monitor_bounds',return_value=center),patch.object(wf,'popup_position',return_value=(-1800,100)),patch.object(wf,'popup_outer_geometry',return_value=(0,0,1100,800)),patch.object(wf,'saved_popup_monitor_bounds') as connected,patch.object(wf,'center_native_popup') as native,patch.object(wf,'popup_window_handle',return_value=1),patch.object(wf,'set_popup_position') as move:
            wf.restore_stage_popup_position(window,owner)
            connected.assert_not_called()
            if os.name=='nt':native.assert_called_once_with(1,center)
            else:move.assert_called_once_with(window,730,300)

    def test_restore_uses_only_owner_monitor_and_clamps_visible(self):
        left=(-1920,0,1920,1040);center=(0,0,2560,1400);right=(2560,-240,1920,1040)
        self.assertEqual(wf.remembered_position_on_monitor((-1800,100),460,230,left),(-1800,100))
        self.assertIsNone(wf.remembered_position_on_monitor((-1800,100),460,230,center))
        self.assertIsNone(wf.remembered_position_on_monitor((100,100),460,230,right))
        self.assertEqual(wf.remembered_position_on_monitor((4400,700),460,230,right),(4020,570))
        self.assertEqual(wf.remembered_position_on_monitor((-100,1000),2200,1400,left),(-1920,0))
        self.assertIsNone(wf.remembered_position_on_monitor(None,460,230,left))


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(StageWindowTests))
    if not result.wasSuccessful():raise SystemExit(1)
