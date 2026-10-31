"""U03/U01: 고정 가상 원자료로 사건·분량·카드·호환성 양방향 검사."""
from copy import deepcopy
from dataclasses import asdict, replace
from unittest.mock import patch
import unittest

from scripts.llm_fixture import synthetic_result
from review_fixtures import with_review_units
from src.agents.answer_quality import QUALITY_CHECKS, review_units, select_evidence
from src.agents.chat import answer_question, validate_response, _answer_request, _check_answer, normalize_attachments
from src.agents.evidence import article_evidence, build_evidence
from src.agents.issues import group_issues, card_groups, VerifiedEventLink, validate_issue_cards
from src.agents.output_contract import response_format
from src.agents.presentation import parse_presentation, enforce_presentation, sentences
from src.config import Settings
from src.models import AnswerBlock, ChatResponse, AppError, NewsArticle, Commentary, Statement


COMPANY='가상검수회사'


def evidence_for(*titles):
    return {f'NEWS_{i}':article_evidence(NewsArticle(i,title,f'https://source{i}.example/a',None,None),COMPANY)
            for i,title in enumerate(titles,1)}


def earnings(period='2025년 연간',amount='1000'):
    return f'{COMPANY} {period} 실적 발표, 매출 {amount}억원'


def card_payload(text='확인된 실적 소식을 정리했습니다.',body='관련 보도에 따르면 매출은 1000억원입니다.',ids=None):
    return {'text':text,'evidence_ids':[],'follow_up':'','blocks':[
        {'title':'연간 실적 발표','text':body,'evidence_ids':ids or ['NEWS_1'],'implication':None}]}


def verdict():
    return {'checks':dict.fromkeys(QUALITY_CHECKS,True),'supported':True,'answers_question':True}


class PresentationTests(unittest.TestCase):
    def test_line_sentence_issue_card_requests_are_separate(self):
        for text in ('뉴스 세 줄로 요약해 줘','뉴스 3문장 요약','세 가지 이슈를 카드로 세 문장 요약'):
            with self.subTest(text=text):
                contract=parse_presentation(text,has_news=True)
                self.assertEqual((contract.style,contract.max_sentences),('plain',3))
        self.assertEqual(parse_presentation('뉴스 세 줄 요약',has_news=True).max_lines,3)
        self.assertIsNone(parse_presentation('뉴스 세 문장 요약',has_news=True).max_lines)
        for text in ('이슈 세 개 알려줘','세 가지 이슈를 카드로 보여줘','뉴스 두 개 알려줘'):
            with self.subTest(text=text):
                contract=parse_presentation(text,has_news=True)
                self.assertEqual(contract.style,'issues')
                self.assertIsNone(contract.max_sentences)
        self.assertEqual(parse_presentation('뉴스 두 개 알려줘',has_news=True).max_issues,2)

    def test_per_issue_sentence_constraint_does_not_become_global_one_sentence(self):
        for text in ('이슈 두 개를 각각 한 문장으로','두 가지 이슈를 각 이슈 한 문장으로','이슈 두 개를 한 문장씩'):
            with self.subTest(text=text):
                contract=parse_presentation(text,has_news=True)
                self.assertEqual((contract.style,contract.max_sentences,contract.per_issue_sentences),('issues',None,1))

    def test_explicit_format_and_zero_news(self):
        self.assertEqual(parse_presentation('뉴스를 짧게 카드로 보여줘',has_news=True).style,'issues')
        self.assertEqual(parse_presentation('뉴스를 카드 없이 글로 보여줘',has_news=True).style,'plain')
        self.assertEqual(parse_presentation('뉴스 카드로 보여줘',has_news=False).style,'plain')
        self.assertIsNone(parse_presentation('중요한 문장 위주로 뉴스 요약',has_news=True).max_sentences)

    def test_sentence_count_preserves_decimal_and_distinguishes_visual_wrapping(self):
        self.assertEqual(len(sentences('주가는 4.46% 상승했습니다. 거래량도 늘었습니다.')),2)
        response=ChatResponse('첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다. 넷째 문장입니다.',[])
        with self.assertRaises(AppError):
            enforce_presentation(response,parse_presentation('세 문장 요약'))

    def test_optional_implication_counts_toward_per_issue_length(self):
        response=ChatResponse('주요 이슈입니다.',[],blocks=(AnswerBlock('일정','출시 계획이 있습니다.',(), '판매는 별도 확인이 필요합니다.'),))
        with self.assertRaises(AppError):
            enforce_presentation(response,parse_presentation('이슈 한 개를 각각 한 문장으로',has_news=True))

    def test_old_and_new_dataclass_names_and_replace_roundtrip(self):
        old=AnswerBlock('제목','본문입니다.',('NEWS_1',))
        new=AnswerBlock(headline='제목',summary='본문입니다.',evidence_ids=('NEWS_1',))
        self.assertEqual(old,new)
        self.assertIsNone(old.implication)
        self.assertEqual((new.headline,new.summary),(old.title,old.text))
        self.assertEqual(replace(new,implication='해석입니다.').implication,'해석입니다.')
        self.assertEqual(AnswerBlock(**asdict(new)),new)
        with self.assertRaises(TypeError):
            AnswerBlock(title='A',headline='B',text='본문입니다.')
        with self.assertRaises(TypeError):
            AnswerBlock(headline='제목')


class IssueIdentityTests(unittest.TestCase):
    def test_same_earnings_three_reports_merge_and_urls_not_generated(self):
        evidence=evidence_for(earnings(),earnings()+' 발표 내용 보도',earnings()+' 소식')
        groups=group_issues(evidence)
        self.assertEqual(len(groups),1)
        self.assertTrue(groups[0].confirmed)
        self.assertEqual(groups[0].evidence_ids,('NEWS_1','NEWS_2','NEWS_3'))
        response=validate_response(card_payload(),evidence,'issues')
        self.assertEqual(response.blocks[0].evidence_ids,groups[0].evidence_ids)
        self.assertEqual([e['url'] for e in response.evidence],[evidence[f'NEWS_{i}']['url'] for i in range(1,4)])

    def test_same_period_conflicting_values_not_averaged_or_latest_selected(self):
        evidence=evidence_for(earnings(amount='1000'),earnings(amount='1200'))
        group=group_issues(evidence)[0]
        self.assertIn('revenue',group.conflicts)
        with self.assertRaises(AppError):
            validate_response(card_payload(),evidence,'issues')
        response=validate_response(card_payload(body='같은 기간 매출이 기사마다 다르게 보도돼 확인이 필요합니다.'),evidence,'issues')
        self.assertEqual(len(response.blocks),1)
        self.assertEqual(len(response.evidence),2)

    def test_different_financial_periods_and_accounting_bases_are_separate(self):
        for a,b in ((earnings('2026년 1분기'),earnings('2026년 2분기')),
                    (earnings()+' 연결 기준',earnings()+' 별도 기준')):
            with self.subTest(a=a,b=b):
                self.assertEqual(len(group_issues(evidence_for(a,b))),2)

    def test_same_day_different_contracts_separate_by_explicit_counterparty(self):
        evidence=evidence_for(f'{COMPANY} 10월 23일 알파와 장비 공급 계약',f'{COMPANY} 10월 23일 베타와 장비 공급 계약')
        groups=card_groups(group_issues(evidence))
        self.assertEqual(len(groups),2)
        self.assertNotEqual(groups[0].anchors[0],groups[1].anchors[0])

    def test_similar_titles_dates_amounts_do_not_prove_same_contract(self):
        evidence=evidence_for(f'{COMPANY} 계약 금액 300억원',f'{COMPANY} 신규 계약 금액 300억원')
        self.assertEqual(len(group_issues(evidence)),2)
        self.assertEqual(len(card_groups(group_issues(evidence))),1)

    def test_investment_needs_verified_project_amount_and_target_not_just_title_similarity(self):
        text=f'{COMPANY} 신규 생산라인 투자 금액 2000억원, 2027년 하반기 가동 목표'
        self.assertEqual(len(group_issues(evidence_for(text,text+' 발표'))),1)
        other=text.replace('하반기','상반기')
        self.assertEqual(len(group_issues(evidence_for(text,other))),2)
        weak=f'{COMPANY} 투자 계획 발표'
        self.assertEqual(len(group_issues(evidence_for(weak,weak))),2)
        self.assertEqual(len(card_groups(group_issues(evidence_for(weak,weak)))),1)

    def test_company_qualifier_and_announcement_not_promoted_to_earnings(self):
        evidence=evidence_for(earnings(),earnings().replace(COMPANY,'다른회사'))
        evidence['NEWS_2']['stock_name']='다른회사'
        self.assertEqual(len(group_issues(evidence)),2)
        root=article_evidence(NewsArticle(1,f'{COMPANY} 투자 계획','https://example.com',None,None,
            f'{COMPANY} 2025년 연간 매출 1000억원'),COMPANY)
        self.assertEqual(group_issues({'NEWS_1':root})[0].kind,'investment')

    def test_result_target_metadata_does_not_merge_other_company_articles(self):
        evidence=evidence_for(earnings(),earnings().replace(COMPANY,'타사회사'))
        # NEWS_2의 stock_name은 결과 대상이지만 원문이 그 회사의 사건임을 뒷받침하지 않는다.
        groups=group_issues(evidence)
        self.assertEqual(len(groups),2)
        self.assertEqual(groups[1].reason,'company_role_unconfirmed')
        self.assertFalse(groups[1].confirmed)

    def test_verified_correction_link_keeps_versions_only_changed_field_is_replaced(self):
        evidence=evidence_for(f'{COMPANY} 계약 금액 600억원, 투자 금액 70억원',
                              f'{COMPANY} 계약 금액 300억원, 투자 금액 80억원')
        for key,doc in (('NEWS_1','D1'),('NEWS_2','D2')):
            evidence[key]['document_id']=doc
        links=(VerifiedEventLink('NEWS_1',COMPANY,'E1','D1'),
               VerifiedEventLink('NEWS_2',COMPANY,'E1','D2','D1',('contract_amount',)))
        group=group_issues(evidence,verified_links=links)[0]
        self.assertEqual(group.evidence_ids,('NEWS_1','NEWS_2'))
        self.assertNotIn('contract_amount',group.conflicts)
        self.assertIn('investment_amount',group.conflicts)
        self.assertEqual(group.versions[1],('D2','D1',('contract_amount',)))
        self.assertEqual(len(group_issues(evidence)),2)  # 자동 정정 연결은 하지 않는다.

    def test_bad_link_reference_or_cycle_does_not_suppress_conflict(self):
        evidence=evidence_for(earnings(),earnings(amount='1200'))
        for key,doc in (('NEWS_1','D1'),('NEWS_2','D2')):
            evidence[key]['document_id']=doc
        for previous in ('MISSING','D1'):
            first=VerifiedEventLink('NEWS_1',COMPANY,'E1','D1','D2' if previous=='D1' else '')
            second=VerifiedEventLink('NEWS_2',COMPANY,'E1','D2',previous,('revenue',))
            with self.subTest(previous=previous):
                self.assertIn('revenue',group_issues(evidence,verified_links=(first,second))[0].conflicts)

    def test_source_selection_prefers_distinct_issues_over_duplicate_fill(self):
        evidence=evidence_for(*(earnings()+' 보도'+str(i) for i in range(5)),earnings('2026년 1분기'),earnings('2026년 2분기'))
        selected=select_evidence('뉴스 주요 이슈 알려줘',[],evidence,[]).evidence
        self.assertEqual(len(selected),4)
        self.assertTrue({'NEWS_6','NEWS_7'}<=set(selected))
        self.assertEqual(len(evidence),7)


class IssueAnswerTests(unittest.TestCase):
    def setUp(self):
        self.base=synthetic_result()
        self.settings=Settings('fixture','fixture','id','secret')
        self.evidence=evidence_for(earnings(),earnings()+' 소식',earnings()+' 보도')
        self.result=replace(self.base,news=replace(self.base.news,articles=tuple(
            NewsArticle(i,e['text'],e['url'],None,None) for i,e in enumerate(self.evidence.values(),1))))

    def test_one_issue_schema_and_generation_even_when_three_requested(self):
        with patch('src.agents.chat._invoke',side_effect=with_review_units([card_payload(),verdict()])) as invoke:
            response=answer_question('최근 이슈 세 가지를 카드로 보여줘',self.result,[],self.settings)
        self.assertEqual(len(response.blocks),1)
        self.assertIsNone(response.blocks[0].implication)
        request=invoke.call_args_list[0].args[2]
        self.assertEqual(len(request['issue_groups']),1)
        schema=response_format(request,'openai/gpt-oss-20b')['json_schema']['schema']
        self.assertEqual(schema['properties']['blocks']['maxItems'],1)
        self.assertIn('implication',schema['properties']['blocks']['items']['properties'])

    def test_zero_one_two_issues_schema_does_not_force_three(self):
        for count in range(3):
            evidence=evidence_for(*(earnings(f'2026년 {q}분기') for q in range(1,count+1)))
            request=_answer_request('이슈 세 개 알려줘',self.result,[],[],evidence,[],[])
            schema=response_format(request,'openai/gpt-oss-20b')['json_schema']['schema']
            self.assertEqual(schema['properties']['blocks']['maxItems'],count)

    def test_duplicate_event_cards_and_unrelated_combination_rejected(self):
        payload=card_payload()
        payload['blocks'].append({'title':'다른 매체 실적','text':'다른 매체도 같은 실적을 보도했습니다.','evidence_ids':['NEWS_2']})
        with self.assertRaises(AppError):
            validate_response(payload,self.evidence,'issues')
        other=evidence_for(earnings(),earnings('2026년 1분기'))
        with self.assertRaises(AppError):
            validate_response(card_payload(ids=['NEWS_1','NEWS_2']),other,'issues')

    def test_optional_implication_null_empty_and_alias_shape(self):
        for implication in (None,''):
            payload=card_payload()
            block=payload['blocks'][0]
            payload['blocks']=[{'headline':block['title'],'summary':block['text'],'evidence_ids':['NEWS_1'],'implication':implication}]
            response=validate_response(payload,self.evidence,'issues')
            self.assertIsNone(response.blocks[0].implication)
        for implication in ('확인되지 않은 수익은 99%입니다.','[원문](https://fake.example)입니다.',{'text':'객체'}):
            payload=card_payload()
            payload['blocks'][0]['implication']=implication
            with self.subTest(implication=implication),self.assertRaises(AppError):
                validate_response(payload,self.evidence,'issues')

    def test_implication_is_in_every_semantic_review_and_legacy_tuple_text(self):
        payload=card_payload()
        payload['blocks'][0]['implication']='이 수치만으로 사업 원인을 확정할 수 없습니다.'
        response=validate_response(payload,self.evidence,'issues')
        self.assertIn('사업 원인',tuple(response)[0])
        units=review_units(response,self.evidence)
        unit=next(u for u in units if '사업 원인' in u['statement'])
        self.assertEqual(set(unit['evidence']),{'NEWS_1','NEWS_2','NEWS_3'})

    def test_three_sentence_summary_retries_four_sentences_without_forcing_cards(self):
        wrong={'text':'실적 발표가 보도됐습니다. 매출이 확인됐습니다. 연간 기준입니다. 다른 내용은 없습니다.',
               'evidence_ids':['NEWS_1'],'follow_up':'','blocks':[]}
        good={**wrong,'text':'실적 발표가 보도됐습니다. 매출은 1000억원입니다. 연간 기준 자료입니다.'}
        with patch('src.agents.chat._invoke',side_effect=with_review_units([wrong,good,verdict()])) as invoke:
            response=answer_question('뉴스 세 문장으로 요약해 줘',self.result,[],self.settings)
        self.assertEqual(len(sentences(response.intro)),3)
        self.assertEqual(response.blocks,())
        self.assertEqual(invoke.call_args_list[1].args[2]['validation_error'],'chat_length')
        self.assertEqual(invoke.call_args_list[0].args[2]['answer_style'],'plain')

    def test_concept_direct_answer_also_honors_explicit_length(self):
        plain={'text':'PER는 주가를 주당순이익으로 나눈 배수입니다.','evidence_ids':[],'follow_up':'','blocks':[]}
        with patch('src.agents.chat._invoke',side_effect=with_review_units([plain,verdict()])) as invoke:
            response=answer_question('PER와 PBR의 차이를 한 문장으로 설명해줘',None,[],self.settings)
        self.assertEqual(len(sentences(response.text)),1)
        self.assertGreater(invoke.call_count,0)

    def test_original_cmp_placeholder_guard_is_not_lost_after_rendering(self):
        evidence=build_evidence(self.base)
        key=next(k for k in evidence if k.startswith('CMP_'))
        payload={'text':'확인한 비교는 {{'+key+'}}입니다.','evidence_ids':[key],'follow_up':'','blocks':[]}
        request={'answer_style':'plain','concept_reference':{},'comparison_style':'rates'}
        with patch('src.agents.chat._invoke') as invoke,self.assertRaises(AppError) as caught:
            _check_answer(payload,evidence,[],self.base,request,self.settings,'실적 비교 설명')
        self.assertEqual(caught.exception.code,'chat_comparison_style')
        invoke.assert_not_called()

    def test_initial_report_path_also_folds_same_event_and_keeps_financial_card(self):
        from src.analysis_flow import analysis_response
        commentary=Commentary((Statement('매출 실적이 보도됐습니다.',(1,)),
                               Statement('연간 실적 발표 소식입니다.',(2,))), '', None, None,
                              Statement('같은 기간의 실적 발표를 다룹니다.',(3,)))
        response=analysis_response(replace(self.result,commentary=commentary))
        news=[b for b in response.blocks if any(k.startswith('NEWS_') for k in b.evidence_ids)]
        self.assertEqual(len(news),1)
        self.assertEqual(news[0].evidence_ids,('NEWS_1','NEWS_2','NEWS_3'))
        self.assertTrue(any(b.title=='연간 실적' for b in response.blocks))

    def test_attachment_notice_is_separate_from_one_sentence_summary(self):
        payload={'text':'확인할 내용을 글로 입력할 수 있습니다.','evidence_ids':[],'follow_up':'','blocks':[]}
        with patch('src.agents.chat._invoke',return_value=payload):
            response=answer_question('첨부를 한 문장으로 설명해줘',None,[],self.settings,
                normalize_attachments([('chart.png',b'fixture-image')]))
        self.assertEqual(len(sentences(response.text)),1)
        self.assertIn('본문은 현재 읽을 수 없습니다',response.notices[0])

    def test_two_issues_each_one_sentence_generation_and_extra_implication_rejected(self):
        evidence=evidence_for(earnings('2026년 1분기'),earnings('2026년 2분기'))
        result=replace(self.base,news=replace(self.base.news,articles=tuple(
            NewsArticle(i,e['text'],e['url'],None,None) for i,e in enumerate(evidence.values(),1))))
        question='이슈 두 개를 각각 한 문장으로 카드로 보여줘'
        payload={'text':'분기별 실적 발표입니다.','evidence_ids':[],'follow_up':'','blocks':[
            {'title':'전기 실적','text':'전기 실적이 보도됐습니다.','evidence_ids':['NEWS_1']},
            {'title':'당기 실적','text':'당기 실적 발표 소식입니다.','evidence_ids':['NEWS_2']}]}
        with patch('src.agents.chat._invoke',side_effect=with_review_units([payload,verdict()])):
            response=answer_question(question,result,[],self.settings)
        self.assertEqual(len(response.blocks),2)
        self.assertTrue(all(len(sentences(b.text))==1 for b in response.blocks))
        wrong=deepcopy(payload)
        wrong['blocks'][0]['implication']='별도 확인이 필요합니다.'
        request=_answer_request(question,result,[],[],evidence,[],[])
        with self.assertRaises(AppError) as caught:
            _check_answer(wrong,evidence,[],result,request,self.settings,question)
        self.assertEqual(caught.exception.code,'chat_length')

    def test_distinct_event_categories_cluster_and_form_multiple_cards(self):
        titles = (
            f'{COMPANY} 공정위 과징금 부과 결정',
            f'{COMPANY} 공정위 과징금 처분에 불복 소송 검토',
            f'{COMPANY} 한국품질만족지수 18개 부문 최다 수상',
            f'{COMPANY} 한국품질만족지수 18년 연속 1위 기록',
            f"'{COMPANY} 기밀유출 혐의' 전 임원 2심 징역 3년 법정구속",
            f'{COMPANY} 주주환원 확대 기대감 발표',
        )
        evidence = evidence_for(*titles)
        groups = group_issues(evidence)
        # 6개 기사가 4개 독립 사건(regulatory 1건, product 1건, legal 1건, shareholder 1건)으로 병합
        kinds = {g.kind: g for g in groups}
        self.assertIn('regulatory', kinds)
        self.assertIn('product', kinds)
        self.assertIn('legal', kinds)
        self.assertIn('shareholder', kinds)
        # 공정위 과징금 기사 2건은 동일한 하나의 IssueGroup으로 병합됨
        self.assertEqual(kinds['regulatory'].evidence_ids, ('NEWS_1', 'NEWS_2'))
        # 품질만족지수 기사 2건도 동일한 하나의 IssueGroup으로 병합됨
        self.assertEqual(kinds['product'].evidence_ids, ('NEWS_3', 'NEWS_4'))
        # card_groups 선출 시 4개 독립 사건이 모두 선출 대상이 됨
        eligible = card_groups(groups)
        self.assertEqual(len(eligible), 4)

    def test_three_issue_cards_generation_and_validation(self):
        titles = (
            f'{COMPANY} 한국품질만족지수 18개 부문 최다 수상',
            f'{COMPANY} 한국품질만족지수 18년 연속 1위 기록',
            f"'{COMPANY} 기밀유출 혐의' 전 임원 2심 징역 3년 법정구속",
            f'{COMPANY} 주주환원 확대 기대감 발표',
        )
        evidence = evidence_for(*titles)
        groups = group_issues(evidence)
        eligible = card_groups(groups)
        self.assertEqual(len(eligible), 3)

        payload = {
            'text': f'{COMPANY}의 최근 3가지 주요 이슈입니다.',
            'evidence_ids': [], 'follow_up': '',
            'blocks': [
                {'title': '품질만족지수 수상', 'text': '품질만족지수 18개 부문에서 수상했습니다.', 'evidence_ids': ['NEWS_1', 'NEWS_2']},
                {'title': '기밀유출 법적 공방', 'text': '기밀유출 혐의 관련 2심 판결이 내려졌습니다.', 'evidence_ids': ['NEWS_3']},
                {'title': '주주환원 정책 기대', 'text': '주주환원 확대 방안이 발표되었습니다.', 'evidence_ids': ['NEWS_4']},
            ]
        }
        response = validate_response(payload, evidence, 'issues')
        self.assertEqual(len(response.blocks), 3)
        # 3개 카드 검증 통과 (max_issues=3)
        validate_issue_cards(response, evidence, groups, max_issues=3)

        # max_issues=2로 제한된 경우 3개 카드는 거절
        with self.assertRaises(AppError) as caught:
            validate_issue_cards(response, evidence, groups, max_issues=2)
        self.assertEqual(caught.exception.code, 'chat_issues')


if __name__=='__main__':
    unittest.main()
