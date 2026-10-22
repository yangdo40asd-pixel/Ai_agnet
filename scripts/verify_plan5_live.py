"""설정된 LLM의 답변·분류를 가상 검수 자료로 확인한다. 실제 투자 데이터 검사가 아니다."""
from pathlib import Path
import hashlib
import json
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.agents.chat import answer_question
from src.agents.request import route_message
from src.config import load_settings
from src.models import AnalysisResult, AppError, FinancialData, NewsData, StockCandidate, now_kst

if __name__ == "__main__":
    settings = load_settings()
    stock = StockCandidate("가상검수회사", "123456", "KOSPI", "123456.KS")
    result = AnalysisResult("가상테마", (stock,), FinancialData(stock, 10000, 12.5, now_kst()),
                            NewsData((), now_kst(), "empty", "검수용 빈 뉴스"), None, result_id="synthetic-only")
    records = []
    for question, current in (("이 종목의 PER을 어떻게 해석해야 합니까?", result),
                              ("매수와 매도의 차이는 무엇입니까?", None),
                              ("현재 PBR은 왜 없습니까?", result)):
        started = time.perf_counter()
        try:
            text, evidence, follow = answer_question(question, current, [], settings)
            records.append({"question": question, "status": "returned", "text": text,
                            "evidence_ids": [e["id"] for e in evidence], "follow_up": follow,
                            "elapsed_seconds": round(time.perf_counter()-started, 2),
                            "path": "verified_metric_fallback" if any(e.get("answer_origin") == "verified_metric_fallback" for e in evidence)
                                    else "deterministic" if "PBR" in question else "live_llm",
                            "quality_review": "needs_human_review"})
        except AppError as error:
            records.append({"question": question, "status": "error", "error_code": error.code, "message": error.message})
            if error.code in {"ai_rate_limit", "ai_auth"}:
                break
    try:
        intent = route_message("테마 검색 말고 삼성전자만 보고 싶습니다.", None, None, [], settings)
        records.append({"question": "테마 검색 말고 삼성전자만 보고 싶습니다.", "status": "classified", "intent": intent.__dict__})
    except AppError as error:
        records.append({"task": "route", "status": "error", "error_code": error.code})
    report = {"checked_at": now_kst().isoformat(), "model": settings.groq_model, "synthetic_data": True,
              "cases": records, "sha256": {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
                  for p in ("src/agents/chat.py", "src/agents/request.py", "src/ui/app.py")}}
    output = ROOT / "docs/검수/계획5_실제LLM_검수.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "cases": records}, ensure_ascii=True))
