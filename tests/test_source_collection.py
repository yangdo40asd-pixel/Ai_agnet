"""T00: 실제 통신 없는 제한 수집·자료 범위·공식 원문 검수."""
from dataclasses import replace
import io
import zipfile
import unittest
from urllib.parse import quote
from unittest.mock import Mock, patch

from src.config import Settings
from src.models import AppError, StockCandidate
from src.data.news import fetch_news, parse_news
from src.data.disclosures import collect_disclosures, document_text


def page(titles, total=50):
    return Mock(status_code=200, json=Mock(return_value={'total': total, 'items': [
        {'title': t, 'description': '<b>검색 발췌</b>', 'originallink': 'https://example.com/'+str(i)+quote(t),
         'pubDate': 'Tue, 27 Oct 2026 09:00:00 +0900'} for i,t in enumerate(titles)]}))


def zipped(text):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('doc.xml', '<DOC><P>'+text+'</P></DOC>')
    return buffer.getvalue()


class SourceCollectionTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings('test', 'test', 'id', 'secret')

    def test_ten_candidates_and_description_without_full_body_claim(self):
        with patch('src.data.news.requests.get', return_value=page(['가상회사 소식'+str(i) for i in range(14)])) as get:
            news = fetch_news('반도체', '가상회사', self.settings)
        self.assertEqual(len(news.articles), 10)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(get.call_args.kwargs['params']['display'], 10)
        self.assertEqual(news.articles[0].description, '검색 발췌')

    def test_second_query_only_when_candidates_insufficient_and_at_most_twenty(self):
        with patch('src.data.news.requests.get', side_effect=[page(['다른회사 소식'+str(i) for i in range(10)]),
                   page(['가상회사 자료'+str(i) for i in range(12)])]) as get:
            news = fetch_news('반도체', '가상회사', self.settings)
        self.assertEqual(get.call_count, 2)
        self.assertEqual(len(news.articles), 20)
        self.assertEqual(get.call_args.kwargs['params']['query'], '가상회사')
        self.assertEqual([a.id for a in news.articles], list(range(1,21)))

    def test_second_failure_preserves_first_page_and_no_retry(self):
        with patch('src.data.news.requests.get', side_effect=[page(['가상회사 기사']), Mock(status_code=429)]) as get:
            news = fetch_news('반도체', '가상회사', self.settings)
        self.assertEqual((len(news.articles), news.status, get.call_count), (1, 'partial', 2))

    def test_same_event_articles_kept_as_sources_without_inventing_independent_issues(self):
        with patch('src.data.news.requests.get',return_value=page(['가상회사 같은 투자 발표']*3)) as get:
            news=fetch_news('반도체','가상회사',self.settings)
        self.assertEqual(get.call_count,1)
        self.assertEqual(len(news.articles),3)
        self.assertEqual(len({a.title for a in news.articles}),1)
        # 수집 건수는 사건 수가 아니다. 별도 이슈 분리는 U에서 검수한다.

    def test_end_of_pagination_and_missing_total_do_not_loop(self):
        for total in (0, 1, 10):
            with patch('src.data.news.requests.get', return_value=page(['가상회사 자료'], total)) as get:
                fetch_news('가상회사', '가상회사', self.settings)
                self.assertEqual(get.call_count, 1)

    def test_parse_legacy_limit_and_explicit_limit_and_duplicate_url(self):
        data=page([str(i) for i in range(11)]).json()
        self.assertEqual(len(parse_news(data).articles), 3)
        self.assertEqual(len(parse_news(data, limit=10).articles), 10)

    def test_official_document_boundaries(self):
        self.assertEqual(document_text(zipped('가상회사 투자 공시')), '가상회사 투자 공시')
        for raw in (b'not zip', b'a'*2_000_001, zipped('<!ENTITY bad>')):
            with self.subTest(length=len(raw)), self.assertRaises(AppError):
                document_text(raw)

    def test_no_document_fetch_without_explicit_request_or_key(self):
        stock=StockCandidate('가상회사','123456','KOSPI','123456.KS')
        with patch('src.data.disclosures.requests.get') as get:
            self.assertEqual(collect_disclosures(stock,self.settings,'주가')[1], 'not_requested')
            self.assertEqual(collect_disclosures(stock,self.settings,'공시')[1], 'not_configured')
            get.assert_not_called()

    def test_official_list_to_document_is_limited_and_receipts_preserved(self):
        stock=StockCandidate('가상회사','123456','KOSPI','123456.KS')
        settings=replace(self.settings, dart_api_key='fixture')
        mapping={'123456': {'corp_code':'00123456','ambiguous':False}}
        rows=[{'corp_code':'00123456','rcept_no':'2026102700000'+str(i),'rcept_dt':'20261027','report_nm':'계약 공시'} for i in range(3)]
        listing=Mock(status_code=200,json=Mock(return_value={'status':'000','list':rows}))
        with patch('src.data.disclosures.fetch_corp_codes',return_value=mapping), patch(
                'src.data.disclosures.requests.get',side_effect=[listing,Mock(status_code=200,content=zipped('가상회사 계약금액 300억원입니다.')),
                                                                Mock(status_code=200,content=zipped('가상회사 계약 변경입니다.'))]) as get:
            docs,status=collect_disclosures(stock,settings,'계약 공시')
        self.assertEqual((len(docs),status,get.call_count),(2,'ok',3))
        self.assertEqual(docs[0].scope,'official_disclosure')
        self.assertEqual(docs[0].document_id,rows[0]['rcept_no'])


if __name__=='__main__':
    unittest.main()
