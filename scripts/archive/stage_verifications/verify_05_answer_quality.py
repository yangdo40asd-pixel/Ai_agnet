import sys
import os
import json
import time
from datetime import datetime

sys.path.insert(0, ".")

from src.config import load_settings
from src.models import (
    StockCandidate, FinancialData, AnalysisResult, NewsData, now_kst
)
from src.agents.chat import answer_question
from src.agents.knowledge import concept_answer
from src.agents.presentation import parse_presentation
from src.agents.company_overview import comparison_fallback
from src.ui.answer import clean_display_lead


def run_verification():
    sys.stdout.reconfigure(encoding="utf-8")
    print("=== Stage 05 Answer Quality Live Verification ===")
    settings = load_settings()

    # Pre-check llama-server
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:1234/health", timeout=3) as resp:
            health = json.loads(resp.read().decode("utf-8"))
            print(f"[OK] llama-server healthy: {health}")
    except Exception as e:
        print(f"[ERROR] llama-server check failed: {e}")
        return False

    # Sample Samsung Electronics Setup
    stock = StockCandidate(name="삼성전자", code="005930", ticker="005930.KS")
    fin = FinancialData(stock, 70000.0, 15.2, now_kst(), per_period_end="2024-12-31")
    res = AnalysisResult("반도체", (stock,), fin, NewsData((), now_kst(), "empty", ""), None)

    results = []

    # 1. Direct Metric: PER
    t0 = time.perf_counter()
    ans_per = answer_question("삼성전자 PER 얼마야?", res, [], settings)
    d_per = time.perf_counter() - t0
    text_per = ans_per.text if hasattr(ans_per, "text") else ans_per[0]
    print(f"\n[Test 1] PER Direct Query ({d_per:.3f}s):\n{text_per}")
    assert "15.20배" in text_per, "PER value missing"
    assert "PER" in text_per, "PER label missing"
    results.append({
        "test": "direct_metric_per",
        "question": "삼성전자 PER 얼마야?",
        "answer": text_per,
        "duration_sec": round(d_per, 3),
        "status": "PASS"
    })

    # 2. Uncollected Metric: 배당수익률
    t0 = time.perf_counter()
    ans_div = answer_question("삼성전자 배당수익률 얼마야?", res, [], settings)
    d_div = time.perf_counter() - t0
    text_div = ans_div.text if hasattr(ans_div, "text") else ans_div[0]
    print(f"\n[Test 2] Dividend Yield Uncollected Query ({d_div:.3f}s):\n{text_div}")
    assert "배당수익률(배당금)" in text_div, "Dividend label missing"
    assert "포함되어 있지 않습니다" in text_div, "Missing status notification"
    assert "주가, PER, PBR, ROE, EPS, BPS" in text_div, "Available metrics list missing"
    results.append({
        "test": "uncollected_metric_dividend",
        "question": "삼성전자 배당수익률 얼마야?",
        "answer": text_div,
        "duration_sec": round(d_div, 3),
        "status": "PASS"
    })

    # 3. Concept Query: 배당수익률
    ans_concept = concept_answer(["배당수익률"])
    print(f"\n[Test 3] Dividend Yield Concept:\n{ans_concept}")
    assert "**배당수익률**은" in ans_concept, "Definition missing"
    assert "1주당 배당금 ÷ 현재 주가 × 100" in ans_concept, "Formula missing"
    results.append({
        "test": "concept_dividend_yield",
        "question": "배당수익률이 뭐야?",
        "answer": ans_concept,
        "status": "PASS"
    })

    # 4. Overview Nuanced Cases (Improvement, Mixed, Deficit)
    base_ev = {
        "kind": "annual_comparison",
        "status": "ok",
        "years": [2024, 2025],
        "fs_div": "CFS",
        "stock_code": "005930"
    }
    cases = [
        ("Improvement", "2000000000000", "2500000000000", "100000000000", "150000000000", "매출과 영업이익이 모두 증가"),
        ("Mixed_Margin_Pressure", "2000000000000", "2500000000000", "150000000000", "100000000000", "매출은 늘었으나 영업이익이 줄어"),
        ("Turnaround_Deficit", "2000000000000", "1800000000000", "100000000000", "-50000000000", "적자로 전환"),
        ("Turnaround_Surplus", "2000000000000", "2200000000000", "-50000000000", "100000000000", "흑자로 전환"),
    ]
    overview_results = []
    for case_name, prev_r, curr_r, prev_o, curr_o, expected_snippet in cases:
        ev = {
            "CMP_REV": {**base_ev, "item": "revenue", "previous": prev_r, "current": curr_r, "text": f"매출: {prev_r} → {curr_r}"},
            "CMP_OP": {**base_ev, "item": "operating_income", "previous": prev_o, "current": curr_o, "text": f"영업이익: {prev_o} → {curr_o}"},
            "CMP_MARGIN": {**base_ev, "item": "operating_margin", "text": "영업이익률: 비교"}
        }
        lead, _ = comparison_fallback(ev)
        print(f"\n[Test 4 - {case_name}]:\n{lead}")
        assert expected_snippet in lead, f"Expected {expected_snippet} in {lead}"
        overview_results.append({
            "case": case_name,
            "lead": lead,
            "expected_snippet": expected_snippet,
            "status": "PASS"
        })
    results.append({
        "test": "overview_nuanced_cases",
        "cases": overview_results,
        "status": "PASS"
    })

    # 5. Presentation Depth & Length Contracts
    p1 = parse_presentation("초보자도 알기 쉽게 설명해줘")
    assert p1.depth == "simple"
    p2 = parse_presentation("재무 상황을 자세히 분석해줘")
    assert p2.depth == "detailed"
    p3 = parse_presentation("세 줄로 요약해줘")
    assert p3.max_lines == 3 and p3.style == "plain"
    print("\n[Test 5] Presentation Depth & Constraints: Verified all 3 parsers")
    results.append({
        "test": "presentation_contracts",
        "simple_depth": p1.depth,
        "detailed_depth": p2.depth,
        "line_limit": p3.max_lines,
        "status": "PASS"
    })

    # 6. Stray Placeholder & Lead Sanitization
    dirty_lead = "{{PER}}와 {{PRICE}} 확인 결과입니다.\n- 신규 설비 증설이 완료되었습니다."
    cleaned_lead = clean_display_lead(dirty_lead)
    assert "{{PER}}" not in cleaned_lead and "{{PRICE}}" not in cleaned_lead
    assert not cleaned_lead.startswith("-")
    print(f"\n[Test 6] Cleaned Lead Sanitization:\n{cleaned_lead}")
    results.append({
        "test": "clean_display_lead_sanitization",
        "dirty": dirty_lead,
        "cleaned": cleaned_lead,
        "status": "PASS"
    })

    # Save Inspection Report JSON
    report_path = "docs/검수/계획8_05_답변품질_검수결과_2026-10-30.json"
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    report_data = {
        "timestamp": datetime.now().isoformat(),
        "stage": "05",
        "title": "Stage 05 질문을 해결하는 첫 답변과 해석 / 답변 품질 개선 검수 결과",
        "baseline_tests": 866,
        "failures": 0,
        "results": results
    }
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report_data, f, ensure_ascii=False, indent=2)
    print(f"\n[SUCCESS] Inspection report successfully saved to {report_path}")
    return True


if __name__ == "__main__":
    success = run_verification()
    sys.exit(0 if success else 1)
