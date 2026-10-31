"""저장한 가상 검수 응답을 실제 의미 검증기에 다시 전달한다. 생성 성공 검사가 아니다."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.agents import chat
from src.agents.answer_quality import answer_context, model_evidence
from src.agents.knowledge import TERMS
from src.config import load_settings
from src.agents.rate_control import paced_verification, current_pacer
from src.models import AppError, now_kst


@paced_verification()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("새 출력 경로가 필요합니다.")
    saved = json.loads(args.input.read_text(encoding="utf-8-sig"))
    if saved.get("synthetic_data") is not True:
        parser.error("가상 검수 입력만 지원합니다.")
    settings = load_settings()
    report = {"checked_at": now_kst().isoformat(), "synthetic_data": True, "model": settings.groq_model,
              "source": str(args.input), "cases": [], "sha256": {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
              for p in ("src/agents/chat.py", "src/agents/answer_quality.py", "src/agents/transport.py", "src/agents/rate_control.py")}}
    cases = [c for c in saved["cases"] if c.get("case_id") in args.case]
    if len(cases) != len(set(args.case)):
        parser.error("지정한 사례를 입력 파일에서 찾지 못했습니다.")
    for index, case in enumerate(cases):
        question = case["question"]
        history = case["fixture"]["question_history"]
        payload = next(t["response"] for t in reversed(case["parsed_response_trace"]) if t["task"] == "chat_answer")
        required = [k for k in TERMS if k in question.upper()]
        evidence, requirements = answer_context(question, history, case["fixture"]["evidence"], required)
        request = {"question": question, "answer_style": "issues" if payload.get("blocks") else "plain",
                   "evidence": model_evidence(evidence), "conversation": chat.conversation_context(history),
                   "concept_reference": {k: TERMS[k] for k in required}, "answer_requirements": requirements}
        original = chat._invoke
        trace = []
        def audited(*a, **kw):
            response = original(*a, **kw)
            trace.append({"task": a[2]["task"], "response": response})
            return response
        chat._invoke = audited
        item = {"case_id": case["case_id"], "question": question,
                "fixture": case["fixture"], "original_payload": payload}
        try:
            answer = chat._check_answer(payload, evidence, required, None, request, settings, question)
            item.update(status="accepted", checked_text=answer.text)
        except AppError as error:
            item.update(status="rejected" if not error.code.startswith("ai_") else "not_evaluated", error_code=error.code)
        finally:
            chat._invoke = original
        item["parsed_response_trace"] = trace
        if case.get("expected_status") in {"accepted", "rejected"}:
            item["expected_status"] = case["expected_status"]
            item["matches_expected"] = (item["status"] == case["expected_status"]
                                        if item["status"] != "not_evaluated" else None)
        report["cases"].append(item)
        report["rate_control"] = current_pacer().report()
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        print(json.dumps({k: item.get(k) for k in ("case_id", "status", "error_code", "matches_expected")}), flush=True)
        if item.get("error_code") in {"ai_rate_limit", "ai_auth", "ai_verification_budget"}:
            break


if __name__ == "__main__":
    main()
