"""V160/V161: editing a connected temporary core's ID/name/signal at one number updates the whole path."""
from pathlib import Path
import sys
import tempfile
import unittest
from check_field_survey import code,wf


def fixture(path,field):
    s=code['Store'](path)
    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')")
    if field:s.conn.execute("INSERT OR REPLACE INTO meta VALUES('field_identity_policy',?)",(wf.FIELD_SLOT_POLICY,))
    s.conn.commit()
    nodes=[s.add_node('합성 시설 '+str(i),i*180,0) for i in range(4)]
    cables=[s.add_cable(nodes[i],nodes[i+1],chr(65+i),'6C','기설') for i in range(3)]
    with s.action('합성 임시코어 경로'):
        for i,c in enumerate(cables):
            s.conn.execute("UPDATE cores SET core_id='임시-7',detail='임시 내역',status1='normal',signal=? WHERE cable_id=? AND core_index=1",(('on','unknown','off')[i],c))
        for i in (1,2):
            a,b=sorted(((cables[i-1],1),(cables[i],1)));s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(nodes[i],*a,*b))
        # An unconnected number with the same temporary ID must stay as it is.
        s.conn.execute("UPDATE cores SET core_id='임시-7',detail='분리 내역' WHERE cable_id=? AND core_index=6",(cables[0],))
    return s,nodes,cables


class TemporaryRouteRename(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
    def tearDown(self):self.s.close();self.temp.cleanup()

    def check_mode(self,field):
        self.s,n,c=fixture(self.home/('f.sqlite3' if field else 'p.sqlite3'),field)
        self.assertEqual(wf.field_slot_mode(self.s),field)
        signals=[self.s.core(x,1)['signal'] for x in c]
        old=self.s.core(c[2],1)
        # Edit at the far end, typed in the screen form 임시코어7 → real ID.
        self.s.update_core(c[2],1,['REAL-9','새 코어명',old['status1'],old['status2'],old['signal']])
        for x in c:
            row=self.s.core(x,1);self.assertEqual((row['core_id'],row['detail']),('REAL-9','새 코어명'),x)
        if field:self.assertEqual([self.s.core(x,1)['signal'] for x in c],signals)
        # Field drawings keep cable-slot identities: an unconnected number stays.
        if field:stray=self.s.core(c[0],6);self.assertEqual((stray['core_id'],stray['detail']),('임시-7','분리 내역'))
        self.s.undo()
        for x in c:self.assertEqual(self.s.core(x,1)['core_id'],'임시-7')
        return c

    def test_field_slot_drawing(self):self.check_mode(True)
    def test_plain_drawing(self):self.check_mode(False)

    def test_name_only_and_screen_label(self):
        self.s,n,c=fixture(self.home/'n.sqlite3',True)
        old=self.s.core(c[1],1)
        self.s.update_core(c[1],1,['임시코어7','이름만',old['status1'],old['status2'],old['signal']])
        for x in c:
            row=self.s.core(x,1);self.assertEqual((row['core_id'],row['detail']),('임시-7','이름만'))
        self.s.update_core(c[0],1,['임시코어12','이름만',old['status1'],old['status2'],'on'])
        self.assertEqual([self.s.core(x,1)['core_id'] for x in c],['임시-12']*3)
        self.assertEqual([self.s.core(x,1)['detail'] for x in c],['이름만']*3)

    def test_real_id_and_lock_untouched(self):
        self.s,n,c=fixture(self.home/'r.sqlite3',True)
        wf.field_slot_write(self.s,(c[0],1),['LIVE-1','실제','normal','','on']);self.s.conn.commit()
        old=self.s.core(c[2],1)
        self.s.update_core(c[2],1,['임시-7','바꾼 이름',old['status1'],old['status2'],old['signal']])
        self.assertEqual(self.s.core(c[0],1)['core_id'],'LIVE-1');self.assertEqual(self.s.core(c[1],1)['detail'],'바꾼 이름')

    def test_locked_path_refuses_without_writes(self):
        self.s,n,c=fixture(self.home/'l.sqlite3',True)
        self.s.set_node_locked(n[2],True);old=self.s.core(c[0],1)
        with self.assertRaisesRegex(ValueError,'잠겨'):
            self.s.update_core(c[0],1,['REAL-9','x',old['status1'],old['status2'],old['signal']])
        self.assertEqual([self.s.core(x,1)['core_id'] for x in c],['임시-7']*3)

    def test_signal_follows_connected_temporary_path(self):
        self.s,n,c=fixture(self.home/'s.sqlite3',True)
        old=self.s.core(c[0],1);stray=self.s.core(c[0],6)['signal']
        self.s.update_core(c[0],1,[old['core_id'],old['detail'],old['status1'],old['status2'],'off'])
        self.assertEqual([self.s.core(x,1)['signal'] for x in c],['off']*3)
        self.assertEqual(self.s.core(c[0],6)['signal'],stray)
        self.s.undo();self.assertEqual([self.s.core(x,1)['signal'] for x in c],['on','unknown','off'])
        with self.s.action('케이블 신호'):self.s.set_core_signal('임시-7','on',slot=(c[1],1))
        self.assertEqual([self.s.core(x,1)['signal'] for x in c],['on']*3)
        with self.s.action('함체 신호'):positions=self.s.set_core_signal('임시-7','unknown',slot=(c[2],1),node_id=n[2])
        self.assertEqual(len(positions),3);self.assertEqual([self.s.core(x,1)['signal'] for x in c],['unknown']*3)

    def test_after_drawing_signal(self):
        self.s,n,c=fixture(self.home/'a.sqlite3',False)
        self.s.conn.execute("UPDATE meta SET value='after' WHERE key='active_scenario'");self.s.conn.commit()
        old=self.s.core(c[1],1)
        self.s.update_core(c[1],1,[old['core_id'],old['detail'],old['status1'],old['status2'],'on'])
        self.assertEqual([self.s.core(x,1)['signal'] for x in c],['on']*3)


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=1).result
    if not result.wasSuccessful():
        for _,trace in result.failures+result.errors:print('::error::'+trace.encode('ascii','backslashreplace').decode().replace('\n','%0A'))
        sys.exit(1)
    print('PASS temporary route rename')
