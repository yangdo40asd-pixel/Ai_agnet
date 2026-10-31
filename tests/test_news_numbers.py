"""T02/T03: 검증된 뉴스 숫자만 항목·대상·기간·방향에 맞게 허용한다."""
from dataclasses import replace
import unittest

from scripts.llm_fixture import synthetic_result
from src.agents.chat import validate_answer
from src.agents.evidence import build_evidence
from src.data.text_facts import source_facts, fact_payload
from src.models import AppError, NewsArticle


class NewsNumberTests(unittest.TestCase):
    def evidence(self,title,scope='headline_only'):
        return {'NEWS_1':{'text':title,'scope':scope,'structured_facts':[
            fact_payload(f) for f in source_facts(title,'NEWS_1','가상회사',scope=scope)]}}

    def check(self,text,evidence):
        return validate_answer({'text':text,'evidence_ids':['NEWS_1'],'follow_up':''},evidence)[0]

    def test_price_and_change_normal_spellings_allowed(self):
        evidence=self.evidence('가상회사 주가 22만2500원으로 4.46% 상승')
        answer=self.check('주가는 222,500원으로 4.46% 상승했습니다.',evidence)
        self.assertIn('222,500원',answer)

    def test_cross_item_borrowing_or_direction_or_unit_or_fake_value_rejected(self):
        evidence=self.evidence('가상회사 주가 4.46% 상승, 외국인 지분율 52.3%')
        for text in ('외국인 지분율은 4.46%입니다.','주가는 52.3% 상승했습니다.',
                     '주가는 4.46% 하락했습니다.','주가는 4.46%p 상승했습니다.',
                     '주가는 99% 상승했습니다.','타사회사 주가는 4.46% 상승했습니다.'):
            with self.subTest(text=text),self.assertRaises(AppError):
                self.check(text,evidence)

    def test_period_mismatch_and_provisional_to_final_rejected(self):
        evidence=self.evidence('가상회사 2026년 3분기 잠정 매출 400억원')
        self.assertIn('400억원',self.check('2026년 3분기 잠정 매출은 400억원입니다.',evidence))
        for text in ('2025년 3분기 잠정 매출은 400억원입니다.','확정 매출은 400억원입니다.',
                     '매출은 400억원입니다.'):
            with self.subTest(text=text),self.assertRaises(AppError):
                self.check(text,evidence)

    def test_source_date_accepted_but_publication_not_used_as_event(self):
        evidence=self.evidence('가상회사 10월 23일 투자 결정, 투자 금액 2000억원')
        self.assertIn('10월 23일',self.check('10월 23일 투자 금액은 2000억원으로 발표됐습니다.',evidence))
        with self.assertRaises(AppError):
            self.check('10월 27일 투자 금액은 2000억원으로 발표됐습니다.',evidence)

    def test_aggregate_holding_not_misrepresented_as_direct(self):
        evidence=self.evidence('가상회사 특수관계인 합산 지분율 19.69%')
        self.assertIn('19.69%',self.check('특수관계인 합산 지분율은 19.69%입니다.',evidence))
        with self.assertRaises(AppError):
            self.check('가상회사의 단독 지분율은 19.69%입니다.',evidence)

    def test_reported_news_not_promoted_to_official_confirmation(self):
        evidence=self.evidence('가상회사 투자 금액 2000억원')
        self.assertIn('2000억원',self.check('보도된 투자 금액은 2000억원입니다.',evidence))
        with self.assertRaises(AppError):
            self.check('공시에서 투자 금액은 2000억원으로 확인됐습니다.',evidence)

    def test_older_value_allowed_for_history_but_not_current(self):
        evidence=self.evidence('가상회사 최초 공시 계약 금액 600억원, 정정 공시 계약 금액 300억원',scope='official_disclosure')
        self.assertIn('600억원',self.check('최초 공시 계약 금액은 600억원이며, 정정 공시 계약 금액은 300억원입니다.',evidence))
        with self.assertRaises(AppError):
            self.check('현재 계약 금액은 600억원입니다.',evidence)

    def test_industry_fact_not_used_for_company(self):
        evidence=self.evidence('반도체 업계 투자 금액 300억원')
        with self.assertRaises(AppError):
            self.check('가상회사 투자 금액은 300억원입니다.',evidence)

    def test_fact_ids_and_payload_json_serialization(self):
        import json
        base=synthetic_result()
        stock=replace(base.financial.stock,name='가상회사')
        article=NewsArticle(1,'가상회사 주가 4.46% 상승','https://example.com/a',None,None,
                            '가상회사 매출 400억원')
        result=replace(base,financial=replace(base.financial,stock=stock),news=replace(base.news,articles=(article,)))
        evidence=build_evidence(result)
        json.dumps(evidence,ensure_ascii=False,allow_nan=False)
        facts=evidence['NEWS_1']['structured_facts']
        self.assertEqual(len({f['fact_id'] for f in facts}),len(facts))
        self.assertEqual(evidence['NEWS_1']['scope'],'article_excerpt')

    def test_foreign_ratio_keeps_specific_item_and_rejects_generic_borrowing(self):
        evidence=self.evidence('가상회사 외국인 지분율 4.46%')
        self.assertEqual(evidence['NEWS_1']['structured_facts'][0]['item'],'foreign_ratio')
        self.assertIn('4.46%',self.check('외국인 지분율은 4.46%입니다.',evidence))
        with self.assertRaises(AppError):
            self.check('주가는 4.46% 상승했습니다.',evidence)

    def test_negative_change_normalizes_magnitude_but_preserves_direction(self):
        evidence=self.evidence('가상회사 주가 -4.46% 하락')
        self.assertIn('4.46%',self.check('주가는 4.46% 하락했습니다.',evidence))
        for text in ('주가는 4.46% 상승했습니다.','주가는 -4.46% 상승했습니다.'):
            with self.subTest(text=text),self.assertRaises(AppError):
                self.check(text,evidence)

    def test_isolated_official_document_is_not_latest_valid_contract(self):
        evidence=self.evidence('가상회사 계약 금액 300억원',scope='official_disclosure')
        evidence['NEWS_1']['validity']='document_only'
        self.assertIn('300억원',self.check('조회한 공시에 기재된 계약 금액은 300억원입니다.',evidence))
        for text in ('현재 계약 금액은 300억원입니다.','최신 공시의 계약 금액은 300억원입니다.',
                     '계약 금액은 300억원입니다.'):
            with self.subTest(text=text),self.assertRaises(AppError):
                self.check(text,evidence)

    def test_value_from_uncited_article_does_not_license_answer(self):
        evidence=self.evidence('가상회사 주가 4.46% 상승')
        evidence['NEWS_2']={'text':'가상회사 주가 5.23% 상승','scope':'headline_only',
            'structured_facts':[fact_payload(f) for f in source_facts('가상회사 주가 5.23% 상승','NEWS_2','가상회사')]}
        with self.assertRaises(AppError):
            self.check('주가는 5.23% 상승했습니다.',evidence)


if __name__=='__main__':
    unittest.main()
