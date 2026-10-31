"""가상 자료로 실제 LLM의 이슈 구조·출처·짧은 답변을 검사한다. 시장 자료 검사가 아니다."""
import argparse
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.agents.chat import answer_question
from src.agents import chat
from src.agents import report as report_agent
from src.analysis_flow import analysis_response
from src.config import load_settings
from src.agents.rate_control import paced_verification, current_pacer
from src.models import AnalysisResult, AppError, AnnualFinancialSummary, FinancialData, KST, NewsData, NewsArticle, StockCandidate, now_kst


@paced_verification()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", action="append", choices=("issues", "summary", "per", "followup", "conflict", "missing", "financial", "basic_report"),
                        help="선택한 사례만 실행한다. 여러 번 지정할 수 있다.")
    parser.add_argument("--pause-seconds", type=float, default=0, help="추가 사례 간 대기(초). 모든 실제 요청에는 별도로 최소 65초 간격 적용")
    args = parser.parse_args()
    if not 0 <= args.pause_seconds <= 60:
        parser.error("사례 간 대기는 0~60초로 지정합니다.")
    if args.output.exists():
        parser.error("기존 검수 기록을 덮어쓰지 않도록 새 출력 경로를 지정합니다.")
    settings = load_settings()
    stock = StockCandidate("가상검수회사", "123456", "KOSPI", "123456.KS")
    retrieved = now_kst()
    finance = FinancialData(stock, 10000, 12.5, retrieved,
                            price_at=datetime(2026, 10, 20, 15, 30, tzinfo=KST))
    news = NewsData((
        NewsArticle(1, "가상검수회사 신규 생산라인 가동 계획 발표", "https://example.com/plan", "2026-10-19T09:00:00+09:00", "example.com"),
        NewsArticle(2, "가상검수회사 별도 공급 계약 취소 공시", "https://example.org/cancel", "2026-10-20T09:00:00+09:00", "example.org"),
    ), retrieved)
    result = AnalysisResult("가상테마", (stock,), finance, news, None, result_id="synthetic-block-evaluation")
    cases = [
        ("issues", "이 종목의 뉴스 이슈를 분석해줘", []),
        ("summary", "이 종목 뉴스를 세 줄로 요약해줘", []),
        ("per", "이 종목의 PER을 어떻게 해석해야 합니까?", []),
        ("followup", "그러면 그 발표로 실적 개선이 확정된 건가요?", [
            {"role": "user", "text": "이 종목의 생산라인 뉴스는 무엇입니까?"},
            {"role": "assistant", "text": "제목에는 신규 생산라인 가동 계획 발표가 담겨 있습니다."},
        ]),
        ("conflict", "기사마다 가동 여부가 다른데 실제 가동을 시작한 건가요?", []),
        ("missing", "이 종목의 PBR가 없는데 회사가 공시를 안 해서 그런 건가요? 왜 그런지 해석해줘", []),
        ("financial", "매출이 늘었으면 실적이 좋아진 거야?", [
            {"role": "user", "text": "가상검수회사의 최근 실적을 보여줘"},
        ]),
        ("basic_report", "반도체 테마에서 가상검수회사 선택", []),
    ]
    selected = args.case or ["issues", "summary", "per", "followup"]
    cases = [case for case in cases if case[0] in selected]
    report = {"checked_at": retrieved.isoformat(), "synthetic_data": True, "model": settings.groq_model,
              "cases": [], "sha256": {path: hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in
                                      ("src/agents/chat.py", "src/agents/answer_quality.py", "src/agents/transport.py", "src/agents/rate_control.py", "src/models.py", "src/ui/answer.py", "src/agents/evidence.py", "src/agents/grounding.py", "src/agents/report.py", "src/analysis_flow.py", "src/data/financial_comparison.py", "src/agents/financial_numbers.py", "src/agents/report_presentation.py", "src/agents/schema_diagnostics.py", "src/source_presentation.py")}}
    from dataclasses import replace
    for case_index, (case_id, question, history) in enumerate(cases):
        if case_index:
            time.sleep(args.pause_seconds)
        case_result = result
        if case_id in {"financial", "basic_report"}:
            case_result = replace(result, theme="반도체", annual_summaries=(
                AnnualFinancialSummary("2024", revenue=10_000_000_000, operating_income=1_000_000_000),
                AnnualFinancialSummary("2025", revenue=12_000_000_000, operating_income=1_800_000_000),
            ), news=replace(news, articles=(
                NewsArticle(1, "가상검수회사 반도체 메모리 생산라인 가동 계획 발표", "https://example.com/memory", "2026-10-19T09:00:00+09:00", "example.com"),
                NewsArticle(2, "가상그룹 지주회사 이사회 경영 강화", "https://example.org/governance", "2026-10-20T09:00:00+09:00", "example.org"),
            )))
        if case_id == "conflict":
            case_result = replace(result, news=replace(news, articles=(
                NewsArticle(1, "가상검수회사 신규 생산라인 가동 개시 보도", "https://example.com/start", "2026-10-19T09:00:00+09:00", "example.com"),
                NewsArticle(2, "가상검수회사 신규 생산라인 가동 여부 미확인 보도", "https://example.org/unknown", "2026-10-20T09:00:00+09:00", "example.org"),
            )))
        started = time.perf_counter()
        # 실제 호출은 그대로 수행하며 가상 검수 입력의 파싱된 응답만 기록한다.
        trace = []
        original_invoke = chat._invoke
        original_report_invoke = report_agent._invoke
        original_check = chat._check_answer
        def audited_invoke(*call_args, **call_kwargs):
            response = original_invoke(*call_args, **call_kwargs)
            request = call_args[2]
            trace.append({"task": request.get("task", "basic_report" if "headlines" in request else None),
                          "response": response, "selected_evidence_ids": list(request.get("evidence", {})),
                          "selection": request.get("selection"),
                          "displayed_data_sources": request.get("displayed_data_sources", [])})
            return response
        def audited_check(*call_args, **call_kwargs):
            try:
                return original_check(*call_args, **call_kwargs)
            except AppError as error:
                trace.append({"task": "answer_validation", "error_code": error.code})
                raise
        chat._invoke = audited_invoke
        report_agent._invoke = audited_invoke
        chat._check_answer = audited_check
        try:
            if case_id == "basic_report":
                commentary = report_agent.generate_commentary(case_result.theme, case_result.financial, case_result.news, settings)
                answer = analysis_response(replace(case_result, commentary=commentary))
            else:
                answer = answer_question(question, case_result, history, settings)
            text, refs, follow = answer
            report["cases"].append({"question": question, "status": "returned", "text": text,
                "blocks": [asdict(b) for b in getattr(answer, "blocks", ())],
                "evidence_ids": [r["id"] for r in refs], "follow_up": follow,
                "path": ("verified_metric_fallback" if any(r.get("answer_origin") == "verified_metric_fallback" for r in refs)
                         else "live_llm" if any(t.get("task") in {"chat_answer", "basic_report"} for t in trace) else "direct_code"),
                "elapsed_seconds": round(time.perf_counter()-started, 2), "quality_review": "pending"})
        except AppError as error:
            report["cases"].append({"question": question, "status": "error", "error_code": error.code, "message": error.message})
        finally:
            chat._invoke = original_invoke
            report_agent._invoke = original_report_invoke
            chat._check_answer = original_check
        report["cases"][-1]["case_id"] = case_id
        report["cases"][-1]["fixture"] = {"question_history": history, "evidence": chat.build_evidence(case_result)}
        report["cases"][-1]["parsed_response_trace"] = trace
        report["rate_control"] = current_pacer().report()
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print(json.dumps({key: report["cases"][-1].get(key) for key in ("case_id", "status", "error_code", "elapsed_seconds")}), flush=True)
        if report["cases"][-1].get("error_code") in {"ai_auth", "ai_rate_limit", "ai_verification_budget"}:
            break


if __name__ == "__main__":
    main()
