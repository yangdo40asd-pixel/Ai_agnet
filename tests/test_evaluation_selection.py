"""실제 평가 질문 실패의 원인인 기간 선택을 고정한다. 검증 규칙은 변경하지 않는다."""
import unittest
from src.agents.answer_quality import select_evidence
from src.agents.evidence import build_evidence
from scripts.llm_fixture import synthetic_result


class EvaluationSelectionTests(unittest.TestCase):
    def setUp(self): self.evidence=build_evidence(synthetic_result())

    def test_named_year_evaluation_keeps_comparable_previous_year(self):
        for expression in ('좋은 편이야','괜찮아','양호해','나쁜 편이야','어떤 편이야'):
            with self.subTest(expression=expression):
                selected=select_evidence('2025년 실적은 '+expression+'?',[],self.evidence,[],strict=True)
                compared=[e for e in selected.evidence.values() if e.get('kind')=='annual_comparison']
                self.assertTrue(compared)
                self.assertTrue(all(e['years']==[2024,2025] for e in compared))

    def test_value_only_question_does_not_require_previous_year(self):
        selected=select_evidence('2025년 영업이익은 얼마야?',[],self.evidence,[],strict=True)
        self.assertTrue(any(e.get('kind')=='annual_financial' for e in selected.evidence.values()))
        self.assertFalse(any(e.get('kind')=='annual_comparison' for e in selected.evidence.values()))

    def test_unavailable_explicit_year_does_not_become_different_year(self):
        selected=select_evidence('2022년 실적은 좋은 편이야?',[],self.evidence,[],strict=True)
        self.assertFalse(any(e.get('kind')=='annual_comparison' for e in selected.evidence.values()))

    def test_detailed_cause_is_not_forced_into_two_sentences(self):
        selected=select_evidence('왜 영업이익이 늘었어? 자세히 설명해줘',[],self.evidence,[],strict=True)
        joined=' '.join(selected.requirements)
        self.assertIn('자세한 설명 요청',joined)
        self.assertNotIn('2문장 이내',joined)
