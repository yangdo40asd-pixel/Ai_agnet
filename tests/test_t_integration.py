"""T의 자료 수집→원문 사실→기존 답변/리포트 경계 검수. 실제 통신은 금지한다."""
from dataclasses import replace
from unittest.mock import Mock, patch
import hashlib
import unittest

from scripts.llm_fixture import synthetic_result
from src.agents.answer_quality import select_evidence, model_evidence
from src.agents.evidence import build_evidence, article_evidence
from src.agents.local_verification import turn_budget, current_turn_remaining
from src.agents.news_relevance import prepare_news, admitted_evidence
from src.agents.report import validate_report
from src.config import Settings
from src.data.disclosures import collect_disclosures
from src.data.news import fetch_news
from src.models import AppError, NewsArticle, SourceDocument, now_kst
from src.pipeline import analyze_selected_stock
from src.ui.app import _source_turn_budget


class TIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.result=synthetic_result()
        self.stock=self.result.financial.stock
        self.settings=Settings('fixture','fixture','id','secret')

    def test_news_scope_pipeline_preserves_original_question_and_official_snapshot(self):
        document=SourceDocument('NEWS_DART_20261027000001',self.stock.code,self.stock.name,'투자 공시',
            self.stock.name+' 투자 금액 300억원','OpenDART 공시 원문','https://example.com/disclosure',now_kst())
        question=self.stock.name+' 투자 공시 확인해 주세요'
        with patch('src.pipeline.fetch_news',return_value=self.result.news), patch(
                'src.data.disclosures.collect_disclosures',return_value=((document,),'ok')) as collect:
            result=analyze_selected_stock(self.result.theme,self.result.candidates,self.stock.code,
                settings=self.settings,previous=self.result,scope='news',question=question)
        collect.assert_called_once_with(self.stock,self.settings,question)
        self.assertEqual(result.source_documents,(document,))
        self.assertEqual(self.result.source_documents,())
        self.assertNotEqual(result.result_id,self.result.result_id)
        root=build_evidence(result)[document.evidence_id]
        self.assertEqual(root['validity'],'document_only')
        fact=root['structured_facts'][0]
        self.assertEqual(fact['source_hash'],hashlib.sha256(document.text.encode()).hexdigest())
        self.assertEqual(document.text[slice(*fact['span'])],fact['raw_text'])

    def test_basic_report_accepts_registered_number_rejects_wrong_item_and_other_article(self):
        article=NewsArticle(1,self.stock.name+' 주가 4.46% 상승','https://example.com/a',None,None)
        news=replace(self.result.news,articles=(article,))
        payload={'stock_name':self.stock.name,'price':self.result.financial.price,'per':self.result.financial.per,
                 'stock_comment':'','theme_trend':[{'text':'관련 보도에 따르면 주가는 4.46% 상승했습니다.','news_ids':[1]}],
                 'summary':None,'risk':None,'opportunity':None}
        self.assertIn('4.46%',validate_report(payload,self.result.financial,news).theme_trend[0].text)
        for statement in ('외국인 지분율은 4.46%입니다.','주가는 4.46% 하락했습니다.','주가는 99% 상승했습니다.'):
            wrong={**payload,'theme_trend':[{'text':statement,'news_ids':[1]}]}
            with self.subTest(statement=statement),self.assertRaises(AppError):
                validate_report(wrong,self.result.financial,news)

    def test_excerpt_scope_and_model_fact_filter_do_not_promote_source(self):
        article=NewsArticle(1,self.stock.name+' 투자 소식','https://example.com/a',None,None,
                            self.stock.name+' 투자 금액 300억원, 항목 미상 17배')
        raw=article_evidence(article,self.stock.name)
        shown=model_evidence({'NEWS_1':raw})['NEWS_1']
        self.assertEqual(shown['scope'],'article_excerpt')
        self.assertTrue(all(f['status']=='verified' for f in shown['structured_facts']))
        self.assertNotIn('source_hash',shown['structured_facts'][0])
        self.assertTrue(all(f['scope']=='article_excerpt' for f in shown['structured_facts']))

    def test_twenty_candidates_checked_in_bounded_batches_and_ids_kept(self):
        articles=tuple(NewsArticle(i,self.stock.name+' 투자 소식 '+str(i),'https://example.com/'+str(i),None,None) for i in range(1,21))
        news=replace(self.result.news,articles=articles)
        settings=replace(self.settings,ai_provider='local',local_model='fixture')
        def reply(settings,instruction,payload,max_tokens):
            return {'assessments':[{'id':a['id'],'relation':'company','subject_quote':self.stock.name,
                                   'support_quote':'투자 소식'} for a in payload['articles']]}
        with patch('src.agents.news_relevance._invoke',side_effect=reply) as invoke:
            checked=prepare_news(news,self.stock,'반도체',settings,context_id='T-batches-unique')
        self.assertEqual(invoke.call_count,4)
        self.assertEqual([a.article_id for a in checked.admission.assessments],list(range(1,21)))
        self.assertEqual(checked.articles,articles)
        evidence={f'NEWS_{a.id}':article_evidence(a,self.stock.name) for a in articles}
        selected=select_evidence('투자 뉴스 요약해 주세요',[],evidence,[],strict=True)
        self.assertEqual(len(selected.evidence),4)
        self.assertEqual(len(evidence),20)
        explicit=select_evidence('투자 뉴스 요약해 주세요',[],evidence,['NEWS_20'],strict=True)
        self.assertIn('NEWS_20',explicit.evidence)
        root={'scope':'official_disclosure','stock_code':self.stock.code,'source':'OpenDART 공시 원문'}
        self.assertIn('NEWS_DART_1',admitted_evidence({'NEWS_DART_1':root},checked.admission))
        self.assertNotIn('NEWS_DART_1',admitted_evidence({'NEWS_DART_1':{**root,'stock_code':'999999'}},checked.admission))

    def test_exhausted_shared_budget_stops_before_source_calls(self):
        settings=replace(self.settings,dart_api_key='fixture')
        with turn_budget(0),patch('src.data.news.requests.get') as news_get,patch(
                'src.data.disclosures.fetch_corp_codes') as mapping:
            self.assertEqual(fetch_news('반도체',self.stock.name,settings).status,'failed')
            self.assertEqual(collect_disclosures(self.stock,settings,'공시')[1],'source_budget')
        news_get.assert_not_called()
        mapping.assert_not_called()

    def test_ui_source_budget_and_nested_answer_share_deadline(self):
        settings=replace(self.settings,ai_provider='local',local_turn_timeout=23)
        with patch('src.ui.app.load_settings',return_value=settings),_source_turn_budget():
            outer=current_turn_remaining()
            with turn_budget(300):
                inner=current_turn_remaining()
            self.assertLessEqual(inner,outer)
            self.assertLess(inner,24)
        self.assertIsNone(current_turn_remaining())

    def test_official_deferred_candidates_retained_but_not_given_to_model(self):
        text=self.stock.name+' 알 수 없는 항목 17배\n'+self.stock.name+' 투자 금액 300억원'
        document=SourceDocument('NEWS_DART_FIXTURE',self.stock.code,self.stock.name,'투자 공시',text,
            'OpenDART 공시 원문','https://example.com/a',now_kst())
        raw=build_evidence(replace(self.result,source_documents=(document,)))[document.evidence_id]
        self.assertEqual([f['status'] for f in raw['structured_facts']],['deferred','verified'])
        visible=model_evidence({document.evidence_id:raw})[document.evidence_id]['structured_facts']
        self.assertEqual(len(visible),1)
        self.assertEqual(visible[0]['item'],'investment_amount')


if __name__=='__main__':
    unittest.main()
