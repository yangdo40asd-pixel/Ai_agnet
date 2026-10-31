"""V01/V03: 올바른 해석과 비약의 통제 자료 검사. 실제 모델의 판정 정확도와 구분한다."""
from dataclasses import replace
from unittest.mock import patch
import unittest

from scripts.llm_fixture import synthetic_result
from src.agents.answer_quality import QUALITY_CHECKS, select_evidence
from src.agents.chat import _check_answer, answer_question
from src.agents.evidence import article_evidence, build_evidence
from src.agents.grounding import review_response
from src.agents.interpretation import classify_unit, decisions_for, apply_veto
from src.config import Settings
from src.models import AppError, AnswerBlock, ChatResponse, NewsArticle


NAME='가상검수회사'


def evidence_for(title):
    return {'NEWS_1':article_evidence(NewsArticle(1,title,'https://example.com/a',None,None),NAME)}


def unit(text,evidence,identifier='intro_0'):
    return {'id':identifier,'statement':text,'evidence':evidence}


def approve(settings,instruction,payload,*args,**kwargs):
    return {'checks':dict.fromkeys(QUALITY_CHECKS,True),'supported':True,'answers_question':True,
            'unit_reviews':[{'id':u['id'],'reason':'통제 승인','supported':True} for u in payload['review_units']]}


class FinancialInterpretationTests(unittest.TestCase):
    def setUp(self):
        self.settings=Settings('fixture','fixture','','')

    def test_tier1_shareholding_fact_and_necessary_limitation_are_allowed(self):
        evidence=evidence_for(NAME+' 보유 비율 불변, 담보계약 조건 변경')
        for text in ('이번에 바뀐 부분은 보유 비율이 아니라 담보계약 조건입니다.',
                     '지분율 불변만으로 거래가 없었다고 단정할 수 없습니다.',
                     '이번 공시만으로 주가 영향이 제한적이라고 판단할 수 없습니다.'):
            with self.subTest(text=text):
                decision=classify_unit(unit(text,evidence))
                self.assertFalse(decision.flags)

    def test_same_shareholding_cannot_imply_no_trade_or_price_or_control_stability(self):
        evidence=evidence_for(NAME+' 보유 비율 불변, 담보계약 조건 변경')
        for text in ('지분율이 그대로이므로 거래가 없었습니다.',
                     '주가 영향은 제한적일 것으로 해석됩니다. 다만 확인이 필요합니다.',
                     '지배구조가 완전히 안정됐습니다.'):
            with self.subTest(text=text):
                self.assertTrue(classify_unit(unit(text,evidence)).flags)

    def test_connected_caution_cannot_hide_positive_unsupported_claim(self):
        evidence=evidence_for(NAME+' 보유 비율 불변')
        for text in ('주가 영향은 제한적일 것으로 보이지만 결과는 확정할 수 없습니다.',
                     '앞으로 주가는 반드시 상승할 것이지만 실제 결과는 확정할 수 없습니다.',
                     '투자는 주가 상승에 기여할 가능성이 있지만 결과는 확정할 수 없습니다.'):
            with self.subTest(text=text):
                self.assertTrue(classify_unit(unit(text,evidence)).flags)

    def test_reported_actual_no_trade_is_not_rejected_as_ratio_inference(self):
        evidence=evidence_for(NAME+' 조회 기간 거래 없음 확인')
        self.assertFalse(classify_unit(unit('조회 기간 거래가 없었습니다.',evidence)).flags)

    def test_tier2_financial_relation_is_allowed_without_inventing_business_cause(self):
        evidence={'CMP':{'kind':'annual_comparison','text':'매출/이익 및 이익률 개선','status':'ok'}}
        self.assertEqual(classify_unit(unit('매출 확대와 함께 이익으로 남는 비중도 높아져 수익성이 개선됐습니다.',evidence)).tier,'T2')
        for text in ('판가 인상 덕분에 이익이 증가했습니다.','생산 효율 개선 때문에 수익성이 좋아졌습니다.',
                     '제품 믹스 개선의 영향으로 이익이 증가했습니다.'):
            with self.subTest(text=text):
                self.assertTrue(classify_unit(unit(text,evidence)).flags)

    def test_good_conditional_production_path_has_four_requirements(self):
        evidence=evidence_for(NAME+' 생산능력 확대 목적으로 신규 라인 투자 계획 발표')
        text='설비가 계획대로 가동되고 수요가 뒷받침되면 출하 확대에 기여할 수 있습니다.'
        decision=classify_unit(unit(text,evidence))
        self.assertEqual(decision.tier,'T3')
        self.assertFalse(decision.flags)
        self.assertEqual(len(decision.requirements),4)
        with_caution=classify_unit(unit(text+' 다만 실적 반영은 확정할 수 없습니다.',evidence))
        self.assertEqual(with_caution.tier,'T3')
        self.assertFalse(with_caution.flags)

    def test_possible_word_does_not_excuse_missing_fact_or_mechanism(self):
        for title,text in ((NAME+' 생산능력 확대 투자 계획','생산 확대에 기여할 수 있습니다.'),
                           (NAME+' 이사회 개최','설비가 가동되고 수요가 뒷받침되면 출하가 늘어날 수 있습니다.'),
                           (NAME+' 투자 계획','주가 상승에 기여할 수 있습니다.')):
            with self.subTest(title=title,text=text):
                self.assertTrue(classify_unit(unit(text,evidence_for(title))).flags)

    def test_plan_not_promoted_to_completed_or_orders(self):
        evidence=evidence_for(NAME+' 생산능력 확대 목적의 신규 생산라인 계획')
        for text in ('신규 생산라인 가동이 완료됐습니다.','고객 주문 확보 덕분에 매출이 증가했습니다.'):
            with self.subTest(text=text):
                self.assertTrue(classify_unit(unit(text,evidence)).flags)

    def test_headline_and_same_block_condition_can_share_context_without_excusing_false_fact(self):
        evidence=evidence_for(NAME+' 생산능력 확대 목적의 신규 라인 계획')
        units=[unit('생산 확대 가능성',evidence,'block_0_0'),
               unit('생산 확대에 기여할 수 있습니다.',evidence,'block_0_1'),
               unit('설비가 가동되고 수요가 뒷받침되는 경우입니다.',evidence,'block_0_2')]
        self.assertTrue(all(not decision.flags for decision in decisions_for(units)))
        units[1]=unit('생산라인 가동이 완료됐습니다.',evidence,'block_0_1')
        self.assertTrue(decisions_for(units)[1].flags)

    def test_conditions_from_different_issue_cannot_be_borrowed(self):
        evidence=evidence_for(NAME+' 생산능력 확대 목적의 신규 라인 계획')
        units=[unit('생산 확대에 기여할 수 있습니다.',evidence,'block_0_1'),
               unit('설비가 가동되고 수요가 뒷받침되는 경우입니다.',evidence,'block_1_1')]
        self.assertTrue(decisions_for(units)[0].flags)

    def test_market_conditional_path_needs_actual_trade_fact(self):
        text='같은 매수세가 지속되는 경우 매수 우위가 수급을 뒷받침할 수 있습니다.'
        valid=evidence_for(NAME+' 외국인 순매수 300억원')
        self.assertFalse(classify_unit(unit(text,valid)).flags)
        self.assertTrue(classify_unit(unit(text,evidence_for(NAME+' 보유 비율 불변'))).flags)

    def test_market_company_flow_periods_must_match(self):
        evidence={'MARKET':{'text':'시장 전체 외국인 순매도','period':'2026-10-20~2026-10-24'},
                  'COMPANY':{'text':NAME+' 외국인 순매수','period':'2026-10-20~2026-10-24'}}
        text='이 기간 시장에서는 순매도했지만 이 종목에는 순매수 자금이 들어와 다른 방향을 보였습니다.'
        self.assertFalse(decisions_for([unit(text,evidence)])[0].flags)
        evidence['COMPANY']['period']='2026-10-01~2026-10-03'
        self.assertIn('flow_period_mismatch',decisions_for([unit(text,evidence)])[0].flags)
        self.assertIn('flow_period_mismatch',decisions_for([unit(text+' 하지만 향후 주가는 알 수 없습니다.',evidence)])[0].flags)

    def test_document_relationship_not_promoted_to_current_valid_shareholder(self):
        evidence=evidence_for(NAME+' 주주 보고')
        evidence['NEWS_1']['relationship_proofs']=[{'validity':'document_only','quote':'문서에 기재된 주주 관계'}]
        self.assertTrue(classify_unit(unit('현재 주주 관계는 확인됐습니다.',evidence)).flags)
        self.assertFalse(classify_unit(unit('이 문서만으로 현재 주주 관계를 단정할 수 없습니다.',evidence)).flags)

    def test_reported_forecast_is_attribution_not_guaranteed_future(self):
        evidence=evidence_for('가상 증권사, '+NAME+' 주가 상승 전망')
        text='증권사는 주가가 상승할 것으로 전망했습니다.'
        self.assertFalse(classify_unit(unit(text,evidence)).flags)
        self.assertTrue(classify_unit(unit('앞으로 주가는 반드시 상승할 것입니다.',evidence)).flags)

    def test_code_veto_overrides_all_model_approvals_and_preserves_one_review_call(self):
        evidence=evidence_for(NAME+' 보유 비율 불변')
        response=ChatResponse('주가 영향은 제한적일 것으로 해석됩니다.',[dict(evidence['NEWS_1'],id='NEWS_1')],lead_evidence_ids=('NEWS_1',))
        with patch('src.agents.chat._invoke',side_effect=approve) as invoke:
            verdict,units=review_response(response,evidence,{'question':'무슨 의미입니까?'},self.settings,invoke)
        self.assertFalse(verdict['supported'])
        self.assertFalse(verdict['unit_reviews'][0]['supported'])
        self.assertEqual(invoke.call_count,1)

    def test_good_guard_decision_never_overrides_model_rejection_or_malformed_review(self):
        good=classify_unit(unit('보유 비율은 그대로입니다.',evidence_for(NAME+' 보유 비율 불변')))
        original={'supported':False,'checks':{}}
        self.assertIs(apply_veto(original,[good]),original)
        self.assertIsNone(apply_veto(None,[good]))

    def test_future_price_claim_with_registered_past_number_is_rejected_after_numeric_pass(self):
        evidence=evidence_for(NAME+' 주가 20% 상승')
        payload={'text':'앞으로 주가는 20% 상승할 것입니다.','evidence_ids':['NEWS_1'],'follow_up':'','blocks':[]}
        request={'answer_style':'plain','concept_reference':{},'question':'앞으로 어떻습니까?'}
        with patch('src.agents.chat._invoke',side_effect=approve),self.assertRaises(AppError) as caught:
            _check_answer(payload,evidence,[],synthetic_result(),request,self.settings,request['question'])
        self.assertEqual(caught.exception.code,'chat_grounding')

    def test_preliminary_results_answer_uses_available_values_not_old_annual_comparison(self):
        result=synthetic_result()
        article=NewsArticle(1,NAME+' 2026년 3분기 잠정 매출 400억원, 영업이익 60억원',
                            'https://example.com/preliminary',None,None)
        result=replace(result,news=replace(result.news,articles=(article,)))
        payload={'text':'잠정 매출은 400억원이며 영업이익은 60억원입니다. 확정 발표에서는 수치 변경 여부와 사업부별 매출과 이익 구성을 살펴볼 수 있습니다.',
                 'evidence_ids':['NEWS_1'],'follow_up':'','blocks':[]}
        def invoke(settings,instruction,request,*args,**kwargs):
            if request['task']=='chat_answer':
                self.assertEqual(set(request['evidence']),{'NEWS_1'})
                return payload
            return approve(settings,instruction,request,*args,**kwargs)
        with patch('src.agents.chat._invoke',side_effect=invoke):
            response=answer_question('실적 발표에서 무엇을 보면 돼?',result,[],self.settings)
        self.assertIn('잠정 매출은 400억원',response.text)
        self.assertNotIn('2025년',response.text)
        missing=select_evidence('2024년 1분기 잠정 실적은?',[],build_evidence(result),[],strict=True)
        self.assertEqual(set(missing.evidence),{'NEWS_STATUS'})
        combined=select_evidence('2024년 1분기 잠정 실적과 PER은?',[],build_evidence(result),['PER'],strict=True)
        self.assertEqual(set(combined.evidence),{'NEWS_STATUS','PER'})


if __name__=='__main__':
    unittest.main()
