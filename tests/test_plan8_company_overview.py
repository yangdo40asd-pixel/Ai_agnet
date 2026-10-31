"""기업 종합 질문의 목적·누락 자료·실제 잘못된 금액의 거절을 함께 보호한다."""
import json
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from src.agents.question_goal import question_goal
from src.agents.request import route_message
from src.agents.chat import validate_answer, _verified_fallback
from src.agents.company_overview import comparison_fallback
from src.analysis_flow import needs_data
from src.agents.answer_quality import select_evidence
from src.agents.evidence import build_evidence
from src.diagnostics import capture_validation_events, record_validation_failure
from src.models import AppError, CandidateDiscoveryResult, now_kst
from src.config import Settings
from scripts.llm_fixture import synthetic_result


class CompanyOverviewGoalTests(unittest.TestCase):
    def test_overview_and_specific_questions_have_distinct_goals(self):
        for question in ('삼성SDI는 어때?', '이 회사는 어때?', '삼성전자를 분석해줘'):
            self.assertTrue(question_goal(question).company_overview)
        for question in ('삼성SDI PER은 어때?', '이 종목 실적은 어때?', '최근 뉴스는 어때?',
                         '왜 영업이익이 줄었어?', '그럼 내년은?', '방금 답변 요약해줘'):
            self.assertFalse(question_goal(question).company_overview)

    def test_overview_keeps_target_and_all_scope_without_model(self):
        result=synthetic_result();stock=result.financial.stock
        d=CandidateDiscoveryResult('테마',(stock,),now_kst())
        with patch('src.agents.request._invoke') as model:
            i=route_message(stock.name+'는 어때?',d,stock.code,[],Settings('test','test','',''))
        self.assertEqual((i.action,i.scope,i.purpose),('answer','all','company_overview'))
        self.assertEqual(i.code,stock.code);model.assert_not_called()

    def test_missing_company_data_is_requested_after_price_only(self):
        r=synthetic_result()
        empty=replace(r,section_status={'dart':'not_collected'},news=replace(r.news,status='not_collected'))
        self.assertTrue(needs_data(empty,'all','이 회사는 어때?',now=now_kst(),dart_enabled=True))
        full=replace(r,section_status={'dart':'ok'},news=replace(r.news,status='ok'))
        self.assertFalse(needs_data(full,'all','이 회사는 어때?',now=now_kst(),dart_enabled=True))

    def test_missing_credentials_do_not_trigger_endless_collection(self):
        r=synthetic_result();r=replace(r,section_status={'dart':'not_collected'},news=replace(r.news,status='ok'))
        self.assertFalse(needs_data(r,'all','이 회사는 어때?',now=now_kst(),dart_enabled=False))

    def test_overview_selection_retains_comparisons_and_price(self):
        selected=select_evidence('이 회사는 어때?',[],build_evidence(synthetic_result()),[],strict=True)
        self.assertEqual(selected.reason,'overview')
        self.assertTrue(any(v.get('kind')=='annual_comparison' for v in selected.evidence.values()))
        self.assertIn('PRICE',selected.evidence)
        self.assertTrue(any('핵심 상황' in s for s in selected.requirements))


class OverviewFallbackTests(unittest.TestCase):
    def facts(self,old='100',new='-50'):
        return {'CMP_OP':{'kind':'annual_comparison','item':'operating_income','status':'ok',
            'years':[2024,2025],'fs_div':'CFS','stock_code':'123456','previous':old,'current':new,
            'text':'영업이익: 100원 → -50원 (적자 전환)'}}

    def test_loss_transition_preserves_financial_meaning_and_provenance(self):
        text,refs=comparison_fallback(self.facts())
        self.assertIn('적자로 전환',text);self.assertIn('본업',text)
        self.assertEqual(refs[0]['answer_origin'],'verified_fallback')
        self.assertEqual(refs[0]['stock_code'],'123456')

    def test_profit_and_loss_changes_are_not_always_positive(self):
        for old,new,word in (('-100','50','흑자로 전환'),('-100','-50','손실 규모는 줄'),
                             ('-50','-100','손실 규모가 커'),('100','50','영업이익이 줄')):
            self.assertIn(word,comparison_fallback(self.facts(old,new))[0])

    def test_mixed_companies_or_accounting_bases_are_not_merged(self):
        for field,value in (('stock_code','654321'),('fs_div','OFS'),('years',[2023,2024])):
            facts=self.facts();facts['OTHER']={**facts['CMP_OP'],field:value}
            self.assertIsNone(comparison_fallback(facts))

    def test_unverified_or_nonfinite_facts_are_not_used(self):
        for field,value in (('status','missing'),('current','NaN'),('current','garbage')):
            facts=self.facts();facts['CMP_OP'][field]=value
            self.assertIsNone(comparison_fallback(facts))

    def test_overview_limited_answer_keeps_financials_not_only_price(self):
        response=_verified_fallback('이 회사는 어때?',self.facts(),{'question_goal':'company_overview'})
        self.assertIn('적자로 전환',response[0])
        self.assertEqual(response[1][0]['id'],'CMP_OP')


class ValidationDiagnosticTests(unittest.TestCase):
    def test_opt_in_capture_is_private_and_does_not_mutate_payload(self):
        events=[];payload={'text':'답변','api_key':'secret','nested':{'authorization':'private','text':'근거'}}
        error=AppError('chat_numbers','오류')
        with capture_validation_events(events.append):
            record_validation_failure('chat_answer',payload,{},error,question='질문')
        self.assertNotIn('secret',str(events));self.assertNotIn('private',str(events))
        events[0]['response']['text']='변경'
        self.assertEqual(payload['text'],'답변')
        record_validation_failure('chat_answer',payload,{},error)
        self.assertEqual(len(events),1)

    def test_sink_failure_does_not_change_answer_validation(self):
        with capture_validation_events(lambda event: (_ for _ in ()).throw(RuntimeError())):
            record_validation_failure('chat_answer',{}, {},AppError('chat_numbers','오류'))

    def test_real_wrong_amount_responses_remain_rejected(self):
        cases=json.loads((Path(__file__).parent/'fixtures'/'plan8_rejected_amounts.json').read_text(encoding='utf8'))
        for case in cases:
            with self.subTest(text=case['response']['text'][:60]),self.assertRaises(AppError) as caught:
                validate_answer({k:v for k,v in case['response'].items() if k in {'text','evidence_ids','follow_up'}},case['evidence'])
            self.assertEqual(caught.exception.code,'chat_numbers')


class OverviewFollowupAndLiteralTests(unittest.TestCase):
    def test_why_inherits_financial_focus_from_used_evidence(self):
        evidence=build_evidence(synthetic_result())
        refs=[dict(v,id=k) for k,v in evidence.items() if v.get('kind')=='annual_comparison']
        messages=[{'role':'user','text':'이 회사는 어때?'},
                  {'role':'assistant','text':'확인된 실적의 의미를 설명했습니다.','evidence':refs}]
        selected=select_evidence('왜 그런 거야?',messages,evidence,[],strict=True)
        self.assertEqual(selected.reason,'financials')
        self.assertTrue(any('인과' in x for x in selected.requirements))

    def test_why_without_financial_refs_is_not_forced_into_financials(self):
        selected=select_evidence('왜 그런 거야?',[{'role':'assistant','text':'일반 개념입니다.'}],{},[],strict=True)
        self.assertNotEqual(selected.reason,'financials')

    def test_exact_source_industry_terms_are_not_financial_numbers(self):
        from src.agents.literal_numbers import mask_literal_source_numbers
        evidence={'NEWS_1':{'url':'https://example.com','text':'배터리3사 실적과 2차전지 동향'}}
        self.assertNotRegex(mask_literal_source_numbers('배터리 3사의 2차전지 동향',evidence),r'\d')
        for text in ('배터리 4사','자동차 3사','3차전지','200억원'):
            self.assertRegex(mask_literal_source_numbers(text,evidence),r'\d')

    def test_source_free_industry_numbers_remain_unverified(self):
        from src.agents.literal_numbers import mask_literal_source_numbers
        self.assertIn('2',mask_literal_source_numbers('2차전지',{}))


class LossTransitionNumberTests(unittest.TestCase):
    def evidence(self):
        case=json.loads((Path(__file__).parent/'fixtures'/'plan8_rejected_amounts.json').read_text(encoding='utf8'))[0]
        return case['evidence']

    def test_exact_signed_transition_pair_is_verified(self):
        from src.agents.financial_numbers import mask_verified_comparisons
        for text in ('영업이익은 3,633.0억원에서 -17,223.6억원으로 적자 전환되었습니다.',
                     '영업이익은 3,633.0억 원에서 -17,223.6억 원으로 적자 전환했습니다.'):
            self.assertNotRegex(mask_verified_comparisons(text,self.evidence()),r'\d')

    def test_wrong_value_sign_item_or_state_is_rejected(self):
        from src.agents.financial_numbers import mask_verified_comparisons
        for text in ('영업이익은 363.3억원에서 -17,223.6억원으로 적자 전환했습니다.',
                     '영업이익은 3,633.0억원에서 -1,722.3억원으로 적자 전환했습니다.',
                     '영업이익은 3,633.0억원에서 17,223.6억원으로 적자 전환했습니다.',
                     '당기순이익은 3,633.0억원에서 -17,223.6억원으로 적자 전환했습니다.',
                     '영업이익은 3,633.0억원에서 -17,223.6억원으로 흑자 전환했습니다.'):
            with self.subTest(text=text),self.assertRaises(AppError):
                mask_verified_comparisons(text,self.evidence())

    def test_wrong_comparison_year_remains_rejected(self):
        from src.agents.financial_numbers import mask_verified_comparisons
        text='2023년 대비 2025년 영업이익은 3,633.0억원에서 -17,223.6억원으로 적자 전환했습니다.'
        with self.assertRaises(AppError):mask_verified_comparisons(text,self.evidence())

    def test_retry_feedback_does_not_invent_rates_policy(self):
        from src.agents.chat import _apply_retry_feedback
        request={'question':'삼성SDI는 어때?','review_profile':'scoped-v1'}
        _apply_retry_feedback(request,{},AppError('chat_comparison_style','중복'))
        self.assertNotIn('comparison_style=rates입니다',request['validation_feedback'])
        self.assertIn('자리표시자는 유지',request['validation_feedback'])


if __name__=='__main__':unittest.main()
