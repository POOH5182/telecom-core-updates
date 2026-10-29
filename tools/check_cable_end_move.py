"""V170: move one end of a cable to another facility while keeping its core IDs, details and signals."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code,wf


class CableEndMoveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.s=code['Store'](Path(self.temp.name)/'m.sqlite3');s=self.s
        self.a=s.add_node('함체A',100,100);self.b=s.add_node('함체B',500,100);self.c=s.add_node('함체C',500,400)
        self.main=s.add_cable(self.a,self.b,'MAIN','12C','기설');self.other=s.add_cable(self.b,self.c,'BC','12C','기설')
        s.conn.executemany("UPDATE cores SET core_id=?,detail=?,signal=? WHERE cable_id=? AND core_index=?",
                           [(f'ID-{i}',f'내역{i}','ON',self.main,i) for i in range(1,5)]);s.conn.commit()
        s.connect(self.b,(self.main,1),(self.other,1))
    def tearDown(self):self.s.close();self.temp.cleanup()

    def identities(self):
        return [(r['core_id'],r['detail'],r['signal']) for r in self.s.conn.execute('SELECT * FROM cores WHERE cable_id=? ORDER BY core_index',(self.main,))]

    def test_move_keeps_cores_drops_old_splices_and_undoes(self):
        s=self.s;before=self.identities();groups=len(s.history_rows())
        preview=s.cable_end_move_preview(self.main,self.b,self.c)
        self.assertEqual((preview['column'],preview['other'],preview['splices'],preview['cores']),('n2id',self.a,1,4))
        s.move_cable_end(self.main,self.b,self.c)
        cable=s.cable(self.main);self.assertEqual((cable['n1id'],cable['n2id']),(self.a,self.c))
        self.assertEqual(self.identities(),before)
        self.assertEqual(s.conn.execute('SELECT COUNT(*) FROM splices WHERE node_id=? AND (cable1_id=? OR cable2_id=?)',(self.b,self.main,self.main)).fetchone()[0],0)
        self.assertEqual(len(s.history_rows()),groups+1)
        s.undo();cable=s.cable(self.main);self.assertEqual((cable['n1id'],cable['n2id']),(self.a,self.b))
        self.assertEqual(s.conn.execute('SELECT COUNT(*) FROM splices WHERE node_id=?',(self.b,)).fetchone()[0],1)
        self.assertEqual(self.identities(),before)

    def test_move_first_end(self):
        self.s.move_cable_end(self.main,self.a,self.c);cable=self.s.cable(self.main)
        self.assertEqual((cable['n1id'],cable['n2id']),(self.c,self.b))

    def test_invalid_targets(self):
        s=self.s
        for old,new in ((self.b,self.b),(self.b,self.a),(self.c,self.a),(self.b,'missing')):
            with self.assertRaises(ValueError):s.move_cable_end(self.main,old,new)
        cable=s.cable(self.main);self.assertEqual((cable['n1id'],cable['n2id']),(self.a,self.b))

    def test_locked_enclosure_blocks_move(self):
        s=self.s;s.set_node_locked(self.a,True);s.set_node_locked(self.b,True)
        with self.assertRaises(Exception):s.move_cable_end(self.main,self.b,self.c)
        cable=s.cable(self.main);self.assertEqual((cable['n1id'],cable['n2id']),(self.a,self.b))
        self.assertEqual(self.identities()[0],('ID-1','내역1','ON'))


def windows_ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    import faulthandler
    faulthandler.dump_traceback_later(90,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store;a=s.add_node('MOVE A',380,220);b=s.add_node('MOVE B',900,220);c=s.add_node('MOVE C',900,520)
            cable=s.add_cable(a,b,'MV1','12C','기설')
            s.conn.execute("UPDATE cores SET core_id='KEEP-1',detail='유지내역' WHERE cable_id=? AND core_index=1",(cable,));s.conn.commit()
            app.refresh();app.update()
            class Event:x_root=10;y_root=10
            with patch.object(code['tk'].Menu,'tk_popup'):app.selected={cable};app.show_status_menu('cable',cable,Event())
            labels=[app._cable_end_menu.entrycget(i,'label') for i in range(app._cable_end_menu.index('end')+1)]
            assert labels==['MOVE A 쪽 끝 → 다른 시설로…','MOVE B 쪽 끝 → 다른 시설로…'],labels
            app._cable_end_menu.invoke(1)
            assert app.cable_end_move and 'MOVE B' in app.status.get(),app.status.get()
            with patch.object(code['messagebox'],'askyesno',return_value=False) as ask:
                app.finish_cable_end_move(app.cable_end_move,c);assert ask.called
            assert s.cable(cable)['n2id']==b
            app.start_cable_end_move(cable,b)
            with patch.object(code['messagebox'],'askyesno',return_value=True):
                app.finish_cable_end_move(app.cable_end_move,c)
            app.update()
            assert s.cable(cable)['n2id']==c and s.core(cable,1)['core_id']=='KEEP-1' and s.core(cable,1)['detail']=='유지내역'
            assert '코어내역 유지' in app.status.get(),app.status.get()
            app.set_mode('select');assert app.cable_end_move is None
            app.undo();assert s.cable(cable)['n2id']==b
            assert not errors,errors
            print('PASS windows cable end move')
        finally:app.on_close()


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=2).result
    if not result.wasSuccessful():
        print('::error::check_cable_end_move unit tests failed');sys.exit(1)
    try:windows_ui()
    except Exception:
        import traceback;print('::error::'+traceback.format_exc().replace('\n','%0A'));raise
    print('PASS check_cable_end_move')
