"""V173: 선택번호배정 저장 asks a short 저장하시겠습니까? 네/아니오; Enter or Space = 네, Esc = 아니오."""
import tkinter as tk
import traceback
from check_field_survey import wf


def ask(root,action):
    review=wf.ManualAllocationReview(root,'코어ID: CORE-1\n\n추가할 함체 접속\n없음');root.update()
    action(review);root.update()
    return review.result,review


def main():
    root=tk.Tk();root.geometry('300x200+40+40')
    try:
        result,review=ask(root,lambda r:None)
        if review.winfo_exists():
            texts=[str(w.cget('text')) for w in review.winfo_children()[0].winfo_children()]
            assert '저장하시겠습니까?' in texts,texts
            assert review.yes_button.cget('text')=='네' and review.no_button.cget('text')=='아니오'
            assert review.detail is None
            review.toggle_detail();root.update()
            assert review.detail is not None and '코어ID: CORE-1' in review.detail.get('1.0','end')
            review.toggle_detail();root.update();assert not review.detail.master.winfo_ismapped()
            review.destroy()
        for key in ('<Return>','<KP_Enter>','<space>'):
            for target in ('yes_button','no_button','detail_button',None):
                def press(r):
                    widget=getattr(r,target) if target else r
                    widget.focus_force();r.update();widget.event_generate(key,when='now')
                result,_=ask(root,press)
                assert result is True,(key,target)
        assert ask(root,lambda r:(r.focus_force(),r.update(),r.event_generate('<Escape>',when='now')))[0] is False
        assert ask(root,lambda r:r.no_button.invoke())[0] is False
        assert ask(root,lambda r:r.yes_button.invoke())[0] is True
        # A repeated key after the window closed must not fail.
        result,review=ask(root,lambda r:r.confirm());review.confirm();assert result is True
        print('PASS save confirm yes/no')
    except Exception:
        print('::error::save confirm check failed: '+traceback.format_exc().replace('\n',' | '));raise
    finally:root.destroy()


if __name__=='__main__':main()
