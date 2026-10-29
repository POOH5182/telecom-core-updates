"""V175: 도면에서 코어배정 on an 예외코어 no longer dead-ends. One question
「예외를 해제하고 바로 배정할까요?」: 아니오 changes nothing; 네 removes 예외코어
from that core ID (signal and splices stay) and opens the allocation."""
import tempfile
import unittest
from unittest.mock import patch

from check_after_plan import wf,LocalApp,update


def drawing(app):
    s=app.store
    n=[s.add_node('함체 '+str(i),i*200,100) for i in range(3)]
    s.backup_to(app.scenario_path('before'))
    c=[s.add_cable(n[i],n[i+1],'NEW'+str(i+1),'144C','신설') for i in range(2)]
    update(s,c[0],81,dict(core_id='3061686251',detail='예외 회선',signal='on'))
    s.set_cores_exception([(c[0],81)],True)
    return c


class Parent:
    def __init__(self):self.released=0
    def after_exception_release(self):self.released+=1


class ExceptionReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.app=LocalApp(self.temp.name);self.s=self.app.store
        self.c=drawing(self.app);self.source=(self.c[0],81)
    def tearDown(self):self.s.close();self.temp.cleanup()

    def exception(self):return wf.is_exception(wf.annotate(self.s,self.s.core(*self.source)))

    def factory(self,calls):
        def make(allow):
            calls.append(allow);return wf.IncrementalCoreAllocator(self.app,self.source,allow_excluded=allow)
        return make

    def test_exception_core_raises_typed_error(self):
        self.assertTrue(self.exception())
        for cls in (wf.ManualCoreAllocator,wf.IncrementalCoreAllocator):
            with self.subTest(cls=cls.__name__):
                with self.assertRaises(wf.ExceptionCompleteCore) as caught:cls(self.app,self.source)
                self.assertIsInstance(caught.exception,ValueError)
                self.assertEqual(caught.exception.core_id,'3061686251')
                self.assertIn('예외 완료',str(caught.exception))

    def test_no_keeps_exception_and_opens_nothing(self):
        calls=[];parent=Parent()
        with patch.object(wf.messagebox,'askyesno',return_value=False) as ask:
            self.assertIsNone(wf.open_allowing_excluded(parent,'도면에서 코어배정',self.factory(calls)))
        self.assertIn('예외를 해제하고 바로 배정할까요?',ask.call_args[0][1])
        self.assertEqual(calls,[False]);self.assertTrue(self.exception());self.assertEqual(parent.released,0)

    def test_yes_releases_exception_and_opens_allocation(self):
        calls=[];parent=Parent()
        with patch.object(wf.messagebox,'askyesno',return_value=True) as ask:
            service=wf.open_allowing_excluded(parent,'도면에서 코어배정',self.factory(calls))
        self.assertEqual(ask.call_count,1);self.assertEqual(calls,[False,False])
        self.assertEqual(service.core_id,'3061686251');self.assertFalse(self.exception())
        self.assertEqual(parent.released,1)
        row=self.s.core(*self.source);self.assertEqual(row['signal'],'on');self.assertEqual(row['detail'],'예외 회선')
        p=service.preview({**service.existing,self.c[1]:81});service.apply(p)
        self.assertEqual(self.s.core(self.c[1],81)['core_id'],'3061686251')

    def test_normal_core_opens_without_question(self):
        self.s.set_cores_exception([self.source],False)
        with patch.object(wf.messagebox,'askyesno') as ask:
            service=wf.open_allowing_excluded(Parent(),'도면에서 코어배정',self.factory([]))
        ask.assert_not_called();self.assertEqual(service.core_id,'3061686251')


if __name__=='__main__':unittest.main(verbosity=2)
