"""계획4의 대화 답변·유도 질문 세 사례만 실제 AI로 검사한다. 금융 API는 호출하지 않는다."""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.agents.chat import answer_question, validate_follow_up
from src.config import load_settings
from src.models import AnalysisResult, AppError, FinancialData, NewsData, StockCandidate, now_kst


def run_cases(settings, only: str | None = None) -> dict:
    stock = StockCandidate("검수용가상회사", "999999", "KOSPI", "999999.KS")
    result = AnalysisResult(
        "가상 검수", (stock,), FinancialData(stock, 10000, 12.5, now_kst()),
        NewsData((), now_kst()), None,
    )
    report = {
        "checked_at": now_kst().isoformat(), "model": settings.groq_model,
        "scope": "AI 답변과 유도 질문만 검사. 실제 금융·뉴스·DART 조회 제외.",
        "external_ai_mocked": False, "browser_or_server_started": False, "cases": [],
    }
    for kind, question, analysis, required in (
        ("general_term", "PER는 무슨 뜻이야?", None, set()),
        ("selected_per", "현재 종목의 PER를 쉽게 설명해줘", result, {"PER"}),
        ("missing_pbr", "현재 종목의 PBR 정보가 없어. 어떻게 이해해야 해?", result, {"PBR"}),
    ):
        if only and kind != only:
            continue
        item = {"kind": kind, "checked_at": now_kst().isoformat(),
                "synthetic_stock_data": analysis is not None}
        started = time.monotonic()
        try:
            _answer, evidence, follow = answer_question(question, analysis, [], settings)
            validate_follow_up(follow)
            actual = {entry["id"] for entry in evidence}
            if (required and not required.issubset(actual)) or (analysis is None and actual):
                raise AppError("live_evidence", "검사에서 요구한 근거를 확인하지 못했습니다.")
            item.update(success=True, evidence_ids=sorted(actual), follow_up_valid=True)
        except Exception as error:
            # 응답 본문·키·외부 예외 메시지는 기록하지 않는다.
            item.update(success=False, error_type=type(error).__name__)
            if isinstance(error, AppError):
                item["error_code"] = error.code
        item["seconds"] = round(time.monotonic() - started, 3)
        report["cases"].append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    report["success"] = all(item["success"] for item in report["cases"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--case", choices=["general_term", "selected_per", "missing_pbr"])
    parser.add_argument("--output", type=Path, default=ROOT / "검수자료" / "계획4_대화_API_검수.json")
    args = parser.parse_args()
    if not args.live:
        parser.error("실제 AI 호출에는 --live를 명시해 주세요.")
    report = run_cases(load_settings(), args.case)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
