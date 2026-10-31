"""계획7: 일반 질문의 근거 입력이 로컬 모델 문맥을 넘지 않도록 줄이는 규칙과 매수 판단 질문의 보충 조회."""

import json
import unittest
from datetime import timedelta

from src.agents.answer_quality import GENERAL_EVIDENCE_CHAR_BUDGET, _fit_general_evidence
from src.analysis_flow import needs_data


def _cmp(item, years):
    return {"kind": "annual_comparison", "status": "ok", "item": item, "years": list(years),
            "text": "x" * 1100, "value_text": "y" * 100}


class FitGeneralEvidenceTests(unittest.TestCase):
    def _big(self):
        evidence = {"PRICE": {"status": "ok", "text": "가격"}, "PER": {"status": "ok", "text": "PER"},
                    "PBR": {"status": "missing", "text": "m" * 300}, "BPS": {"status": "missing", "text": "m" * 300}}
        for item in ("revenue", "operating_income", "net_income", "operating_margin"):
            evidence[f"CMP_2023_2024_{item}"] = _cmp(item, (2023, 2024))
            evidence[f"CMP_2024_2025_{item}"] = _cmp(item, (2024, 2025))
        for year in (2023, 2024, 2025):
            for item in ("REVENUE", "OPERATING_INCOME", "NET_INCOME"):
                evidence[f"FIN_{year}_CFS_{item}"] = {"status": "ok", "text": "z" * 700}
        evidence["HISTORY"] = {"status": "ok", "text": "h" * 4000}
        return evidence

    def test_small_evidence_is_unchanged(self):
        small = {"PRICE": {"status": "ok", "text": "가격"}}
        self.assertEqual(_fit_general_evidence(small), small)

    def test_oversized_evidence_is_cut_to_budget_keeping_core_items(self):
        fitted = _fit_general_evidence(self._big())
        self.assertLessEqual(sum(len(json.dumps(v, ensure_ascii=False)) for v in fitted.values()),
                             GENERAL_EVIDENCE_CHAR_BUDGET)
        self.assertIn("PRICE", fitted)
        self.assertIn("PER", fitted)
        self.assertNotIn("PBR", fitted)
        self.assertIn("CMP_2024_2025_revenue", fitted)
        self.assertNotIn("CMP_2023_2024_revenue", fitted)

    def test_required_ids_are_never_dropped(self):
        fitted = _fit_general_evidence(self._big(), ("PBR", "CMP_2023_2024_revenue"))
        self.assertIn("PBR", fitted)
        self.assertIn("CMP_2023_2024_revenue", fitted)


class BuyJudgmentRefreshTests(unittest.TestCase):
    class _News:
        def __init__(self, status, retrieved_at):
            self.status, self.retrieved_at = status, retrieved_at

    class _Result:
        def __init__(self, news, dart):
            self.news = news
            self.section_status = {"dart": dart}

    def test_buy_question_fetches_missing_news_or_dart_only_when_uncollected(self):
        from src.models import now_kst
        now = now_kst()
        missing = self._Result(self._News("not_collected", now), "not_collected")
        done = self._Result(self._News("ok", now), "ok")
        self.assertTrue(needs_data(missing, "all", "삼성전자 지금 사도 될까?", now=now, dart_enabled=True))
        self.assertFalse(needs_data(done, "all", "삼성전자 지금 사도 될까?", now=now, dart_enabled=True))
        self.assertFalse(needs_data(missing, "all", "삼성전자 요약해줘", now=now, dart_enabled=True))


if __name__ == "__main__":
    unittest.main()