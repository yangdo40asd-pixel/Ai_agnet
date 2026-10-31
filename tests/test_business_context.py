"""사업 자료 보강→후보 누적→질문별 근거·출처 연결의 정상/반례."""
from dataclasses import replace
import hashlib
import socket
import unittest
from unittest.mock import patch, MagicMock

from src.agents.business_context import business_excerpt, detailed_business_evidence
from src.agents.discovery_answer import business_evidence, discovery_answer, is_discovery_question
from src.config import Settings
from src.data import business_sources, business_web
from src.data.business_budget import business_budget, business_timeout
from src.data.business_sections import PARSER_REVISION
from src.discovery_flow import enrich_discovery
from src.models import (AppError, BusinessSourceBatch, CandidateDiscoveryResult,
                        CompanyBusinessProfile, CompanyBusinessSource, StockCandidate, now_kst)

SETTINGS = Settings('fixture', 'fixture', '', '')
STOCK = StockCandidate('가상제조', '000001', 'KOSPI', '000001.KS')
OTHER = StockCandidate('가상장비', '000002', 'KOSDAQ', '000002.KQ')
PROFILE = CompanyBusinessProfile(STOCK.name, STOCK.code, '반도체 제조업', '반도체', now_kst(),
                                 'https://kind.krx.co.kr/', 'https://official.example/')


def source(stock=STOCK, text='메모리 반도체를 제조합니다. 데이터 저장용 메모리 제품을 공급합니다.'):
    return CompanyBusinessSource(stock.name, stock.code, '20260814000001', '반기보고서 (2026.06)',
        '주요 제품 및 서비스', text, 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814000001',
        now_kst(), hashlib.sha256(text.encode()).hexdigest(), PARSER_REVISION, '20260814', '2026.06')


class BusinessContextTests(unittest.TestCase):
    def test_excerpt_keeps_complete_claims_and_relevant_context(self):
        text = '주소를 안내합니다.\n메모리 제품을 제조합니다.\n' + '긴 문장' * 200
        self.assertIn('메모리 제품을 제조합니다.', business_excerpt(text, ('메모리',), 50))
        self.assertNotIn('긴 문장', business_excerpt(text, ('메모리',), 50))

    def test_source_ids_are_company_and_revision_scoped_and_wrong_owner_is_rejected(self):
        d = CandidateDiscoveryResult('반도체', (STOCK, OTHER), now_kst(), business_sources=(source(), source(OTHER)))
        first = detailed_business_evidence(d, d.candidates)
        self.assertEqual(len(first), 2)
        self.assertEqual(len(set(first)), 2)
        self.assertTrue(all(e['scope'] == 'official_business' and e['theme_supported'] is None for e in first.values()))
        forged = replace(source(), stock_name='다른회사')
        self.assertEqual(detailed_business_evidence(replace(d, business_sources=(forged,)), d.candidates), {})
        revised = detailed_business_evidence(replace(d, business_sources=(source(text='메모리의 새 원문입니다.'),)), d.candidates)
        self.assertFalse(set(revised) & set(first))

    def test_memory_scope_uses_actual_source_even_if_listing_just_says_semiconductor(self):
        from src.agents.answer_quality import QUALITY_CHECKS
        d = CandidateDiscoveryResult('반도체', (STOCK,), now_kst(), business_profiles=(PROFILE,), business_sources=(source(),))
        self.assertTrue(is_discovery_question('메모리 분야를 설명해줘', d))
        def invoke(settings, instruction, request, *args, **kwargs):
            if request['task'] == 'chat_grounding_review':
                return {'checks': dict.fromkeys(QUALITY_CHECKS, True), 'supported': True, 'answers_question': True,
                        'reason': '모의 판정', 'unit_reviews': [{'id':u['id'], 'supported':True, 'reason':'모의 근거'} for u in request['review_units']]}
            ids = [k for k,v in request['evidence'].items() if v['kind'] == 'company_business_section']
            return {'text':'가상제조는 데이터 저장용 메모리 제품을 제조합니다.', 'evidence_ids':ids, 'follow_up':''}
        with patch('src.agents.discovery_answer._invoke', side_effect=invoke):
            answer = discovery_answer('그중 메모리 쪽만 알려줘', d, SETTINGS)
        self.assertIn('메모리 제품', answer.text)
        self.assertEqual(answer.evidence[0]['scope'], 'official_business')
        self.assertFalse(any(e.get('answer_origin') for e in answer.evidence))

    def test_short_listing_is_not_proof_of_equipment_use_or_company_absence(self):
        d = CandidateDiscoveryResult('반도체', (STOCK,), now_kst(), business_profiles=(PROFILE,))
        evidence = business_evidence(d)
        self.assertFalse(any('데이터 저장용' in e['text'] for e in evidence.values()))
        with patch('src.agents.discovery_answer._invoke') as invoke:
            answer = discovery_answer('그중 메모리 쪽만 알려줘', d, SETTINGS)
        invoke.assert_not_called()
        self.assertIn('근거를 확보하지 못했습니다', answer.text)
        self.assertNotIn('사업이 없습니다', answer.text)

    def test_memory_scope_accepts_cited_english_product_class_without_company_exception(self):
        from src.agents.business_context import matches_business_area, business_area_terms
        self.assertTrue(matches_business_area({'products':'DRAM · NAND Storage'}, '메모리'))
        self.assertFalse(matches_business_area({'products':'DRAMATIC marketing'}, '메모리'))
        self.assertFalse(matches_business_area({'products':'비메모리 반도체 제조'}, '메모리'))
        self.assertFalse(matches_business_area({'products':'non-memory semiconductor'}, '메모리'))
        self.assertTrue(matches_business_area({'products':'메모리 및 비메모리 장비'}, '메모리'))
        self.assertFalse(matches_business_area({'products':'일반 반도체'}, 'AI'))
        self.assertEqual(business_area_terms('AI'), ('AI',))

    def test_old_web_parser_output_is_not_reused_as_current_business_evidence(self):
        old = replace(source(), document_id='WEB_old', parser_revision='official-business-html-v1')
        d = CandidateDiscoveryResult('반도체',(STOCK,),now_kst(),business_sources=(old,))
        self.assertEqual(detailed_business_evidence(d,d.candidates),{})

    def test_generic_consumer_product_ad_is_not_theme_business_evidence(self):
        from src.data.business_web import WEB_REVISION
        ad = replace(source(text='뛰어난 디자인과 기술의 다양한 제품을 확인해 보세요.'),
                      document_id='WEB_consumer', parser_revision=WEB_REVISION, section_title='제품')
        d = CandidateDiscoveryResult('반도체',(STOCK,),now_kst(),business_sources=(ad,))
        self.assertEqual(detailed_business_evidence(d,d.candidates),{})

    def test_exact_process_labels_are_allowed_but_wrong_labels_or_financial_numbers_are_not(self):
        from src.agents.chat import validate_answer
        evidence = {'BUSINESS_000001':{'id':'BUSINESS_000001','text':'반도체 2.5D 패키징 및 6-SIDE INSPECTION 장비',
                    'kind':'company_business_section','scope':'official_business','url':'https://official.example/products'}}
        def payload(text):return {'text':text,'evidence_ids':['BUSINESS_000001'],'follow_up':''}
        self.assertIn('2.5D',validate_answer(payload('이 회사는 2.5D 패키징과 6-SIDE 검사 장비를 공급합니다.'),evidence)[0])
        for text in ('이 회사는 2.6D 패키징 장비를 공급합니다.', '이 회사의 영업이익률은 2.5%입니다.',
                     '이 회사는 8-SIDE 검사 장비를 공급합니다.'):
            with self.subTest(text=text),self.assertRaises(AppError):
                validate_answer(payload(text),evidence)

    def test_publication_date_does_not_fabricate_midnight_time(self):
        from src.ui.answer import time_label, evidence_metadata
        self.assertEqual(time_label('20260814'),'2026-08-14')
        self.assertEqual(time_label('2026-08-14'),'2026-08-14')
        label = evidence_metadata({'scope':'official_business','published_at':'20260814'})
        self.assertIn('발행/접수: 2026-08-14',label)
        self.assertNotIn('00:00:00',label)

    def test_enrichment_reuses_fresh_sources_and_preserves_old_company_on_expansion(self):
        old = source()
        new = source(OTHER)
        d = CandidateDiscoveryResult('반도체', (STOCK, OTHER), now_kst(), batch_codes=(OTHER.code,),
                                     business_profiles=(PROFILE,), business_sources=(old,))
        with patch('src.discovery_flow.collect_business_profiles', return_value=()), patch(
                'src.discovery_flow.collect_business_details', return_value=BusinessSourceBatch((new,), ((OTHER.code, 'ok'),))) as collect:
            enriched = enrich_discovery(d, replace(SETTINGS, dart_api_key='fixture'))
            second = enrich_discovery(enriched, replace(SETTINGS, dart_api_key='fixture'))
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(collect.call_args.args[0], (OTHER,))
        self.assertEqual(enriched.business_sources, (old, new))
        self.assertEqual(second.business_sources, enriched.business_sources)

    def test_listing_failure_does_not_discard_detailed_source_success(self):
        d = CandidateDiscoveryResult('반도체', (STOCK,), now_kst())
        with patch('src.discovery_flow.collect_business_profiles', side_effect=AppError('business_failed', '실패')), patch(
                'src.discovery_flow.collect_business_details', return_value=BusinessSourceBatch((source(),), ((STOCK.code, 'ok'),))):
            enriched = enrich_discovery(d, replace(SETTINGS, dart_api_key='fixture'))
        self.assertEqual(enriched.business_error, 'business_failed')
        self.assertEqual(len(enriched.business_sources), 1)
        self.assertTrue(business_evidence(enriched))


class OfficialBusinessWebTests(unittest.TestCase):
    def setUp(self):
        business_web._cache.clear()

    def test_private_hosts_credentials_and_cross_domain_are_rejected(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
        with patch.object(socket, 'getaddrinfo', return_value=answers):
            for url in ('http://127.0.0.1/', 'https://user:secret@official.example/', 'https://foreign.example/'):
                with self.subTest(url=url), self.assertRaises(AppError):
                    business_web.official_url(url, home='https://official.example/')

    def test_official_product_subdomain_is_allowed_but_lookalike_domains_are_not(self):
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443))]
        with patch.object(socket,'getaddrinfo',return_value=public):
            self.assertEqual(business_web.official_url('https://product.official.example/',home='https://www.official.example/'),
                             'https://product.official.example/')
            for url in ('https://official.example.attacker.example/', 'https://notofficial.example/'):
                with self.assertRaises(AppError):
                    business_web.official_url(url,home='https://official.example/')

    def test_business_continuity_policy_is_not_a_product_source(self):
        page = business_web._Page()
        page.feed('<title>Business Continuity Plan</title><h1>Business Continuity Management</h1><p>' + 'Business maintenance policy. ' * 8 + '</p>')
        page.close()
        with patch.object(business_web,'official_url',side_effect=lambda u,**kw:u), patch.object(
                business_web,'_download',return_value=('https://official.example/',page)):
            self.assertEqual(business_web.collect_official_pages(STOCK,'https://official.example/',SETTINGS),())

    def test_redirect_to_another_host_is_rejected_before_second_request(self):
        public = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('1.1.1.1', 443))]
        response = MagicMock(status_code=302, headers={'Location':'http://127.0.0.1/private'})
        with patch.object(socket, 'getaddrinfo', return_value=public), patch.object(business_web.requests, 'get') as fetch:
            fetch.return_value.__enter__.return_value = response
            with self.assertRaises(AppError):
                business_web._download('https://official.example/', 'https://official.example/', SETTINGS)
            self.assertEqual(fetch.call_count, 1)

    def test_one_private_address_in_dns_results_blocks_the_host(self):
        answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443)) for ip in ('1.1.1.1','10.0.0.1')]
        with patch.object(socket, 'getaddrinfo', return_value=answers), self.assertRaises(AppError):
            business_web.official_url('https://official.example/')

    def test_dart_home_registration_must_match_stock_code(self):
        import json
        settings = replace(SETTINGS, dart_api_key='fixture')
        payload = {'status':'000','stock_code':'999999','hm_url':'https://official.example/'}
        with patch.object(business_sources,'fetch_corp_codes',return_value={'000001':{'corp_code':'00100001'}}), patch.object(
                business_sources,'_fetch',return_value=json.dumps(payload).encode()), self.assertRaises(AppError):
            business_sources._official_home(STOCK,settings,None)

    def test_parser_keeps_product_sections_separate_and_ignores_hidden_text(self):
        page = business_web._Page()
        page.feed('<title>제품 설명</title><nav><a href="/products">제품소개</a>메뉴</nav>'
                  '<h1>제품 A</h1><p>' + '메모리 검사 부품을 생산합니다. ' * 7 + '</p>'
                  '<div hidden><div>잘못된 숨김자료</div><p>이것도 숨김자료</p></div>'
                  '<h2>제품 B</h2><p>' + '다른 용도의 장비를 제조합니다. ' * 7 + '</p>')
        page.close()
        self.assertEqual(len(page.sections), 2)
        self.assertNotIn('다른 용도', page.sections[0][1])
        self.assertNotIn('숨김자료', str(page.sections))
        self.assertIn(('/products', '제품소개'), page.links)

    def test_navigation_is_bounded_and_success_is_cached(self):
        landing = business_web._Page()
        landing.feed('<title>공식 기업</title><nav>' + ''.join(f'<a href="/product/{i}">제품{i}</a>' for i in range(10)) + '</nav>')
        landing.close()
        with patch.object(business_web, 'official_url', side_effect=lambda u, **kw:u), patch.object(
                business_web, '_download', side_effect=[('https://official.example/', landing),
                AppError('business_web_http','실패'), AppError('business_web_http','실패')]) as fetch:
            result = business_web.collect_official_pages(STOCK, 'https://official.example/', SETTINGS)
        self.assertEqual(result, ())
        self.assertEqual(fetch.call_count, 3)

    def test_page_source_has_no_fabricated_publication_date_or_financial_period(self):
        page = business_web._Page()
        page.feed('<title>제품 소개</title><h1>제품 및 사업</h1><p>' + '검사용 부품을 제조하여 공급합니다. ' * 8 + '</p>')
        page.close()
        with patch.object(business_web, 'official_url', side_effect=lambda u, **kw:u), patch.object(
                business_web, '_download', return_value=('https://official.example/', page)) as fetch:
            first = business_web.collect_official_pages(STOCK, 'https://official.example/', SETTINGS)
            second = business_web.collect_official_pages(STOCK, 'https://official.example/', SETTINGS)
        self.assertEqual(first, second)
        self.assertEqual(fetch.call_count, 1)
        self.assertIsNone(first[0].published_at)
        self.assertIsNone(first[0].reporting_period)

    def test_dart_failure_falls_back_only_for_matching_verified_profile(self):
        primary = BusinessSourceBatch(statuses=((STOCK.code, 'not_configured'),))
        with patch.object(business_sources, 'collect_business_sources', return_value=primary), patch.object(
                business_web, 'collect_official_pages', return_value=(source(),)) as pages:
            result = business_sources.collect_business_details((STOCK,), SETTINGS, profiles=(PROFILE,))
        self.assertEqual(dict(result.statuses)[STOCK.code], 'ok_official_web')
        self.assertEqual(pages.call_args.args[1], PROFILE.website_url)
        self.assertEqual(business_sources._official_home(STOCK, SETTINGS, replace(PROFILE, stock_name='다른회사')), '')

    def test_source_budget_is_separate_from_outer_model_budget(self):
        from src.agents.local_verification import turn_budget
        with turn_budget(300), business_budget(0), self.assertRaises(AppError):
            business_timeout(SETTINGS)

    def test_company_mapping_request_receives_remaining_source_budget_without_changing_settings(self):
        settings = replace(SETTINGS, dart_api_key='fixture', request_timeout=30)
        with patch.object(business_sources,'_timeout',return_value=1.5), patch.object(
                business_sources,'fetch_corp_codes',return_value={'000001':{'corp_code':'00100001'}}) as mapping, patch.object(
                business_sources,'_collect_one',return_value=((),'empty')):
            business_sources.collect_business_sources((STOCK,),settings)
        self.assertEqual(mapping.call_args.args[0].request_timeout,1.5)
        self.assertEqual(settings.request_timeout,30)


if __name__ == '__main__':
    unittest.main()
