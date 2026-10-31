import unittest
from unittest.mock import patch
from src.agents.period_scope import missing_quarter_answer
from src.agents.chat import answer_question
from src.config import Settings
from scripts.llm_fixture import synthetic_result


class PeriodScopeTests(unittest.TestCase):
    def test_annual_data_does_not_answer_requested_quarter(self):
        response=missing_quarter_answer('2026년 3분기 매출 얼마야?',{'ANNUAL':{'kind':'annual_financial','period':'2025년 연간'}})
        self.assertIn('2026년 3분기',response)

    def test_verified_same_quarter_data_is_preserved(self):
        evidence={'NEWS_1':{'structured_facts':[{'status':'verified','item':'operating_income','financial_period':'2026년 3분기'}]}}
        self.assertIsNone(missing_quarter_answer('2026년 3분기 실적 어때?',evidence))
        self.assertIsNotNone(missing_quarter_answer('2025년 3분기 실적 어때?',evidence))

    def test_deferred_fact_is_not_quarterly_data(self):
        evidence={'NEWS_1':{'structured_facts':[{'status':'deferred','item':'revenue','financial_period':'2026년 3분기'}]}}
        self.assertIsNotNone(missing_quarter_answer('2026년 3분기 실적 어때?',evidence))

    def test_annual_and_concept_news_requests_unchanged(self):
        for q in ('2025년 실적은?','3분기 실적 뉴스 알려줘','3분기 매출의 뜻은?'):
            self.assertIsNone(missing_quarter_answer(q,{}))

    def test_actual_answer_path_does_not_substitute_annual_llm_answer(self):
        settings=Settings('','','','',news_relevance_mode='strict')
        with patch('src.agents.chat._invoke') as invoke:
            answer=answer_question('2026년 3분기 실적은?',synthetic_result(),[],settings)
        self.assertIn('확인하지 못했습니다',answer[0])
        invoke.assert_not_called()
