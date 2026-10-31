"""T01/T04: 구조화 사실·Decimal·등록 단계의 정상/변조 대조."""
from dataclasses import replace
from decimal import Decimal
import unittest

from src.data.text_facts import normalize_quantity, source_facts, extract_candidates, register_fact, contract_scale_fact


class TextFactTests(unittest.TestCase):
    def facts(self,text,**kwargs):
        return source_facts(text,'NEWS_1','가상회사',**kwargs)

    def test_exact_amount_normalization(self):
        for raw,unit,expected in (('22만2500','원','222500'),('222,500','원','222500'),
                                  ('107조4000억','원','107400000000000'),('19.69','%','19.69'),
                                  ('2.19','%p','2.19'),('300','억원','30000000000')):
            with self.subTest(raw=raw):
                value,_=normalize_quantity(raw,unit)
                self.assertIsInstance(value,Decimal)
                self.assertEqual(value,Decimal(expected))

    def test_postposed_investment_amount_is_registered_with_original_span(self):
        for wording in ('가상회사 생산라인에 2000억원 투자 계획 발표',
                        '가상회사는 생산라인에 2000억 원을 투자할 계획입니다.',
                        '가상회사는 생산라인 확대를 위해 2000억원의 투자 계획을 발표했습니다.'):
            with self.subTest(wording=wording):
                fact=self.facts(wording,scope='article_excerpt')[0]
                self.assertEqual((fact.item,fact.status,fact.value),
                                 ('investment_amount','verified',Decimal('200000000000')))
                self.assertEqual(wording[slice(*fact.span)],fact.raw_text)

    def test_postposed_investment_does_not_guess_other_items_or_company(self):
        for wording in ('가상회사 2000억원 투자자 설명회',
                        '가상회사 2000억원 투자수익 발표',
                        '타사회사 생산라인에 2000억원 투자 계획 발표'):
            with self.subTest(wording=wording):
                self.assertEqual(self.facts(wording)[0].status,'deferred')
        self.assertEqual(self.facts('가상회사 매출 2000억원 투자 계획 발표')[0].item,'revenue')

    def test_postposed_investment_answer_still_requires_matching_item_and_value(self):
        from src.agents.news_numbers import mask_verified_news
        from src.data.text_facts import fact_payload
        fact=self.facts('가상회사 생산라인에 2000억원 투자 계획 발표',scope='article_excerpt')[0]
        evidence={'NEWS_1':{'structured_facts':[fact_payload(fact)]}}
        self.assertNotIn('2000',mask_verified_news('가상회사는 2000억 원을 투자할 계획입니다.',evidence))
        from src.models import AppError
        with self.assertRaises(AppError):
            mask_verified_news('가상회사 매출 2000억원입니다.',evidence)
        # 없는 값은 마스킹하지 않으므로 이후 기존 재무 숫자 검사에서 거절한다.
        self.assertIn('3000',mask_verified_news('가상회사는 3000억원을 투자합니다.',evidence))

    def test_invalid_scale_and_comma_are_not_rounded_or_guessed(self):
        for raw in ('1,23','2억3조','1억2억','NaN','Infinity'):
            with self.subTest(raw=raw),self.assertRaises((ValueError,ArithmeticError)):
                normalize_quantity(raw,'원')

    def test_price_and_change_are_separate_facts(self):
        text='가상회사 주가 22만2500원으로 4.46% 상승'
        facts=self.facts(text,published_at='2026-10-27')
        self.assertEqual([f.item for f in facts],['price','price_change'])
        self.assertEqual([f.status for f in facts],['verified','verified'])
        self.assertEqual(facts[0].direction,'value')
        self.assertEqual(facts[1].direction,'up')
        self.assertIsNone(facts[0].event_occurred_at)
        self.assertEqual(facts[0].article_published_at,'2026-10-27')
        self.assertEqual(text[slice(*facts[0].span)],facts[0].raw_text)

    def test_date_event_and_financial_period_are_not_publication_time(self):
        facts=self.facts('가상회사 10월 23일 공시, 2025년 매출 1200억원',published_at='2026-10-27')
        self.assertEqual(facts[0].event_occurred_at,'10월 23일')
        self.assertEqual(facts[-1].financial_period,'2025년')
        self.assertEqual(facts[-1].article_published_at,'2026-10-27')
        self.assertIsNone(facts[-1].event_occurred_at)

    def test_unknown_or_foreign_company_quantities_are_deferred(self):
        for text in ('가상회사 400억원 소식','타사회사 매출 400억원','가상회사, 타사회사 매출 400억원'):
            with self.subTest(text=text):
                self.assertTrue(all(f.status=='deferred' for f in self.facts(text,known_names=('타사회사',))))

    def test_industry_article_not_promoted_to_current_company(self):
        facts=self.facts('반도체 업계 투자 300억원')
        self.assertEqual(facts[0].status,'deferred')
        self.assertEqual(facts[0].reason,'target_not_explicit')

    def test_forged_candidate_is_rejected_before_answer_generation(self):
        text='가상회사 주가 4.46% 상승'
        candidate=extract_candidates(text,'NEWS_1','가상회사')[0]
        self.assertEqual(register_fact(candidate,text,'가상회사',scope='headline_only').status,'verified')
        for changes in ({'item':'foreign_ratio'},{'target':'타사회사'},{'value':Decimal('99')},
                        {'unit':'%p'},{'direction':'down'},{'span':(0,2)},{'source_hash':'forged'},
                        {'scope':'official_disclosure'},{'value':4.46},{'status':'verified'},
                        {'financial_period':'2025년'},{'qualifier':'provisional'},{'ownership_basis':'aggregate'}):
            with self.subTest(changes=changes):
                self.assertEqual(register_fact(replace(candidate,**changes),text,'가상회사',scope='headline_only').status,'rejected')

    def test_source_revision_invalidates_old_fact(self):
        text='가상회사 계약 금액 600억원'
        candidate=extract_candidates(text,'NEWS_1','가상회사')[0]
        self.assertEqual(register_fact(candidate,text.replace('600','300'),'가상회사',scope='headline_only').status,'rejected')

    def test_aggregate_and_provisional_qualifiers_retained(self):
        aggregate=self.facts('가상회사 특수관계인 합산 지분율 19.69%')[0]
        self.assertEqual(aggregate.ownership_basis,'aggregate')
        temporary=self.facts('가상회사 2026년 3분기 잠정 매출 400억원')[-1]
        self.assertEqual(temporary.qualifier,'provisional')
        self.assertEqual(temporary.financial_period,'2026년 3분기')

    def test_current_and_historical_facts_are_both_preserved(self):
        facts=self.facts('가상회사 최초 공시 계약 금액 600억원, 정정 공시 계약 금액 300억원',scope='official_disclosure')
        self.assertEqual([f.value for f in facts],[Decimal('60000000000'),Decimal('30000000000')])
        self.assertEqual([f.validity for f in facts],['historical','current'])

    def test_no_registered_date_from_metadata_without_source_date(self):
        facts=self.facts('가상회사 신규 라인 계획',published_at='2026-10-27')
        self.assertEqual(facts,())

    def test_planned_year_not_marked_as_occurred_event(self):
        fact=self.facts('가상회사 2027년 하반기 가동 목표')[0]
        self.assertEqual(fact.item,'target_date')
        self.assertEqual(fact.qualifier,'planned')
        self.assertIsNone(fact.event_occurred_at)

    def test_longer_company_name_not_promoted_to_selected_company(self):
        for text in ('가상회사우 주가 400원','가상회사이노베이션 주가 400원'):
            with self.subTest(text=text):
                self.assertTrue(all(f.status=='deferred' for f in self.facts(text)))

    def test_negative_increase_conflict_deferred_before_registration(self):
        fact=self.facts('가상회사 주가 -4.46% 상승')[0]
        self.assertEqual((fact.status,fact.reason),('deferred','sign_direction_conflict'))

    def test_full_source_hash_and_original_span_survive_bounded_extraction(self):
        import hashlib
        text='소개\n가상회사 투자 금액 300억원\n'+'자료 '*4000+'가상회사 투자 금액 900억원'
        facts=self.facts(text,scope='official_disclosure')
        self.assertEqual(len(facts),1)
        self.assertEqual(facts[0].source_hash,hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(text[slice(*facts[0].span)],'300억원')

    def test_derived_contract_scale_has_input_ids_and_formula_not_loss_ratio(self):
        contract=self.facts('가상회사 계약 금액 300억원',scope='official_disclosure')[0]
        revenue=self.facts('가상회사 2025년 연간 매출 1200억원',scope='financial_statement')[-1]
        revenue=replace(revenue,fact_id='FIN_REVENUE_2025')
        fact=contract_scale_fact(contract,revenue)
        self.assertEqual((fact.item,fact.value,fact.unit),('contract_scale_ratio',Decimal(25),'%'))
        self.assertEqual(fact.input_fact_ids,(contract.fact_id,revenue.fact_id))
        self.assertIn(' / ',fact.formula)
        for altered in (replace(revenue,value=Decimal(0)),replace(revenue,target='다른회사'),
                        replace(revenue,status='deferred'),replace(revenue,financial_period='2025년 3분기')):
            with self.subTest(altered=altered),self.assertRaises(ValueError):
                contract_scale_fact(contract,altered)


if __name__=='__main__':
    unittest.main()
