"""명시한 localhost 모델만 실제 호출한다. 금융 API·Groq 호출은 차단한다."""
import argparse
from contextlib import ExitStack
from dataclasses import asdict, replace
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]
from src.config import load_settings
from src.models import AppError, ChatResponse, now_kst
from src.agents import chat, report as report_agent
from src.agents.grounding import review_response
from src.agents.local_verification import local_verification
from src.agents.transport import _invoke
from src.analysis_flow import analysis_response
from llm_fixture import synthetic_result
from evaluation_contract import live_contract, assess_contract, validate_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:1234/v1")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-requests", type=int, default=12)
    parser.add_argument("--news-policy", choices=["standard", "strict"], default="strict")
    parser.add_argument("--case", action="append", choices=["schema", "financial", "per", "basic_report", "followup", "mixed", "mixed_saved", "false_claim", "unrelated", "candidates", "route", "candidate_retry"])
    parser.add_argument("--saved-record", type=Path, help="mixed_saved에서 이전 가상 생성 원문을 재검증. 새 생성 성공으로 세지 않음")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("기존 검수 기록을 덮어쓰지 않도록 새 출력 경로를 사용합니다.")
    settings = replace(load_settings(), ai_provider="local", groq_api_key="", local_model=args.model, local_base_url=args.base_url,
                       news_relevance_mode=args.news_policy)
    result = synthetic_result()
    try:
        validate_dataset(result)
    except ValueError as error:
        parser.error(str(error))
    cases = args.case or ["schema", "financial", "basic_report", "per", "false_claim"]
    saved_payload = None
    if "mixed_saved" in cases:
        if not args.saved_record or args.saved_record.stat().st_size > 2_000_000:
            parser.error("mixed_saved는 2MB 이내의 이전 가상 검수 기록이 필요합니다.")
        saved = json.loads(args.saved_record.read_text(encoding="utf-8"))
        if saved.get("synthetic_data") is not True:
            parser.error("가상 자료 기록만 재검증합니다.")
        saved_payload = next(c["trace"][0]["response"] for c in saved["cases"] if c["id"] == "mixed")
    source_paths = [*ROOT.glob("src/agents/providers/*.py"), ROOT / "src/config.py", ROOT / "src/agents/transport.py",
                    ROOT / "src/agents/output_contract.py", ROOT / "src/agents/grounding.py", ROOT / "src/agents/chat.py",
                    ROOT / "src/agents/report.py", ROOT / "src/agents/local_verification.py",
                    ROOT / "src/agents/financial_numbers.py", ROOT / "src/agents/answer_quality.py",
                    ROOT / "src/agents/news_relevance.py", ROOT / "src/models.py", ROOT / "src/pipeline.py",
                    Path(__file__).resolve(), ROOT / "scripts/llm_fixture.py", ROOT / "scripts/evaluation_contract.py"]
    record = {"checked_at": now_kst().isoformat(), "synthetic_data": True, "provider": "local", "model": args.model,
              "base_url": args.base_url, "cases": [], "sha256": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}}
    record["news_policy"] = args.news_policy
    connect = socket.socket.connect

    def local_only(sock, address):
        host = address[0]
        if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
            raise AssertionError("실제 로컬 검수 중 외부 연결 금지")
        return connect(sock, address)

    with ExitStack() as stack:
        stack.enter_context(patch("socket.socket.connect", local_only))
        cloud = stack.enter_context(patch("langchain_groq.ChatGroq", side_effect=AssertionError("Groq 호출 금지")))
        run = stack.enter_context(local_verification(max_requests=args.max_requests))
        for case_id in cases:
            trace = []
            replayed = False
            from src.agents import request as request_agent
            from src.agents import news_relevance as news_policy
            original_chat, original_report, original_route, original_policy = chat._invoke, report_agent._invoke, request_agent._invoke, news_policy._invoke

            def audited(*values, **kwargs):
                nonlocal replayed
                request = values[2]
                is_replay = case_id == "mixed_saved" and request.get("task") == "chat_answer" and not replayed
                if is_replay:
                    replayed = True
                    output = json.loads(json.dumps(saved_payload, ensure_ascii=False))
                else:
                    output = _invoke(*values, **kwargs)
                trace.append({"task": request.get("task", "basic_report" if "headlines" in request else "candidates"),
                              "origin": "saved_generation" if is_replay else "live_local",
                              "response": output, "evidence_ids": list(request.get("evidence", {})),
                              "displayed_data_sources": request.get("displayed_data_sources", [])})
                return output

            chat._invoke = report_agent._invoke = request_agent._invoke = news_policy._invoke = audited
            started = time.monotonic()
            case = {"id": case_id, "quality_review": "pending"}
            try:
                if case_id == "schema":
                    response = audited(settings, "한국어로 PER을 설명하는 JSON을 작성합니다. text, evidence_ids, follow_up, blocks가 필요합니다. 근거와 블록은 빈 배열입니다.",
                                       {"task": "chat_answer", "answer_style": "plain", "evidence": {}}, 250)
                    assert set(response) == {"text", "evidence_ids", "follow_up", "blocks"}
                    case["response"] = response
                elif case_id == "candidates":
                    case["response"] = report_agent.propose_candidates("반도체", settings)
                elif case_id == "candidate_retry":
                    case["response"] = report_agent.propose_candidates("반도체", settings, rejected_names=("가상반도체",),
                                           available_names=("삼성전자", "SK하이닉스", "한미반도체"))
                elif case_id == "route":
                    intent = request_agent.route_message("반도체 쪽을 알아보고 싶은데", None, "", [], settings)
                    case["response"] = asdict(intent)
                    if intent.action != "discover" or "반도체" not in intent.theme:
                        raise AppError("route_mismatch", "관심 테마 탐색 의도를 유지하지 못했습니다.")
                elif case_id == "basic_report":
                    commentary = report_agent.generate_commentary(result.theme, result.financial, result.news, settings)
                    answer = analysis_response(replace(result, commentary=commentary))
                    case["text"], case["blocks"] = answer.text, [asdict(b) for b in answer.blocks]
                elif case_id in {"false_claim", "unrelated"}:
                    key = "NEWS_1" if case_id == "false_claim" else "NEWS_2"
                    evidence = {key: chat.build_evidence(result)[key]}
                    text = "수집된 뉴스 제목 기준입니다. " + ("생산라인 가동이 완료됐습니다." if case_id == "false_claim"
                              else "가상그룹 지주회사의 이사회 경영 강화 소식이 보도되었습니다.")
                    response = ChatResponse(text, [dict(evidence[key], id=key)], lead_evidence_ids=(key,))
                    verdict, units = review_response(response, evidence,
                        {"question": "생산라인이 실제 가동됐습니까?" if case_id == "false_claim" else "실적과 관련 뉴스를 함께 설명해 주세요.",
                         "stock_name": result.financial.stock.name, "theme": result.theme, "concept_reference": {}}, settings, audited)
                    case["verdict"] = verdict
                    rejected = verdict.get("supported") is False if case_id == "false_claim" else verdict.get("checks", {}).get("question_focus") is False
                    if not rejected:
                        raise AppError("review_false_accept", "계획을 실행 완료로 바꾸거나 무관한 기사를 포함한 오답을 검증기가 허용했습니다.")
                else:
                    questions = {"financial": "매출이 늘었으면 실적이 좋아진 거야?", "per": "이 종목의 PER을 어떻게 해석해야 합니까?",
                                 "followup": "그러면 그 발표로 실적 개선이 확정된 건가요?", "mixed": "실적과 관련 뉴스를 함께 설명해 주세요."}
                    history = [{"role": "user", "text": "생산라인 뉴스는 무엇입니까?"}] if case_id == "followup" else []
                    question = questions["mixed" if case_id == "mixed_saved" else case_id]
                    answer = chat.answer_question(question, result, history, settings)
                    text, refs, follow = answer
                    case.update(question=question, text=text, evidence_ids=[r["id"] for r in refs], follow_up=follow,
                                blocks=[asdict(b) for b in getattr(answer, "blocks", ())],
                                path="saved_generation_local_review" if case_id == "mixed_saved" else "fallback" if any(r.get("answer_origin") for r in refs) else "local_llm")
                    if case_id == "mixed_saved":
                        case["saved_record"] = str(args.saved_record)
                        if any(item["task"] == "chat_answer" and item["origin"] == "live_local" for item in trace):
                            case["path"] = "saved_answer_rejected_then_live_rewrite"
                case["status"] = "returned"
                contract = live_contract(case_id)
                if contract is not None:
                    case["contract_check"] = assess_contract(case, contract)
                    if case["contract_check"]["status"] == "failed":
                        case["quality_review"] = "failed_contract"
            except AppError as error:
                case.update(status="error", error_code=error.code, message=error.message)
            finally:
                chat._invoke, report_agent._invoke, request_agent._invoke, news_policy._invoke = original_chat, original_report, original_route, original_policy
                case.update(elapsed_seconds=round(time.monotonic() - started, 3), trace=trace)
                record["cases"].append(case)
                record["requests"] = run.requests
                record["events"] = run.events
                record["groq_client_calls"] = cloud.call_count
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                print(json.dumps({k: case.get(k) for k in ("id", "status", "error_code", "elapsed_seconds")}), flush=True)
            if case.get("error_code") in {"ai_verification_budget", "ai_local_unavailable", "ai_local_timeout", "ai_local_request"}:
                break
            if case.get("contract_check", {}).get("status") == "failed":
                break
    return 1 if any(case["status"] != "returned" or case.get("contract_check", {}).get("status") == "failed"
                    for case in record["cases"]) else 0


if __name__ == "__main__":
    sys.exit(main())
