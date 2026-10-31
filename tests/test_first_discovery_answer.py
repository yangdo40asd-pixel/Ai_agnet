"""첫 탐색의 근거 경계·선택 없는 대화·실패 보존을 검수한다. 기업/수치는 가상 자료다."""
from dataclasses import replace
from unittest.mock import patch
import unittest

import pandas as pd

from src.config import Settings
from src.models import AppError, CompanyBusinessProfile, CandidateDiscoveryResult, StockCandidate, now_kst
from src.data.business import collect_business_profiles, parse_business_table, has_direct_theme_support
from src.discovery_flow import enrich_discovery
from src.agents.discovery_answer import discovery_answer, business_evidence
from src.agents.request import route_message
from src.agents.answer_quality import QUALITY_CHECKS

STOCKS = (StockCandidate('가상제조', '000001', 'KOSPI', '000001.KS'),
          StockCandidate('가상장비', '000002', 'KOSDAQ', '000002.KQ'))
URL = 'https://kind.krx.co.kr/corpgeneral/corpList.do?method=loadInitPage'
PROFILES = (CompanyBusinessProfile('가상제조', '000001', '반도체 제조업', '반도체 메모리 제조', now_kst(), URL),
            CompanyBusinessProfile('가상장비', '000002', '기계 제조업', '반도체 후공정 장비 제조', now_kst(), URL))
SETTINGS = Settings('fixture', 'fixture', '', '')


def discovery():
    return CandidateDiscoveryResult('반도체', STOCKS, now_kst(), business_profiles=PROFILES)


def generated(payload):
    if payload.get('task') == 'chat_grounding_review':
        return {'checks': dict.fromkeys(QUALITY_CHECKS, True), 'supported': True, 'answers_question': True,
                'reason': '모의 검수', 'unit_reviews': [{'id': u['id'], 'supported': True, 'reason': '모의 근거 대조'} for u in payload['review_units']]}
    return {'text': '가상제조는 반도체 메모리를 제조하고 가상장비는 후공정 장비를 제조합니다. 제품 제조와 장비 제조라는 사업 차이가 있습니다.',
            'evidence_ids': list(payload['evidence']), 'follow_up': ''}


class BusinessSourceTests(unittest.TestCase):
    def test_new_business_area_is_not_captured_as_previous_discovery(self):
        from src.agents.discovery_answer import is_discovery_question
        self.assertFalse(is_discovery_question('방산 분야를 알아보고 싶은데', discovery()))
        self.assertTrue(is_discovery_question('그중 메모리 쪽만 알려줘', discovery()))
        self.assertTrue(is_discovery_question('메모리 분야를 설명해줘', discovery()))

    def test_code_and_name_must_both_match_and_duplicates_are_rejected(self):
        table = pd.DataFrame([{'회사명': '다른회사', '종목코드': '000001', '업종': '반도체', '주요제품': '반도체'},
                              {'회사명': '가상장비', '종목코드': '000002', '업종': '기계', '주요제품': '장비'},
                              {'회사명': '가상장비', '종목코드': '000002', '업종': '기계', '주요제품': '장비'}])
        with patch('src.data.business.load_business_table', return_value=(table, now_kst())):
            self.assertEqual(collect_business_profiles(STOCKS, SETTINGS), ())

    def test_official_table_schema_and_leading_zero(self):
        html = '<table><tr><th>회사명</th><th>종목코드</th><th>업종</th><th>주요제품</th></tr><tr><td>가상제조</td><td>000001</td><td>반도체</td><td>메모리</td></tr></table>'
        self.assertEqual(parse_business_table(html).iloc[0]['종목코드'], '000001')
        with self.assertRaises(AppError):
            parse_business_table('<table><tr><th>회사명</th></tr><tr><td>가상제조</td></tr></table>')

    def test_semiconductor_does_not_prove_ai_and_battery_synonym_is_bounded(self):
        self.assertTrue(has_direct_theme_support('반도체', PROFILES[0]))
        self.assertFalse(has_direct_theme_support('AI 반도체', PROFILES[0]))
        battery = replace(PROFILES[0], products='2차전지 제조')
        self.assertTrue(has_direct_theme_support('배터리', battery))
        self.assertFalse(has_direct_theme_support('배터리 소재', battery))

    def test_source_failure_preserves_previous_candidates_and_profiles(self):
        d = discovery()
        with patch('src.discovery_flow.collect_business_profiles', side_effect=AppError('business_failed', '실패')):
            result = enrich_discovery(d, SETTINGS)
        self.assertEqual(result.candidates, d.candidates)
        self.assertEqual(result.business_profiles, d.business_profiles)
        self.assertEqual(result.business_error, 'business_failed')

    def test_enrichment_preserves_old_profile_and_marks_source_scope(self):
        d = replace(discovery(), business_profiles=PROFILES[:1], batch_codes=('000002',))
        with patch('src.discovery_flow.collect_business_profiles', return_value=PROFILES[1:]):
            result = enrich_discovery(d, SETTINGS)
        self.assertEqual({p.stock_code for p in result.business_profiles}, {'000001', '000002'})
        self.assertTrue(all(s.association_status == 'source_supported' for s in result.candidates))


class FirstDiscoveryAnswerTests(unittest.TestCase):
    def invoke(self, settings, instruction, payload, *args, **kwargs):
        return generated(payload)

    def test_first_answer_uses_company_sources_and_shared_review(self):
        with patch('src.agents.discovery_answer._invoke', side_effect=self.invoke) as call:
            answer = discovery_answer('반도체 관련 종목 찾아줘', discovery(), SETTINGS, latest=True)
        self.assertEqual(call.call_count, 2)
        self.assertIn('사업 차이', answer.text)
        self.assertNotIn('선택해', answer.text)
        self.assertEqual({e['stock_code'] for e in answer.evidence}, {'000001', '000002'})
        self.assertFalse(any(e.get('answer_origin') for e in answer.evidence))

    def test_wrong_number_is_rejected_without_relaxing_shared_validator(self):
        wrong = {'text': '가상제조의 매출은 50% 증가했습니다.', 'evidence_ids': ['BUSINESS_000001'], 'follow_up': ''}
        with patch('src.agents.discovery_answer._invoke', return_value=wrong):
            answer = discovery_answer('관련 종목 찾아줘', discovery(), SETTINGS, latest=True)
        self.assertNotIn('50%', answer.text)
        self.assertTrue(all(e['answer_origin'] == 'verified_business_fallback' for e in answer.evidence))

    def test_robot_product_number_requires_exact_cited_source(self):
        from src.agents.chat import validate_answer
        evidence = {'BUSINESS_000001': {'id': 'BUSINESS_000001', 'text': '가상제조 · 주요제품: 4족보행로봇',
                                       'url': URL, 'kind': 'company_profile', 'scope': 'company_profile'}}
        payload = {'text': '가상제조의 제품에는 4족보행로봇이 있습니다.', 'evidence_ids': ['BUSINESS_000001'], 'follow_up': ''}
        self.assertIn('4족보행로봇', validate_answer(payload, evidence)[0])
        for bad in ('가상제조의 제품에는 6족보행로봇이 있습니다.', '가상제조의 이익률은 4%입니다.'):
            with self.assertRaises(AppError):
                validate_answer(dict(payload, text=bad), evidence)

    def test_semantic_rejection_cannot_be_treated_as_success(self):
        def unsupported(settings, instruction, payload, *a, **kw):
            result = generated(payload)
            if payload.get('task') == 'chat_grounding_review':
                result['supported'] = False
            return result
        with patch('src.agents.discovery_answer._invoke', side_effect=unsupported):
            answer = discovery_answer('관련 종목 찾아줘', discovery(), SETTINGS, latest=True)
        self.assertTrue(all(e.get('answer_origin') for e in answer.evidence))

    def test_no_source_never_invokes_model_or_erases_candidate_names(self):
        d = replace(discovery(), business_profiles=(), business_error='business_failed')
        with patch('src.agents.discovery_answer._invoke') as llm:
            answer = discovery_answer('관련 종목 찾아줘', d, SETTINGS)
        llm.assert_not_called()
        self.assertIn('가상제조', answer.text)
        self.assertIn('조회가 실패', answer.text)
        self.assertNotIn('선택해', answer.text)

    def test_partial_source_keeps_confirmed_business_and_missing_company(self):
        d = replace(discovery(), business_profiles=PROFILES[:1])
        with patch('src.agents.discovery_answer._invoke', side_effect=AppError('ai_local_busy', '대기')):
            answer = discovery_answer('관련 종목 찾아줘', d, SETTINGS)
        self.assertIn('반도체 메모리', answer.text)
        self.assertIn('가상장비', answer.text)
        self.assertEqual(len(answer.evidence), 1)

    def test_named_followup_does_not_use_another_company_profile(self):
        with patch('src.agents.discovery_answer._invoke', side_effect=AppError('ai_local_busy', '대기')):
            answer = discovery_answer('가상장비는 어떤 제품을 만들어?', discovery(), SETTINGS)
        self.assertEqual([e['stock_code'] for e in answer.evidence], ['000002'])
        self.assertNotIn('가상제조', answer.text)

    def test_stock_name_code_mismatch_is_not_accepted_as_business_evidence(self):
        d = replace(discovery(), business_profiles=(replace(PROFILES[0], stock_name='다른회사'),))
        self.assertEqual(business_evidence(d), {})

    def test_business_difference_without_selection_bypasses_model_router(self):
        with patch('src.agents.request._invoke') as llm:
            intent = route_message('이 기업들은 서로 뭐가 달라?', discovery(), None, [], SETTINGS)
        self.assertEqual(intent.action, 'discovery_answer')
        llm.assert_not_called()
        self.assertEqual(route_message('그 기업들 실적 비교해줘', discovery(), None, [], SETTINGS).action, 'comparison_query')

    def test_new_company_business_question_does_not_reuse_old_candidates(self):
        from src.agents.discovery_answer import is_discovery_question
        self.assertFalse(is_discovery_question('다른제조는 어떤 제품을 만들어?', discovery()))

    def test_generation_focus_keeps_source_and_unrelated_products_out_of_prompt(self):
        from src.agents.discovery_answer import generation_evidence
        d = replace(discovery(), business_profiles=(replace(PROFILES[0], products='휴대폰 제조,반도체 메모리 제조/부동산 임대'),))
        original = business_evidence(d)
        focused = generation_evidence(original)
        self.assertEqual(focused['BUSINESS_000001']['products'], '반도체 메모리 제조')
        self.assertIn('부동산', original['BUSINESS_000001']['products'])

    def test_business_area_uses_actual_product_words_and_no_selection(self):
        with patch('src.agents.discovery_answer._invoke', side_effect=AppError('ai_local_busy', '대기')):
            answer = discovery_answer('메모리 쪽만 설명해줘', discovery(), SETTINGS)
        self.assertEqual([e['stock_code'] for e in answer.evidence], ['000001'])
        self.assertNotIn('가상장비', answer.text)
        self.assertEqual(route_message('메모리 쪽만 설명해줘', discovery(), None, [], SETTINGS).action, 'discovery_answer')

    def test_unconfirmed_area_is_not_filled_with_other_candidates(self):
        with patch('src.agents.discovery_answer._invoke') as llm:
            answer = discovery_answer('소재 분야만 설명해줘', discovery(), SETTINGS)
        llm.assert_not_called()
        self.assertIn('근거를 확보하지 못했습니다', answer.text)
        self.assertFalse(answer.evidence)


class FirstDiscoveryUiTests(unittest.TestCase):
    def setUp(self):
        import test_user_flow
        self.flow = test_user_flow.UserFlowTests('runTest')
        self.flow.setUp()
        self.addCleanup(self.flow.doCleanups)

    def test_business_explanation_then_followup_without_selection_or_canvas(self):
        from src.models import ChatResponse
        profiles = (replace(PROFILES[0], stock_name='예시회사', stock_code='005930'),)
        with patch('src.discovery_flow.collect_business_profiles', return_value=profiles), patch(
                'src.agents.discovery_answer.discovery_answer', return_value=ChatResponse('확인한 사업 차이를 설명합니다.', [])) as answer:
            self.flow.submit_theme('반도체 관련 종목 찾아줘')
            app = self.flow.app
            self.assertIsNone(app.session_state['selected_code'])
            self.assertNotIn('canvases', app.session_state)
            self.assertFalse(any('분석할 종목을 선택' in e.value for e in app.info))
            self.assertFalse(any(e.key == 'candidate_selector' for e in app.selectbox))
            self.assertTrue(any('개별 기업' in e.value for e in app.caption))
            self.flow.submit_theme('이 기업들은 서로 뭐가 달라?')
            self.assertEqual(answer.call_count, 2)
            self.assertEqual(len(app.session_state['chat_messages']), 4)
            self.assertEqual(app.session_state['chat_request'].status, 'completed')
            self.flow.ticker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
