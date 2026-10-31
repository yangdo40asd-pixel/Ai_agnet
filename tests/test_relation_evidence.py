"""V02: 공식 관계 역할/원문 귀속과 기사 사건 관련성을 분리한다. 공시는 모두 가상이다."""
from dataclasses import replace
import hashlib
from unittest.mock import patch
import unittest

from src.agents.evidence import article_evidence, build_evidence
from src.agents import news_relevance as policy
from src.config import Settings
from src.data.relations import extract_relationships, article_relationships
from src.models import NewsArticle, NewsData, SourceDocument, StockCandidate, now_kst, AnalysisResult, FinancialData
from src.ui.answer import source_groups


def document(stock,text):
    return SourceDocument('NEWS_DART_20261027000123',stock.code,stock.name,'가상 지분 공시',text,
        'OpenDART 공시 원문','https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261027000123',now_kst(),document_id='20261027000123')


def assessment(article,owner):
    return {'assessments':[{'id':article.id,'relation':'group','subject_quote':owner,'support_quote':article.title}]}


class RelationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.stock=StockCandidate('삼성전자','005930','KOSPI','005930.KS')
        self.owner='삼성물산'
        self.doc=document(self.stock,'삼성물산은 삼성전자의 지분을 보유하고 있습니다.')
        self.facts=extract_relationships((self.doc,),self.stock)
        self.article=NewsArticle(1,'삼성물산, 삼성전자 지분 보고서 제출', 'https://example.com/news',None,None)
        self.settings=Settings('','','','',ai_provider='local',local_model='fixture')
        with policy._cache_lock:
            policy._cache.clear()

    def test_official_holder_target_quote_span_and_hash_preserved(self):
        self.assertEqual(len(self.facts),1)
        fact=self.facts[0]
        self.assertEqual((fact.subject_name,fact.target_name,fact.target_code,fact.relation),('삼성물산','삼성전자','005930','shareholder'))
        self.assertEqual(self.doc.text[slice(*fact.span)],fact.quote)
        self.assertEqual(fact.source_hash,hashlib.sha256(self.doc.text.encode()).hexdigest())

    def test_company_names_are_not_hardcoded_and_inverse_wording_preserves_role(self):
        stock=replace(self.stock,name='가상반도체',code='123456')
        text='가상홀딩스가 보유한 가상반도체 지분 현황입니다.'
        facts=extract_relationships((document(stock,text),),stock)
        self.assertEqual((facts[0].subject_name,facts[0].target_name),('가상홀딩스','가상반도체'))

    def test_unofficial_scope_wrong_target_or_host_not_admitted_as_official_relation(self):
        for doc in (replace(self.doc,scope='headline_only'),replace(self.doc,source='뉴스 검색'),
                    replace(self.doc,stock_code='654321'),replace(self.doc,url='https://fake.example/a'),
                    replace(self.doc,url='https://name@dart.fss.or.kr/a')):
            with self.subTest(doc=doc):
                self.assertEqual(extract_relationships((doc,),self.stock),())

    def test_negative_proposed_or_ambiguous_relationship_not_registered(self):
        for text in ('삼성물산은 삼성전자의 지분을 보유하지 않습니다.',
                     '삼성물산은 삼성전자의 지분을 보유할 계획입니다.',
                     '삼성물산과 삼성전자가 같은 그룹이라는 추정입니다.'):
            with self.subTest(text=text):
                self.assertFalse(extract_relationships((replace(self.doc,text=text),),self.stock))

    def test_verified_holder_report_accepted_but_same_group_construction_excluded(self):
        news=NewsData((self.article,),now_kst(),relationships=self.facts)
        parsed=policy.parse_assessments(assessment(self.article,self.owner),news,self.stock,'반도체')
        self.assertTrue(parsed[0].accepted)
        self.assertEqual(parsed[0].reason,'verified_related_shareholder')
        for title in ('삼성물산 건설 수주 소식','삼성물산, 삼성전자 주주사로 건설 수주',
                      '삼성물산, 다른회사 지분 보고서 제출'):
            other=replace(self.article,title=title)
            with self.subTest(title=title):
                selected=policy.parse_assessments(assessment(other,self.owner),replace(news,articles=(other,)),self.stock,'반도체')
                self.assertFalse(selected[0].accepted)

    def test_relation_without_verified_proof_or_wrong_subject_code_rejected(self):
        for facts in ((),(replace(self.facts[0],target_code='654321'),),
                      (replace(self.facts[0],subject_name='다른주주'),)):
            news=NewsData((self.article,),now_kst(),relationships=facts)
            with self.subTest(facts=facts):
                self.assertFalse(policy.parse_assessments(assessment(self.article,self.owner),news,self.stock,'반도체')[0].accepted)

    def test_relation_cache_and_admission_invalidated_when_official_source_changes(self):
        news=NewsData((self.article,),now_kst(),relationships=self.facts)
        with patch.object(policy,'_invoke',return_value=assessment(self.article,self.owner)) as invoke:
            first=policy.prepare_news(news,self.stock,'반도체',self.settings,context_id='relation-case')
            self.assertTrue(first.admission.assessments[0].accepted)
            policy.prepare_news(news,self.stock,'반도체',self.settings,context_id='relation-case')
            self.assertEqual(invoke.call_count,1)
            changed=extract_relationships((replace(self.doc,text=self.doc.text+'\n문서 변경 기록'),),self.stock)
            newer=replace(news,relationships=changed)
            self.assertFalse(policy.matches(first.admission,newer,self.stock,'반도체','relation-case',self.settings))
            policy.prepare_news(newer,self.stock,'반도체',self.settings,context_id='relation-case')
            self.assertEqual(invoke.call_count,2)

    def test_model_and_display_get_original_official_relation_source_without_promoting_article_scope(self):
        news=NewsData((self.article,),now_kst(),relationships=self.facts)
        result=AnalysisResult('반도체',(self.stock,),FinancialData(self.stock,100,10,now_kst()),news,None,source_documents=(self.doc,))
        evidence=build_evidence(result)['NEWS_1']
        self.assertEqual(evidence['scope'],'headline_only')
        self.assertEqual(evidence['relationship_proofs'][0]['scope'],'official_disclosure')
        groups,_=source_groups({'evidence':[dict(evidence,id='NEWS_1')]})
        self.assertEqual([group['url'] for group in groups],[self.article.url,self.doc.url])

    def test_explicit_supply_and_cooperation_roles_from_official_text(self):
        for text,kind in (('가상장비는 삼성전자에 장비 공급 계약을 체결했습니다.','supply'),
                          ('가상장비는 삼성전자와 생산라인 공동 투자 계약을 체결했습니다.','cooperation')):
            with self.subTest(text=text):
                facts=extract_relationships((replace(self.doc,text=text),),self.stock)
                self.assertTrue(any(fact.relation==kind for fact in facts))


if __name__=='__main__':
    unittest.main()
