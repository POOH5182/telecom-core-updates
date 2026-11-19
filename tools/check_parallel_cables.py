"""V205: cables that join the same two enclosures are drawn as straight
parallel lines (no bowed curves). The two outside cables carry their label
just outside the bundle; inner cables carry it on their own line at
staggered heights so labels never overlap. A lone cable is unchanged."""
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from check_field_survey import code

path_of=code['parallel_cable_path'];even=code['cable_path_even_points'];point=code['cable_path_point']
GAP=code['PARALLEL_CABLE_GAP'];END=code['PARALLEL_CABLE_END']


class Geometry(unittest.TestCase):
    def test_lone_cable_keeps_old_three_point_form(self):
        self.assertEqual(path_of(0,0,100,0,0,1),[(0,0),(50,0),(100,0)])
        self.assertTrue(code['cable_path_smooth'](path_of(0,0,100,0,0,1)))

    def test_two_cables_are_straight_and_parallel(self):
        a=path_of(100,100,100,450,0,2);b=path_of(100,100,100,450,1,2)
        self.assertEqual(len(a),2);self.assertEqual(len(b),2)
        self.assertEqual({round(x,6) for x,_ in a},{round(a[0][0],6)})
        self.assertAlmostEqual(abs(a[0][0]-b[0][0]),GAP)
        self.assertFalse(code['cable_path_smooth'](a))

    def test_wide_bundle_tapers_into_the_enclosure(self):
        n=4
        for i in range(n):
            p=path_of(0,0,0,400,i,n,2)
            offset=(i-(n-1)/2)*GAP*2
            for x,_ in (p[0],p[-1]):self.assertLessEqual(abs(x),END*2+1e-6)
            self.assertAlmostEqual(abs(p[1][0]),abs(offset));self.assertAlmostEqual(abs(p[-2][0]),abs(offset))
        # Diagonal cables: middle run stays parallel to the chord.
        p=path_of(0,0,300,400,3,4);(x1,y1),(x2,y2)=p[1],p[2]
        self.assertAlmostEqual((x2-x1)*400-(y2-y1)*300,0,places=6)

    def test_even_points_follow_the_straight_lines(self):
        p=path_of(0,0,0,600,0,2)
        pts=even(p,150);self.assertEqual(len(pts),4)
        self.assertTrue(all(abs(x-p[0][0])<1e-6 for x,_ in pts))
        self.assertEqual(point(p,.5),(p[0][0],300.0))
        self.assertIn(' L ',code['cable_path_svg'](p))


def ui():
    if sys.platform!='win32' and not os.environ.get('TELECOM_CHECK_UI'):return
    import faulthandler
    faulthandler.dump_traceback_later(120,exit=True)
    with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,TELECOM_APP_HOME=temp):
        app=code['App']();errors=[];app.report_callback_exception=lambda *a:errors.append(a)
        try:
            s=app.store
            a=s.add_node('PAR A',400,160);b=s.add_node('PAR B',400,560)
            ids=[s.add_cable(a,b,'',spec,'기설') for spec in ('72C','48C','24C','144C')]
            lone_a=s.add_node('LONE A',900,160);lone_b=s.add_node('LONE B',900,560)
            lone=s.add_cable(lone_a,lone_b,'','12C','기설')
            app.display_options['auto_labels']=True
            app.refresh();app.update()
            xs=[]
            for cid in ids:
                coords=app.canvas.coords(app.cable_line_items[cid])
                pts=code['cable_path_points'](coords)
                assert len(pts) in (2,4),coords
                assert app.canvas.itemcget(app.cable_line_items[cid],'smooth') in ('0','false',''),app.canvas.itemcget(app.cable_line_items[cid],'smooth')
                mid=pts[len(pts)//2-1] if len(pts)==4 else pts[0]
                xs.append(round(mid[0],3))
            assert len(set(xs))==4 and (xs==sorted(xs) or xs==sorted(xs,reverse=True)),xs
            lone_coords=app.canvas.coords(app.cable_line_items[lone]);assert len(lone_coords)==6,lone_coords
            layout={e['id']:e for e in app.current_label_layout}
            boxes=[layout[c]['bounds'] for c in ids]
            for i in range(len(boxes)):
                for j in range(i+1,len(boxes)):
                    p,q=boxes[i],boxes[j]
                    assert p[2]<=q[0] or q[2]<=p[0] or p[3]<=q[1] or q[3]<=p[1],(p,q)
            left,right=min(xs),max(xs)
            outer=[layout[c]['bounds'] for c in ids if round(code['cable_path_point'](code['cable_path_points'](app.canvas.coords(app.cable_line_items[c])),.5)[0],3) in (left,right)]
            assert len(outer)==2
            assert any(bx[2]<=left for bx in outer) and any(bx[0]>=right for bx in outer),(outer,left,right)
            svg=app.drawing_svg();assert ' L ' in svg
            if '--emit-screenshots' in sys.argv:
                from check_desktop_design import screenshot
                Path('dist').mkdir(exist_ok=True);screenshot(app,Path('dist')/'v205-parallel-cables.png')
            assert not errors,errors
        finally:app.on_close()
    faulthandler.cancel_dump_traceback_later()
    print('PASS parallel cables: straight lines, outside labels, lone cable unchanged, SVG')


if __name__=='__main__':
    result=unittest.main(exit=False,verbosity=1).result
    if not result.wasSuccessful():
        print('::error::check_parallel_cables geometry failed');sys.exit(1)
    try:ui()
    except Exception as exc:
        import traceback;traceback.print_exc();print('::error::check_parallel_cables UI failed: '+type(exc).__name__);sys.exit(1)
