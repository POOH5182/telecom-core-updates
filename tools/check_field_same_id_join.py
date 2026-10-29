"""V176: in a field drawing two free ends with the same real core ID at one
enclosure join into one route (no 「같은 코어ID … 끊어짐」 error, one legend row)."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from check_field_survey import code,wf

ID='3061838318'


def fixture(path,field=True):
    s=code['Store'](path)
    s.conn.execute("INSERT OR REPLACE INTO meta VALUES('active_scenario','before')")
    if field:s.conn.execute("INSERT OR REPLACE INTO meta VALUES('field_identity_policy',?)",(wf.FIELD_SLOT_POLICY,))
    s.conn.commit()
    names=('민원동 앞 M/H','JB1744D663','JB1744G021','JB1744W391','1744Y371','서쪽','남쪽','북쪽')
    n={k:s.add_node(k,i*150,0) for i,k in enumerate(names)}
    c=dict(one=s.add_cable(n[names[0]],n[names[1]],'NEW1','36C','신설'),
           left=s.add_cable(n[names[1]],n[names[2]],'L','36C','기설'),
           mid=s.add_cable(n[names[2]],n[names[3]],'M','36C','기설'),
           far=s.add_cable(n[names[3]],n[names[4]],'F','36C','기설'))
    # Extra cables so the meeting enclosures are not route ends.
    for a,b in ((1,5),(2,6),(3,7)):s.add_cable(n[names[a]],n[names[b]],'X'+str(a),'12C','기설')
    with s.action('합성 경로'):
        # Purple: existing 1차 connected route with the real ID, signal ON.
        for cable in ('mid','far'):s.conn.execute("UPDATE cores SET core_id=?,detail='(OK)포항남부경찰서',signal='on' WHERE cable_id=? AND core_index=23",(ID,c[cable]))
        a,b=sorted(((c['mid'],23),(c['far'],23)));s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(n[names[3]],*a,*b))
        # Orange: new cable joined to the left cable with a temporary core.
        s.conn.execute("UPDATE cores SET core_id='임시-5' WHERE cable_id=? AND core_index=1",(c['one'],))
        s.conn.execute("UPDATE cores SET core_id='임시-5' WHERE cable_id=? AND core_index=23",(c['left'],))
        a,b=sorted(((c['one'],1),(c['left'],23)));s.conn.execute('INSERT INTO splices VALUES(?,?,?,?,?)',(n[names[1]],*a,*b))
    return s,n,c,names


def splice_at(s,nid):return s.conn.execute('SELECT COUNT(*) FROM splices WHERE node_id=?',(nid,)).fetchone()[0]


class FieldSameIdJoin(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
    def tearDown(self):self.s.close();self.temp.cleanup()

    def one_route(self):
        model=wf.core_connection_highlight(self.s,[(self.c['one'],1)])
        self.assertEqual(len(model['groups']),1,[g['slots'] for g in model['groups']])
        legend=[r for r in model['legend'] if r['kind']=='segment']
        self.assertEqual(len(legend),1);self.assertEqual(legend[0]['signal'],'on')
        comp=wf.field_slot_audit(self.s)['by_slot'][(self.c['one'],1)]
        self.assertNotIn('split',comp['causes']);self.assertFalse(comp['error'])

    def test_entering_id_at_far_end_offers_join(self):
        self.s,n,c,names=fixture(self.home/'a.sqlite3');self.c=c;g=n[names[2]]
        old=self.s.core(c['one'],1)
        applied,_,errors=self.s.apply_core_identity_changes(c['one'],[(1,ID,'(OK)포항남부경찰서')])
        self.assertEqual((applied,errors),([1],[]))
        self.assertEqual(self.s.core(c['left'],23)['core_id'],ID)
        # The store never rewires by itself (field policy); the editor asks.
        self.assertEqual(splice_at(self.s,g),0)
        with patch.object(wf.messagebox,'askyesno',return_value=False):self.assertEqual(wf.offer_same_id_join(None,self.s,{ID}),'')
        self.assertEqual(splice_at(self.s,g),0)
        with patch.object(wf.messagebox,'askyesno',return_value=True) as ask:note=wf.offer_same_id_join(None,self.s,{ID})
        self.assertIn('JB1744G021',ask.call_args[0][1]);self.assertIn('JB1744G021',note)
        self.assertEqual(splice_at(self.s,g),1)
        self.one_route()
        self.assertEqual(self.s.core(c['one'],1)['signal'] or '',old['signal'] or '')
        self.s.undo()
        self.assertEqual(splice_at(self.s,g),0);self.assertEqual(self.s.core(c['left'],23)['core_id'],ID)

    def existing_split(self,name,signal='on'):
        self.s,n,c,names=fixture(self.home/name);self.c=c
        with self.s.action('합성 끊어진 같은 ID'):
            for cable,index in ((c['one'],1),(c['left'],23)):
                self.s.conn.execute("UPDATE cores SET core_id=?,signal=? WHERE cable_id=? AND core_index=?",(ID,signal,cable,index))
        return n,names

    def test_already_saved_split_offers_join(self):
        n,names=self.existing_split('b.sqlite3','');g=n[names[2]]
        model=wf.core_connection_highlight(self.s,[(self.c['one'],1)])
        self.assertEqual(len(model['groups']),2)
        hint=[b for b in model['boundaries'] if b['node_id']==g]
        self.assertTrue(hint and hint[0].get('same_id'),hint)
        self.assertIn('같은 코어ID 끝 이어 연결',hint[0]['text'])
        pairs=wf.field_same_id_pairs(self.s,node_ids={g},respect_exclusions=False)
        self.assertEqual(len(pairs),1)
        with self.s.action('같은 코어ID 끝 이어 연결'):wf.field_same_id_join_apply(self.s,pairs)
        self.one_route()
        self.s.undo();self.assertEqual(splice_at(self.s,g),0)

    def test_on_off_conflict_is_explained_not_joined(self):
        n,names=self.existing_split('c.sqlite3','off');g=n[names[2]]
        blocked=[]
        self.assertFalse(wf.field_same_id_pairs(self.s,node_ids={g},blocked=blocked))
        self.assertIn('신호가 서로 다릅니다',blocked[0]['reason'])
        hint=[b for b in wf.core_connection_highlight(self.s,[(self.c['one'],1)])['boundaries'] if b['node_id']==g][0]
        self.assertIn('신호가 서로 다릅니다',hint['text'])

    def test_three_ends_are_not_guessed(self):
        n,names=self.existing_split('d.sqlite3');g=n[names[2]]
        extra=[x for x in self.s.node_cables(g) if x['id'] not in self.c.values()][0]['id']
        self.s.conn.execute("UPDATE cores SET core_id=?,signal='on' WHERE cable_id=? AND core_index=1",(ID,extra));self.s.conn.commit()
        blocked=[]
        self.assertFalse(wf.field_same_id_pairs(self.s,node_ids={g},blocked=blocked))
        self.assertIn('3개',blocked[0]['reason'])

    def test_route_identity_review_allows_and_joins(self):
        self.s,n,c,names=fixture(self.home/'e.sqlite3');self.c=c
        preview=wf.field_route_identity_preview(self.s,c['one'],[(1,ID,'')])
        result=wf.field_route_identity_commit(self.s,preview)
        self.assertEqual(result['ids'],(ID,))
        with patch.object(wf.messagebox,'askyesno',return_value=True):self.assertTrue(wf.offer_same_id_join(None,self.s,result['ids']))
        self.one_route()
        # A piece that does not meet this route stays refused as a duplicate.
        free=self.s.add_node('외딴 함체',0,500);other=self.s.add_node('외딴 끝',0,700)
        lone=self.s.add_cable(free,other,'LONE','12C','기설')
        wf.field_slot_write(self.s,(lone,1),('LONE-ID','',  'normal','','on'));self.s.conn.commit()
        with self.assertRaisesRegex(ValueError,'이미'):wf.field_route_identity_preview(self.s,c['one'],[(1,'LONE-ID','')])

    def test_plain_drawing_unchanged(self):
        self.s,n,c,names=fixture(self.home/'f.sqlite3',field=False);self.c=c
        self.assertFalse(wf.field_slot_mode(self.s))
        self.assertEqual(wf.field_same_id_joins_for(self.s,{ID}),[])
        self.assertFalse(wf.field_same_id_pairs(self.s))


if __name__=='__main__':unittest.main(verbosity=2)
