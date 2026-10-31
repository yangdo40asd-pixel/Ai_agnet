"""Stage 09 실시간 로컬 LLM E2E 수명주기 및 대화 품질 검증 스크립트"""
import sys
import os
import json
from pathlib import Path
from datetime import datetime

# UTF-8 stdout configuration
sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT)]

from src.agents.chat import answer_question
from src.agents.request import route_message, is_closing_request, is_reset_request
from src.config import load_settings
from src.models import (
    AnalysisResult,
    FinancialData,
    PriceHistory,
    NewsData,
    StockCandidate,
    CandidateDiscoveryResult,
)
from src.ui.state import (
    reset_all_state,
    store_candidate_discovery,
    canvas_result_id,
    add_canvas,
    ensure_export_bundle,
)
from src.ui.app import _handle_explicit_canvas_or_export_request


def run_stage09_eval():
    settings = load_settings()
    results = {}

    print("=== [Stage 09: 수명주기 실시간 검증 시작] ===")

    # 1. M01-I2: 직전 답변 두 줄 요약 ("방금 말한 거 두 줄로 요약해줘")
    print("\n--- [시나리오 1: M01-I2 직전 답변 2줄 요약] ---")
    mock_stock_sec = StockCandidate(code="005930", name="삼성전자", market="KOSPI")
    mock_fin_sec = FinancialData(stock=mock_stock_sec, price=72000.0, per=14.5, retrieved_at=datetime(2026, 10, 31))
    mock_res_sec = AnalysisResult(
        theme="AI 반도체",
        candidates=(mock_stock_sec,),
        financial=mock_fin_sec,
        news=NewsData((), datetime(2026, 10, 31)),
        commentary=None,
        price_history=PriceHistory("005930", "005930.KS", ()),
        result_id="res_sec_01",
    )

    from src.analysis_flow import build_evidence

    ev_sec = build_evidence(mock_res_sec)
    real_sec_refs = [dict(ev_sec["PRICE"], id="PRICE"), dict(ev_sec["PER"], id="PER")]

    turn1_msgs = [
        {"role": "user", "text": "삼성전자 주가랑 PER 수준 설명해줘"},
        {
            "role": "assistant",
            "text": "삼성전자의 현재 주가는 72,000원이며 PER은 14.5배입니다.",
            "evidence": real_sec_refs,
        },
    ]

    q_restatement = "방금 말한 거 두 줄로 요약해줘"
    print(f"질문: {q_restatement}")
    resp_restatement = answer_question(q_restatement, mock_res_sec, turn1_msgs, settings)
    text_restatement = resp_restatement.intro if hasattr(resp_restatement, "intro") else resp_restatement[0]
    lines_restatement = [line.strip() for line in text_restatement.split("\n") if line.strip()]

    print(f"답변 전문:\n{text_restatement}")
    print(f"줄 수: {len(lines_restatement)}")
    results["m01_i2_restatement"] = {
        "question": q_restatement,
        "answer": text_restatement,
        "line_count": len(lines_restatement),
        "pass": len(lines_restatement) <= 2,
    }

    # 2. M01-I1 & M01-V1: 전체 대화 요약 ("지금까지 대화 내용 요약해줘")
    print("\n--- [시나리오 2: M01-I1 & V1 전체 대화 요약 (삼성전자 + SK하이닉스)] ---")
    mock_stock_hynix = StockCandidate(code="000660", name="SK하이닉스", market="KOSPI")
    mock_fin_hynix = FinancialData(stock=mock_stock_hynix, price=185000.0, per=9.2, retrieved_at=datetime(2026, 10, 31))
    mock_res_hynix = AnalysisResult(
        theme="AI 반도체",
        candidates=(mock_stock_hynix,),
        financial=mock_fin_hynix,
        news=NewsData((), datetime(2026, 10, 31)),
        commentary=None,
        price_history=PriceHistory("000660", "000660.KS", ()),
        result_id="res_hynix_01",
    )

    ev_hynix = build_evidence(mock_res_hynix)
    real_hynix_refs = [dict(ev_hynix["PRICE"], id="PRICE"), dict(ev_hynix["PER"], id="PER")]

    multi_turn_msgs = [
        {"role": "user", "text": "삼성전자 주가랑 PER 알려줘"},
        {"role": "assistant", "text": "삼성전자의 현재 주가는 72,000원이며 PER은 14.5배입니다.", "evidence": real_sec_refs},
        {"role": "user", "text": "SK하이닉스는 어때?"},
        {"role": "assistant", "text": "SK하이닉스의 현재 주가는 185,000원이며 PER은 9.2배입니다.", "evidence": real_hynix_refs},
    ]

    q_summary = "지금까지 대화 내용 요약해줘"
    print(f"질문: {q_summary}")
    resp_summary = answer_question(q_summary, mock_res_hynix, multi_turn_msgs, settings)
    text_summary = resp_summary.intro if hasattr(resp_summary, "intro") else resp_summary[0]
    print(f"답변 전문:\n{text_summary}")
    results["m01_i1_v1_summary"] = {
        "question": q_summary,
        "answer": text_summary,
        "has_samsung": "삼성전자" in text_summary,
        "has_hynix": "SK하이닉스" in text_summary or "하이닉스" in text_summary,
    }

    # 3. M02-I1: 선택적 저장 (명시 요청 vs 일반 요청)
    print("\n--- [시나리오 3: M02-I1 & I2 선택적 저장과 내보내기] ---")
    state_export = {"dashboard_result": mock_res_hynix}
    _handle_explicit_canvas_or_export_request(state_export, "삼성전자랑 하이닉스 중 어디가 더 나아?", None)
    saved_canvases_before = list(state_export.get("canvases", []))
    print(f"일반 질문 시 캔버스 생성 여부: {len(saved_canvases_before) > 0}")

    _handle_explicit_canvas_or_export_request(state_export, "이 분석 내용 엑셀로 저장해줘", None)
    saved_canvases_after = list(state_export.get("canvases", []))
    print(f"명시적 저장 요청 시 캔버스 생성 여부: {len(saved_canvases_after) > 0}")
    has_bundle = len(saved_canvases_after) > 0 and saved_canvases_after[0].get("export_bytes") is not None
    filename = saved_canvases_after[0].get("export_filename") if has_bundle else ""
    print(f"내보내기 번들 생성 완료: {has_bundle}, 파일명: {filename}")
    results["m02_export"] = {
        "non_export_created": len(saved_canvases_before) > 0,
        "explicit_export_created": has_bundle,
        "export_filename": filename,
    }

    # 4. M03-I1: 종료 인사 ("고마워, 오늘은 여기까지 할게")
    print("\n--- [시나리오 4: M03-I1 종료 인사] ---")
    q_close = "고마워, 오늘은 여기까지 할게"
    intent_close = route_message(q_close, None, "000660", multi_turn_msgs, settings)
    print(f"질문: {q_close} -> 분류 액션: {intent_close.action}")
    results["m03_i1_closing"] = {
        "query": q_close,
        "action": intent_close.action,
        "pass": intent_close.action == "closing",
    }

    # 5. M03-I2: 종료 후 새 주제 질문 지속 ("AI 반도체 관련주는?")
    print("\n--- [시나리오 5: M03-I2 종료 후 새 주제 전환] ---")
    q_new_theme = "AI 반도체 관련주는?"
    intent_new_theme = route_message(q_new_theme, None, "000660", multi_turn_msgs, settings)
    print(f"질문: {q_new_theme} -> 분류 액션: {intent_new_theme.action}, 테마: {intent_new_theme.theme}")
    results["m03_i2_new_theme"] = {
        "query": q_new_theme,
        "action": intent_new_theme.action,
        "theme": intent_new_theme.theme,
        "pass": intent_new_theme.action == "discover",
    }

    # 6. M03-V1: 명시적 새 대화 초기화 및 생략 질문 차단 ("새 대화 시작해줘" -> "이 종목 영업이익은?")
    print("\n--- [시나리오 6: M03-V1 명시적 초기화 후 생략 지시어 차단] ---")
    q_reset = "새 대화 시작해줘"
    intent_reset = route_message(q_reset, None, "000660", multi_turn_msgs, settings)
    print(f"질문: {q_reset} -> 분류 액션: {intent_reset.action}")

    # Reset state
    state_reset = {
        "selected_code": "000660",
        "candidate_result": CandidateDiscoveryResult("AI 반도체", (mock_stock_hynix,), datetime(2026, 10, 31)),
        "dashboard_result": mock_res_hynix,
    }
    reset_all_state(state_reset)
    print(f"초기화 후 selected_code: {state_reset.get('selected_code')}")

    q_deictic = "이 종목 영업이익은?"
    intent_deictic = route_message(q_deictic, state_reset.get("candidate_result"), state_reset.get("selected_code"), [], settings)
    print(f"질문: {q_deictic} -> 분류 액션: {intent_deictic.action}, 이유: {intent_deictic.reason}")
    results["m03_v1_reset_and_clarify"] = {
        "reset_action": intent_reset.action,
        "deictic_action": intent_deictic.action,
        "reason": intent_deictic.reason,
        "pass": intent_reset.action == "reset" and intent_deictic.action == "clarify",
    }

    # Save summary report
    out_path = Path("docs/검수/계획8_09_요약_저장_종료_실시간LLM검증_2026-10-31.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n검증 결과 보고서 저장 완료: {out_path}")
    print("=== [Stage 09 검증 완료] ===")


if __name__ == "__main__":
    run_stage09_eval()
