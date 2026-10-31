"""테마 확장·집합 참조·여러 기업의 동일 기준 비교를 연결한다."""
from dataclasses import replace
from unittest.mock import patch
import unittest
import pandas as pd
from src.models import CandidateDiscoveryResult, StockCandidate, now_kst,AppError
from src.config import Settings
from src.pipeline import discover_theme_candidates
from src.agents.report import propose_candidates
from src.agents.request import route_message
from src.agents.discovery_context import collective_comparison,expansion_request
from src.data.company_comparison import build_comparison
from src.agents.company_comparison import comparison_answer
from src.ui.state import store_candidate_extension
from src.agents.output_contract import response_format
import test_company_comparison as fixture

STOCKS=tuple(StockCandidate('회사'+str(i),f'{i:06d}','KOSPI',f'{i:06d}.KS') for i in range(1,7))
SETTINGS=Settings('fixture','fixture','','')

def discovery():return CandidateDiscoveryResult('배터리',STOCKS[:3],now_kst())


class DiscoveryContextTests(unittest.TestCase):
    def test_more_uses_current_theme_without_model_or_selection(self):
        for q in ('관련주 더 보여줘','관련 종목 더 알려줘','다른 후보도 있어?'):
            with patch('src.agents.request._invoke') as llm:
                intent=route_message(q,discovery(),STOCKS[0].code,[],SETTINGS)
                self.assertEqual((intent.action,intent.theme),('expand','배터리'));llm.assert_not_called()

    def test_more_without_theme_asks_once_and_different_explicit_theme_is_new(self):
        self.assertEqual(route_message('관련주 더 보여줘',None,None,[],SETTINGS).action,'clarify')
        i=route_message('반도체 관련주 더 보여줘',discovery(),None,[],SETTINGS)
        self.assertEqual((i.action,i.theme),('discover','반도체'))

    def test_news_or_negative_or_generic_more_does_not_expand(self):
        for q in ('다른 회사 뉴스 알려줘','관련주 더 보여주지 마','관련주 말고 실적 알려줘','더 설명해줘'):
            self.assertFalse(expansion_request(q))

    def test_collective_comparison_keeps_all_latest_codes(self):
        with patch('src.agents.request._invoke') as llm:
            i=route_message('그 기업들 실적 비교해줘',discovery(),STOCKS[0].code,[],SETTINGS)
        self.assertEqual(i.action,'comparison_query');self.assertIsNone(i.entities.primary_stock)
        self.assertEqual(i.entities.mentioned_stocks,STOCKS[:3]);llm.assert_not_called()

    def test_two_of_three_are_not_arbitrarily_chosen(self):
        i=route_message('그 두 기업 실적 비교해줘',discovery(),None,[],SETTINGS)
        self.assertEqual(i.action,'clarify')
        self.assertIsNone(collective_comparison('이 회사 PER 비교해줘',discovery(),[]))

    def test_latest_batch_and_all_candidates_are_distinct(self):
        d=replace(discovery(),candidates=STOCKS,batch_codes=tuple(s.code for s in STOCKS[3:]))
        self.assertEqual(collective_comparison('그 기업들 비교해줘',d,[]),STOCKS[3:])
        self.assertEqual(collective_comparison('지금까지 소개한 기업들 비교해줘',d,[]),STOCKS)

    def test_explicit_company_overrides_collective_reference(self):
        i=route_message('그중 회사2는 어때?',discovery(),STOCKS[0].code,[],SETTINGS)
        self.assertEqual(i.code,STOCKS[1].code);self.assertEqual(i.action,'select')


class CandidateExtensionTests(unittest.TestCase):
    def setUp(self):self.listing=pd.DataFrame([{'Name':s.name,'Code':s.code,'Market':s.market} for s in STOCKS])

    def test_generation_accepts_fewer_new_names_and_schema_has_same_bounds(self):
        with patch('src.agents.report._invoke',return_value={'stocks':['회사4']}) as llm:
            self.assertEqual(propose_candidates('배터리',SETTINGS,excluded_names=('회사1',)),('회사4',))
        payload=llm.call_args.args[2]
        schema=response_format(payload,'fixture',schema_supported=True)['json_schema']['schema']['properties']['stocks']
        self.assertEqual((schema['minItems'],schema['maxItems']),(1,3))
        with patch('src.agents.report._invoke',return_value={'stocks':['회사1']}),self.assertRaises(AppError):
            propose_candidates('배터리',SETTINGS,excluded_names=('회사1',))

    def test_extension_is_accumulated_and_old_codes_are_excluded(self):
        old=discovery()
        with patch('src.pipeline.propose_candidates',return_value=('회사4','회사5')) as propose,patch('src.pipeline.load_listing',return_value=self.listing):
            new=discover_theme_candidates('배터리',settings=SETTINGS,previous=old)
        self.assertEqual(new.candidates,STOCKS[:5]);self.assertEqual(new.latest_candidates,STOCKS[3:5])
        self.assertEqual(propose.call_args.kwargs['excluded_names'],tuple(s.name for s in old.candidates))

    def test_no_new_or_changed_theme_preserves_old_result(self):
        old=discovery()
        with patch('src.pipeline.propose_candidates',return_value=('회사1',)),patch('src.pipeline.load_listing',return_value=self.listing):
            result=discover_theme_candidates('배터리',settings=SETTINGS,previous=old)
        self.assertTrue(result.failure_reason);self.assertEqual(result.candidates,old.candidates)
        with self.assertRaises(AppError):discover_theme_candidates('반도체',settings=SETTINGS,previous=old)

    def test_state_extension_does_not_reset_current_analysis(self):
        marker=object();state={'candidate_result':discovery(),'selected_code':STOCKS[0].code,'dashboard_result':marker,'chat_messages':['old'],'canvases':['saved']}
        new=replace(discovery(),candidates=STOCKS,batch_codes=tuple(s.code for s in STOCKS[3:]))
        store_candidate_extension(state,new)
        self.assertIs(state['dashboard_result'],marker);self.assertEqual(state['selected_code'],STOCKS[0].code)
        self.assertEqual(state['chat_messages'],['old']);self.assertEqual(state['canvases'],['saved'])


class GroupComparisonTests(unittest.TestCase):
    def setUp(self):
        self.companies=(fixture.company('000001','가상A'),fixture.company('000002','가상B',revenues=(100,150)),fixture.company('000003','가상C',profits=(10,-5)))

    def test_all_companies_are_compared_with_unique_source_ids(self):
        s=build_comparison(self.companies);a=comparison_answer(s,'실적 비교해줘')
        self.assertFalse(s.reason)
        self.assertEqual({e['stock_code'] for e in a.evidence},{'000001','000002','000003'})
        self.assertEqual(len({e['id'] for e in a.evidence}),len(a.evidence))
        self.assertIn('가상B',a.text);self.assertIn('적자',a.text)

    def test_common_basis_and_period_must_match_every_company(self):
        for third in (fixture.company('000003','가상C',basis='OFS'),fixture.company('000003','가상C',years=(2022,2023)),replace(self.companies[2],status='failed')):
            s=build_comparison((*self.companies[:2],third));self.assertTrue(s.reason);self.assertFalse(s.metrics)

    def test_duplicate_company_and_unbounded_group_are_rejected(self):
        for cs in ((*self.companies,self.companies[0]),tuple(fixture.company(f'{i:06d}',str(i)) for i in range(1,8))):
            self.assertTrue(build_comparison(cs).reason)

    def test_one_sentence_comparison_keeps_all_source_companies(self):
        a=comparison_answer(build_comparison(self.companies),'실적을 한 문장으로 비교해줘')
        self.assertEqual({e['stock_code'] for e in a.evidence},{'000001','000002','000003'})
        self.assertNotIn('\n',a.text)


class DiscoveryUiFlowTests(unittest.TestCase):
    def setUp(self):
        import test_user_flow
        self.flow=test_user_flow.UserFlowTests('runTest');self.flow.setUp();self.addCleanup(self.flow.doCleanups)
        self.companies=(fixture.company('005930','예시회사'),fixture.company('247540','회사나'),fixture.company('000660','회사다'))
        self.d=CandidateDiscoveryResult('배터리',tuple(c.stock for c in self.companies),now_kst())
        self.flow.app.session_state['candidate_result']=self.d
        self.flow.app.session_state['chat_messages']=[{'role':'assistant','text':'후보를 소개합니다.','discovery':self.d}]

    def test_more_preserves_history_and_does_not_start_stock_analysis(self):
        added=StockCandidate('회사라','111111','KOSPI','111111.KS')
        d=replace(self.d,candidates=(*self.d.candidates,added),batch_codes=(added.code,))
        with patch('src.pipeline.discover_theme_candidates',return_value=d) as discover,patch('src.pipeline.analyze_selected_stock') as collect:
            self.flow.submit_theme('관련주 더 보여줘')
        state=self.flow.app.session_state
        self.assertEqual(state['candidate_result'],d);self.assertEqual(len(state['chat_messages']),3)
        self.assertEqual(discover.call_args.kwargs['previous'],self.d);collect.assert_not_called()
        self.assertEqual(state['chat_request'].status,'completed')
        self.assertIn('회사라',state['chat_messages'][-1]['text'])

    def test_collective_group_routes_through_real_comparison_without_ai(self):
        lookup={c.stock.code:c for c in self.companies}
        with patch('src.comparison_flow.collect_company_financials',side_effect=lambda stock,*a,**kw:{'status':'ok','annual_summaries':lookup[stock.code].summaries}) as fetch:
            self.flow.submit_theme('그 기업들 실적 비교해줘')
        state=self.flow.app.session_state
        self.assertEqual(fetch.call_count,3);self.assertFalse(self.flow.app.error)
        self.assertEqual({c.stock.code for c in state['active_comparison'].companies},set(lookup))
        self.assertEqual(state['chat_request'].status,'completed')
        self.flow.llm.invoke.assert_not_called()


if __name__=='__main__':unittest.main()
