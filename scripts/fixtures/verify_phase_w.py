"""W-B: 고정 가상 자료와 실제 localhost LLM을 분리해 검수한다.

금융 API/클라우드 연결은 차단한다. 최초 생성·심사·재작성 원문을 보존하고
품질 점수는 이 스크립트가 자동 승인하지 않는다. 서버를 시작/재시작하지 않는다.
"""
import argparse
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2] if Path(__file__).resolve().parent.name == "fixtures" else Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from llm_fixture import synthetic_result
from src.config import load_settings
from src.models import AppError, NewsArticle, now_kst
from src.agents import chat, report, request, news_relevance
from src.agents.local_verification import local_verification
from src.agents.transport import _invoke


QUESTIONS = {
    "summary": "삼성전자 종목 이슈 세 줄 요약",
    "overview": "삼성전자 어떻게 생각해?",
    "issues": "최근 주요 이슈 요약해 줘",
    "followup": "그 투자 발표로 앞으로 매출이 늘어나는 거야?",
}


def fixture():
    """실제 상장 이름을 사용하는 가상 수치/기사이며 시장 자료가 아니다."""
    base = synthetic_result()
    stock = replace(base.financial.stock, name="삼성전자", code="005930", ticker="005930.KS")
    news = (
        NewsArticle(1, "삼성전자 반도체 메모리 생산라인 투자 계획 발표",
                    "https://example.com/investment", "2026-10-26T09:00:00+09:00", "example.com",
                    description="삼성전자는 반도체 메모리 생산라인에 2000억원 투자 계획을 발표했습니다. 수요에 대응하기 위한 투자이며 가동 시점은 정해지지 않았습니다."),
        NewsArticle(2, "삼성전자 반도체 메모리 생산라인 투자 계획 보도",
                    "https://example.org/same-investment", "2026-10-26T10:00:00+09:00", "example.org",
                    description="삼성전자는 반도체 메모리 생산라인에 2000억원 투자 계획을 발표했습니다. 같은 투자 발표를 다룬 보도입니다."),
        NewsArticle(3, "가상지주 이사회 경영 강화",
                    "https://example.net/unrelated", "2026-10-26T11:00:00+09:00", "example.net"),
    )
    return replace(base, candidates=(stock,), financial=replace(base.financial, stock=stock),
                   news=replace(base.news, articles=news), result_id="phase-w-synthetic-samsung")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", choices=tuple(QUESTIONS), action="append")
    parser.add_argument("--max-requests", type=int, default=4)
    parser.add_argument("--max-seconds", type=float, default=420)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("검수 원문은 덮어쓰지 않습니다. 새 파일을 지정하십시오.")
    settings = replace(load_settings(), ai_provider="local", groq_api_key="", news_relevance_mode="strict")
    result = fixture()
    record = dict(checked_at=now_kst().isoformat(), synthetic_data=True,
                  fixture_warning="삼성전자 이름/코드 외 모든 기사·수치는 가상 자료입니다.",
                  provider="local", model=settings.local_model, base_url=settings.local_base_url,
                  max_requests=args.max_requests, max_seconds=args.max_seconds,
                  quality_review="pending_engineer_review", cases=[],
                  sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in [*ROOT.glob("src/**/*.py"), Path(__file__), ROOT / "scripts/llm_fixture.py"]})
    connect = socket.socket.connect

    def local_only(sock, address):
        host = address[0]
        if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
            raise AssertionError("W-B 중 금융 API/외부 연결은 금지됩니다.")
        return connect(sock, address)

    with ExitStack() as stack:
        stack.enter_context(patch("socket.socket.connect", local_only))
        cloud = stack.enter_context(patch("langchain_groq.ChatGroq", side_effect=AssertionError("Groq 호출 금지")))
        run = stack.enter_context(local_verification(max_requests=args.max_requests, max_seconds=args.max_seconds))
        for case_id in args.case or ["summary", "overview", "issues"]:
            trace = []

            def audited(*values, **kwargs):
                entry = {"task": values[2].get("task"), "request": deepcopy(values[2]), "max_tokens": values[3]}
                trace.append(entry)
                output = _invoke(*values, **kwargs)
                entry["response"] = output
                return output

            started = time.monotonic()
            case = {"id": case_id, "question": QUESTIONS[case_id], "result_id": result.result_id}
            history = ([{"role": "user", "text": QUESTIONS["summary"], "result_id": result.result_id}]
                       if case_id == "followup" else [])
            try:
                with ExitStack() as calls:
                    for module in (chat, report, request, news_relevance):
                        calls.enter_context(patch.object(module, "_invoke", audited))
                    answer = chat.answer_question(QUESTIONS[case_id], result, history, settings)
                body, refs, follow = answer
                case.update(status="returned", text=body, evidence_ids=[r["id"] for r in refs],
                            follow_up=follow, blocks=[asdict(b) for b in getattr(answer, "blocks", ())],
                            path="fallback" if any(r.get("answer_origin") for r in refs) else "local_llm")
            except AppError as error:
                case.update(status="error", error_code=error.code, message=error.message)
            except AssertionError as error:
                case.update(status="error", error_code="verification_boundary", message=str(error))
            finally:
                case.update(elapsed_seconds=round(time.monotonic() - started, 3), trace=trace)
                case["generation_count"] = sum(t["task"] == "chat_answer" for t in trace)
                record["cases"].append(case)
                record.update(requests=run.requests, events=run.events, groq_client_calls=cloud.call_count)
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({k: case.get(k) for k in ("id", "status", "error_code", "elapsed_seconds")}), flush=True)
            if case["status"] != "returned":
                break
    return int(any(c["status"] != "returned" for c in record["cases"]))


if __name__ == "__main__":
    sys.exit(main())
