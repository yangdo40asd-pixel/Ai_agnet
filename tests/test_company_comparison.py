"""비교의 기업/기간/기준/부분 결측·UI 스냅샷 보존 및 근거 충돌 대조."""
from dataclasses import replace
from decimal import Decimal
import unittest
from unittest.mock import patch

from src.models import AnnualFinancialSummary as Annual, StockCandidate, now_kst
from src.data.company_comparison import CompanyAnnuals, build_comparison
from src.agents.company_comparison import comparison_answer
from src.comparison_flow import collect_comparison, comparison_options, comparison_followup


def company(code='005930',name='가상회사A',*,basis='CFS',years=(2024,2025),revenues=(100,120),profits=(10,24),currency='KRW'):
    stock=StockCandidate(name,code,'KOSPI',code+'.KS')
    return CompanyAnnuals(stock,tuple(Annual(str(y),fs_div=basis,revenue=r*100000000,
        operating_income=p*100000000,currency=currency) for y,r,p in zip(years,revenues,profits)),
        'source-'+code,now_kst())


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.a=company();self.b=company('000660','가상회사B',revenues=(200,300),profits=(20,40))

    def test_matching_comparison_and_namespaced_provenance(self):
        s=build_comparison((self.a,self.b))
        self.assertFalse(s.reason)
        self.assertEqual((s.year,s.fs_div),(2025,'CFS'))
        self.assertEqual(len({m.evidence_id for m in s.metrics}),len(s.metrics))
        a=comparison_answer(s,'영업이익 증가율 비교')
        self.assertIn('40.00%p',a.text)
        self.assertIn('가상회사A',a.text); self.assertIn('가상회사B',a.text)
        self.assertEqual({e['stock_code'] for e in a.evidence},{'005930','000660'})
        self.assertEqual({e['source_result_id'] for e in a.evidence},{self.a.source_id,self.b.source_id})

    def test_margin_comparison_is_percentage_points(self):
        a=comparison_answer(build_comparison((self.a,self.b)),'영업이익률 비교')
        self.assertIn('6.67%p',a.text)
        self.assertIn('매출에서 영업이익으로 남기는 비중',a.text)

    def test_basis_mismatch_never_compares(self):
        self.assertTrue(build_comparison((self.a,replace(self.b,summaries=tuple(replace(s,fs_div='OFS') for s in self.b.summaries)))).reason)

    def test_different_years_or_missing_previous_never_compares(self):
        for b in (company('000660','B',years=(2023,2024)),replace(self.b,summaries=self.b.summaries[1:])):
            with self.subTest(b=b): self.assertTrue(build_comparison((self.a,b)).reason)

    def test_explicit_year_not_replaced_with_latest(self):
        self.assertTrue(build_comparison((self.a,self.b),year=2023).reason)

    def test_common_previous_period_is_selected_without_claiming_latest_each(self):
        a=replace(self.a,summaries=(*self.a.summaries,Annual('2026',revenue=14000000000,operating_income=3000000000)))
        self.assertEqual(build_comparison((a,self.b)).year,2025)

    def test_non_krw_duplicate_year_and_report_type_are_excluded(self):
        for changes in ({'currency':'USD'},{'reprt_code':'11013'}):
            b=replace(self.b,summaries=tuple(replace(s,**changes) for s in self.b.summaries))
            with self.subTest(changes=changes): self.assertTrue(build_comparison((self.a,b)).reason)
        self.assertTrue(build_comparison((self.a,replace(self.b,summaries=(*self.b.summaries,self.b.summaries[-1])))).reason)

    def test_same_company_or_three_companies_are_not_a_pair(self):
        for pair in ((self.a,self.a),(self.a,self.b,self.a)):
            with self.subTest(pair=pair): self.assertTrue(build_comparison(pair).reason)

    def test_failed_data_does_not_become_no_business_events(self):
        s=build_comparison((self.a,replace(self.b,status='failed')))
        self.assertTrue(s.reason); self.assertEqual(comparison_answer(s,'비교').evidence,[])

    def test_loss_and_zero_are_states_not_fabricated_growth(self):
        for profits in ((-10,20),(0,20),(-20,-10),(20,-10)):
            b=company('000660','B',profits=profits)
            with self.subTest(profits=profits):
                s=build_comparison((self.a,b));a=comparison_answer(s,'영업이익 증가율')
                self.assertIn('일반적인 증가율',a.text)
                self.assertTrue(any(m.change_pct is None for m in s.metrics if m.item=='operating_income'))

    def test_partial_missing_item_keeps_available_comparisons(self):
        b=replace(self.b,summaries=tuple(replace(s,revenue=None) for s in self.b.summaries))
        a=comparison_answer(build_comparison((self.a,b)),'실적 비교')
        self.assertIn('40.00%p',a.text);self.assertIn('제외',a.text)

    def test_disjoint_supported_metrics_are_not_a_successful_comparison(self):
        a=replace(self.a,summaries=tuple(replace(s,operating_income=None) for s in self.a.summaries))
        b=replace(self.b,summaries=tuple(replace(s,revenue=None) for s in self.b.summaries))
        snapshot=build_comparison((a,b))
        self.assertTrue(snapshot.reason)
        self.assertEqual(comparison_answer(snapshot,'실적 비교').evidence,[])

    def test_only_unsupported_net_income_does_not_enable_comparison(self):
        def net_income_only(company):
            return replace(company,summaries=tuple(replace(s,revenue=None,operating_income=None,net_income=100)
                                                   for s in company.summaries))
        self.assertTrue(build_comparison((net_income_only(self.a),net_income_only(self.b))).reason)

    def test_missing_basis_is_not_silently_prioritized_when_both_present(self):
        a=replace(self.a,summaries=(*self.a.summaries,*(replace(s,fs_div='OFS') for s in self.a.summaries)))
        b=replace(self.b,summaries=(*self.b.summaries,*(replace(s,fs_div='OFS') for s in self.b.summaries)))
        self.assertTrue(build_comparison((a,b)).reason)
        self.assertFalse(build_comparison((a,b),fs_div='OFS').reason)

    def test_scope_and_year_request_are_explicit(self):
        self.assertEqual(comparison_options('2024년 대비 2025년 별도 영업이익 비교')[0],{'year':2025,'fs_div':'OFS'})
        for q in ('2025년 3분기 비교','PER 비교','2023년과 2025년 비교','연결과 별도 비교','순이익 비교','재무건전성 비교'):
            with self.subTest(q=q): self.assertTrue(comparison_options(q)[1])

    def test_followup_does_not_swallow_new_company_or_year(self):
        for q in ('그럼 매출 증가율은?','영업이익률은?'):
            self.assertTrue(comparison_followup(q))
        for q in ('현대차 영업이익률은?','그럼 삼성전자만 보여줘','2023년 매출은?','PER은?'):
            self.assertFalse(comparison_followup(q))

    def test_explicit_year_collection_is_bounded_and_does_not_call_ai(self):
        from src.config import Settings
        settings=Settings('','','','')
        with patch('src.comparison_flow.collect_company_financials',side_effect=[
            {'status':'ok','annual_summaries':self.a.summaries},{'status':'ok','annual_summaries':self.b.summaries}]) as fetch:
            s,reason=collect_comparison((self.a.stock,self.b.stock),'2025년 영업이익 비교',settings)
        self.assertFalse(reason);self.assertFalse(s.reason)
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(fetch.call_args.kwargs['years'],('2024','2025'))


    def test_short_comparison_keeps_both_names_and_all_requested_leads(self):
        s=build_comparison((self.a,self.b))
        a=comparison_answer(s,'실적을 한 문장으로 비교해줘')
        self.assertEqual(len(__import__('re').findall(r'(?<!\d)\.(?!\d)',a.text)),1)
        self.assertIn('가상회사A',a.text);self.assertIn('가상회사B',a.text)
        self.assertIn('영업이익률',a.text)

    def test_official_link_only_from_valid_actual_receipt(self):
        a=replace(self.a,summaries=tuple(replace(x,rcept_no='20260310002820') for x in self.a.summaries))
        response=comparison_answer(build_comparison((a,self.b)),'영업이익 증가율 비교')
        self.assertTrue(response.evidence[0]['url'].startswith('https://dart.fss.or.kr/'))
        self.assertEqual(response.evidence[1]['url'],'')


class ComparisonUiTests(unittest.TestCase):
    def setUp(self):
        import test_user_flow
        self.flow=test_user_flow.UserFlowTests('runTest')
        self.flow.setUp();self.addCleanup(self.flow.doCleanups)
        self.a=company('005930','예시회사');self.b=company('247540','회사나',profits=(20,40))
        self.patcher=patch('src.comparison_flow.collect_company_financials',side_effect=lambda stock,*args,**kw:
            {'status':'ok','annual_summaries':self.a.summaries if stock.code=='005930' else self.b.summaries})
        self.fetch=self.patcher.start();self.addCleanup(self.patcher.stop)

    def test_chat_only_comparison_and_followup_preserve_dashboard(self):
        from scripts.llm_fixture import synthetic_result
        old=synthetic_result();self.flow.app.session_state['dashboard_result']=old
        self.flow.submit_theme('예시회사와 회사나 영업이익 증가율 비교해줘')
        state=self.flow.app.session_state
        self.assertFalse(self.flow.app.error)
        self.assertIn('40.00%p',state['chat_messages'][-1]['text'])
        snapshot=state['active_comparison'];self.assertEqual(state['dashboard_result'].result_id,old.result_id)
        self.assertEqual(len(state['canvases']) if 'canvases' in state else 0,0)
        self.flow.submit_theme('그럼 영업이익률은?')
        self.assertEqual(self.fetch.call_count,2)
        self.assertEqual(state['chat_messages'][-1]['comparison_id'],snapshot.comparison_id)
        self.assertIn('영업이익률',state['chat_messages'][-1]['text'])
        self.assertEqual(state['chat_request'].status,'completed')

    def test_scope_unsupported_does_not_collect_financials(self):
        self.flow.submit_theme('예시회사와 회사나 PER 비교해줘')
        self.assertFalse(self.flow.app.error)
        self.assertIn('아직 연결되지',self.flow.app.session_state['chat_messages'][-1]['text'])
        self.fetch.assert_not_called()

    def test_failed_new_comparison_does_not_reuse_previous_pair(self):
        self.flow.submit_theme('예시회사와 회사나 영업이익 증가율 비교해줘')
        first=self.flow.app.session_state['chat_messages'][-1]['comparison_snapshot']
        self.flow.submit_theme('예시회사와 회사나 2022년 영업이익 증가율 비교해줘')
        state=self.flow.app.session_state
        self.assertNotIn('active_comparison',state)
        self.assertEqual(state['chat_messages'][-3]['comparison_snapshot'],first)
        self.assertIn('확인하지 못했습니다',state['chat_messages'][-1]['text'])
