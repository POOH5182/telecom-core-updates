"""V180: an 임시코어 assigned on every cable but never spliced at the enclosures
stays 미완료. The reason now says so, and the same-ID join tools (함체 우클릭,
한꺼번에 잇기, 연결 후보 안내) join its pieces in field and after drawings."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import wf,LocalApp,update
from check_field_survey import code

TEMP='임시-78'


def splices(s):return s.conn.execute('SELECT COUNT(*) FROM splices').fetchone()[0]


def after_drawing(app):
    s=app.store
    n=[s.add_node('함체 '+str(i),i*200,100) for i in range(5)]
    s.backup_to(app.scenario_path('before'))
    c=[s.add_cable(n[i],n[i+1],'NEW'+str(i+1),'72C','신설') for i in range(4)]
    s._temporary_auto_running=True # build pieces saved by an older version
    for cable,number in zip(c,(5,5,37,37)):update(s,cable,number,dict(core_id=TEMP,detail='모바일 신규코어',signal='on'))
    s._temporary_auto_running=False
    return n,c


def field_drawing(path):
    s=code['Store'](path)
    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')")
    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('field_identity_policy',?)",(wf.FIELD_SLOT_POLICY,))
    s.conn.commit()
    n=[s.add_node('함체 '+str(i),i*200,100) for i in range(5)]
    c=[s.add_cable(n[i],n[i+1],'NEW'+str(i+1),'72C','신설') for i in range(4)]
    # Side cables so the middle enclosures are not route ends.
    for i in (1,2,3):s.add_cable(n[i],s.add_node('옆 '+str(i),i*200,300),'X'+str(i),'12C','기설')
    s._temporary_auto_running=True # build pieces saved by an older version
    with s.action('합성 임시코어'):
        for cable,number in zip(c,(5,5,37,37)):
            s.conn.execute("UPDATE cores SET core_id=?,detail='모바일 신규코어',signal='on' WHERE cable_id=? AND core_index=?",(TEMP,cable,number))
    s._temporary_auto_running=False
    return s,n,c


class TemporarySplitIncomplete(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
    def tearDown(self):self.s.close();self.temp.cleanup()

    def entry(self,slot):
        report=wf.completion_report(self.s)
        return report['by_slot'].get(slot) or report['by_id'].get(TEMP)

    def check_joins(self,c,n):
        first=(c[0],5)
        entry=self.entry(first)
        self.assertFalse(entry['complete'])
        self.assertIn('구간끼리 접속',entry['reason'])
        self.assertIn('같은 코어ID 끝 이어 연결',entry['reason'])
        model=wf.core_connection_highlight(self.s,[first])
        self.assertEqual(len(model['groups']),4)
        hints=[b for b in model['boundaries'] if b.get('same_id')]
        self.assertEqual(len(hints),3,[b['text'] for b in model['boundaries']])
        self.assertIn('같은 코어ID 끝 이어 연결',hints[0]['text'])
        pairs=wf.field_same_id_pairs(self.s,node_ids={n[1]},respect_exclusions=False)
        self.assertEqual(len(pairs),1)
        rows,blocked=wf.field_same_id_join_rows(self.s)
        self.assertEqual(len(rows),3);self.assertTrue(all(r['checked'] for r in rows))
        with self.s.action('같은 코어ID 한꺼번에 잇기'):wf.field_same_id_join_apply(self.s,[r['pair'] for r in rows])
        self.assertEqual(splices(self.s),3)
        self.assertEqual(len(wf.core_connection_highlight(self.s,[first])['groups']),1)
        self.assertTrue(self.entry(first)['complete'],self.entry(first)['reason'])
        self.assertEqual(wf.field_same_id_join_rows(self.s)[0],[])
        self.s.undo();self.assertEqual(splices(self.s),0)
        print('PASS temporary split pieces explained and joined:',wf.same_id_join_mode(self.s))

    def test_field_drawing(self):
        self.s,n,c=field_drawing(self.home/'f.sqlite3')
        self.assertEqual(wf.same_id_join_mode(self.s),'field')
        self.check_joins(c,n)

    def test_after_drawing(self):
        app=LocalApp(self.temp.name);self.s=app.store
        n,c=after_drawing(app)
        self.assertEqual(wf.same_id_join_mode(self.s),'after')
        # Global after auto-join still never touches 임시 IDs by itself.
        self.assertFalse(wf.after_auto_pairs(self.s))
        self.check_joins(c,n)

    def test_different_temporary_ids_not_joined(self):
        self.s,n,c=field_drawing(self.home/'g.sqlite3')
        with self.s.action('다른 임시'):
            self.s.conn.execute("UPDATE cores SET core_id='임시-90' WHERE cable_id=? AND core_index=5",(c[1],))
        self.assertFalse(wf.field_same_id_pairs(self.s,node_ids={n[1]},respect_exclusions=False))

    def test_entering_temporary_id_offers_join(self):
        self.s,n,c=field_drawing(self.home/'h.sqlite3')
        with patch.object(wf.messagebox,'askyesno',return_value=True):note=wf.offer_same_id_join(None,self.s,{TEMP})
        self.assertTrue(note);self.assertEqual(splices(self.s),3)

    def auto(self,c):
        first=(c[0],5)
        self.assertEqual(len(wf.core_connection_highlight(self.s,[first])['groups']),1)
        self.assertTrue(self.entry(first)['complete'],self.entry(first)['reason'])
        warn=wf.field_slot_warning_summary(self.s) if wf.field_slot_mode(self.s) else None
        if warn:self.assertFalse(any(warn[x]['unassigned'] for x in c),warn)

    def test_v182_open_joins_saved_pieces_once(self):
        for name,maker in (('field',lambda:field_drawing(self.home/'o.sqlite3')),):
            self.s,n,c=maker()
            self.assertEqual(wf.temporary_auto_activate(self.s),3);self.assertEqual(splices(self.s),3);self.auto(c)
            self.s.undo();self.assertEqual(splices(self.s),0)
            self.assertEqual(wf.temporary_auto_activate(self.s),0);self.assertEqual(splices(self.s),0)
        print('PASS V182 saved temporary pieces join on open once')

    def test_v186_unknown_piece_of_live_temporary_joins(self):
        # User case: 임시코어46 ON on two cables, 확인필요 on NEW8 -> still one core.
        for mode in ('after','field'):
            with self.subTest(mode=mode):
                if mode=='after':
                    (self.home/mode).mkdir();app=LocalApp(str(self.home/mode));self.s=app.store;n,c=after_drawing(app)
                else:
                    self.s,n,c=field_drawing(self.home/'u.sqlite3')
                self.s._temporary_auto_running=True
                with self.s.action('합성 확인필요'):self.s.conn.execute("UPDATE cores SET signal='' WHERE cable_id=? AND core_index=5",(c[1],))
                self.s._temporary_auto_running=False
                self.assertEqual(wf.temporary_auto_activate(self.s),3);self.auto(c)
                self.s.close()
        # No ON anywhere on the ID: left alone (V178 확인필요 임시코어 may stop anywhere).
        self.s,n,c=field_drawing(self.home/'z.sqlite3')
        self.s._temporary_auto_running=True
        with self.s.action('합성 전체 확인필요'):self.s.conn.execute("UPDATE cores SET signal='' WHERE core_id=?",(TEMP,))
        self.s._temporary_auto_running=False
        self.assertEqual(wf.temporary_auto_activate(self.s),0);self.assertEqual(splices(self.s),0)
        print('PASS V186 unknown-signal piece of a live temporary core joins')

    def test_v182_after_open_joins(self):
        app=LocalApp(self.temp.name);self.s=app.store
        n,c=after_drawing(app)
        self.assertEqual(wf.temporary_auto_activate(self.s),3);self.auto(c)

    def test_v182_assigning_joins_automatically(self):
        self.s,n,c=field_drawing(self.home/'a.sqlite3')
        with self.s.action('합성 지우기'):self.s.conn.execute("UPDATE cores SET core_id='',detail='',signal='' WHERE cable_id=? AND core_index=37",(c[3],))
        # The other three pieces were already joined by that edit.
        self.assertEqual(splices(self.s),2)
        # Typing the 임시 ID on the last cable joins every same-ID meeting.
        with self.s.action('코어 정보 변경'):self.s.conn.execute("UPDATE cores SET core_id=?,detail='모바일 신규코어',signal='on' WHERE cable_id=? AND core_index=37",(TEMP,c[3]))
        self.assertEqual(splices(self.s),3);self.auto(c)
        self.s.undo();self.assertEqual(splices(self.s),2)
        print('PASS V182 same temporary core joins automatically on edit')

    def test_v182_hand_disconnect_is_kept(self):
        self.s,n,c=field_drawing(self.home/'d.sqlite3')
        wf.temporary_auto_activate(self.s)
        row=self.s.conn.execute('SELECT * FROM splices WHERE node_id=?',(n[2],)).fetchone()
        self.s.disconnect(n[2],row['cable1_id'],row['core1_index'])
        self.assertEqual(splices(self.s),2)
        # A later edit of the same 임시코어 must not undo the hand disconnect.
        with self.s.action('코어 정보 변경'):self.s.conn.execute("UPDATE cores SET detail='바뀐 이름' WHERE cable_id=? AND core_index=5",(c[0],))
        self.assertEqual(splices(self.s),2)


if __name__=='__main__':unittest.main(verbosity=2)
