"""U02: 카드·근거 배지·텍스트 전용·이전 저장 메시지 AppTest. 브라우저는 열지 않는다."""
import unittest

from streamlit.testing.v1 import AppTest
from src.models import AnswerBlock, ChatResponse
from src.ui.answer import response_fields


def render_fixture():
    import streamlit as st
    from src.ui.answer import render_answer
    for message in st.session_state['messages']:
        render_answer(message)


def reference(key='NEWS_1',url='https://news.example/one'):
    return {'id':key,'text':'가상 회사 소식','url':url,'source':'가상 언론','scope':'headline_only'}


def message_for(response):
    return {'text':response.text,'evidence':response.evidence,**response_fields(response)}


class IssueRenderingTests(unittest.TestCase):
    def render(self,messages):
        app=AppTest.from_function(render_fixture)
        app.session_state['messages']=messages
        app.run()
        self.assertEqual(len(app.exception),0)
        return app

    def test_card_headline_body_and_source_badge_are_linked_to_python_reference(self):
        response=ChatResponse('확인한 이슈입니다.',[reference()],blocks=(
            AnswerBlock('핵심 사건','관련 보도에 따르면 투자 계획이 발표됐습니다.',('NEWS_1',)),))
        app=self.render([message_for(response)])
        self.assertTrue(any(m.value.startswith('#### 핵심 사건') for m in app.markdown))
        self.assertTrue(any('투자 계획' in m.value for m in app.markdown))
        self.assertTrue(any('news\\.example' in c.value and 'https://news.example/one' in c.value for c in app.caption))
        self.assertEqual([link.proto.url for link in app.get('link_button')],['https://news.example/one'])
        self.assertNotIn('해석',[c.value for c in app.caption])

    def test_optional_implication_only_renders_when_present(self):
        response=ChatResponse('확인한 이슈입니다.',[reference()],blocks=(
            AnswerBlock('투자 계획','투자 계획이 보도됐습니다.',('NEWS_1',),'실제 집행 여부는 이후 자료로 확인할 수 있습니다.'),))
        app=self.render([message_for(response)])
        self.assertIn('해석',[c.value for c in app.caption])
        self.assertTrue(any('실제 집행 여부' in m.value for m in app.markdown))

    def test_text_only_summary_has_no_card_headings_or_empty_implication(self):
        response=ChatResponse('첫 요약입니다.\n둘째 요약입니다.\n셋째 요약입니다.',[reference()])
        app=self.render([message_for(response)])
        self.assertFalse(any(m.value.startswith('####') for m in app.markdown))
        self.assertTrue(any('첫 요약입니다.' in m.value for m in app.markdown))
        self.assertNotIn('해석',[c.value for c in app.caption])
        self.assertEqual(len(app.get('link_button')),1)

    def test_old_saved_title_text_message_is_still_rendered(self):
        old={'intro':'이전 답변입니다.','text':'이전 답변입니다.','evidence':[reference()],
             'blocks':[{'title':'이전 제목','text':'이전 본문입니다.','evidence_ids':['NEWS_1']}]}
        app=self.render([old])
        self.assertTrue(any('이전 제목' in m.value for m in app.markdown))
        self.assertTrue(any('이전 본문' in m.value for m in app.markdown))

    def test_invalid_source_url_cannot_become_badge_or_footer_link(self):
        response=ChatResponse('조회 결과입니다.',[reference(url='javascript:alert(1)')],blocks=(
            AnswerBlock('안전한 표시','보도 내용입니다.',('NEWS_1',)),))
        app=self.render([message_for(response)])
        self.assertEqual(len(app.get('link_button')),0)
        self.assertFalse(any('javascript:' in c.value for c in app.caption))

    def test_repeated_messages_and_notices_keep_layout_and_no_duplicate_keys(self):
        response=ChatResponse('한 문장 요약입니다.',[reference()],notices=('첨부 본문은 읽지 않았습니다.',))
        app=self.render([message_for(response),message_for(response)])
        self.assertEqual(sum('한 문장 요약' in m.value for m in app.markdown),2)
        self.assertEqual(sum('첨부 본문' in c.value for c in app.caption),2)
        self.assertEqual(response.text,'한 문장 요약입니다.')


if __name__=='__main__':
    unittest.main()
