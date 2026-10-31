"""실제 API + AppTest로 직접 종목 질문→채팅 결과→명시적 캔버스→엑셀을 검사한다.

브라우저/서버를 시작하지 않는다. --live 필수. 인증값·외부 예외 본문은 기록하지 않는다.
"""
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/검수/계획5_실제흐름_검수.json")
    args = parser.parse_args()
    if not args.live:
        parser.error("실제 호출에는 --live가 필요합니다.")
    from streamlit.testing.v1 import AppTest
    from src.models import now_kst
    report = {"checked_at": now_kst().isoformat(), "external_responses_mocked": False,
              "browser_or_server_started": False, "steps": []}
    app = AppTest.from_file(str(ROOT / "src/ui/app.py"), default_timeout=240).run()
    def record(name, passed, **detail):
        report["steps"].append({"step": name, "passed": bool(passed), **detail})
    try:
        record("initial_hidden_canvas", not app.session_state.filtered_state.get("canvases") and not app.exception)
        app.text_input(key="composer_text").set_value("삼성전자 분석해줘")
        app.button(key="composer_submit").click().run()
        result = app.session_state.filtered_state.get("dashboard_result")
        record("direct_stock_analysis", result is not None and result.target_code == "005930" and not app.exception)
        if result is not None:
            record("real_collection", result.financial.price is not None and bool(result.news.articles),
                   section_status=result.section_status, history_bars=len(result.price_history.bars) if result.price_history else 0,
                   annual_periods=len(result.annual_summaries), news_count=len(result.news.articles),
                   commentary_present=result.commentary is not None, ai_error=result.ai_error)
            record("report_in_chat", any("종합 분석" in m["text"] for m in app.session_state["chat_messages"]))
            record("canvas_still_hidden", not app.session_state.filtered_state.get("canvases"))
            app.button(key="add_canvas").click().run()
            cards = app.session_state.filtered_state.get("canvases", [])
            record("explicit_canvas_open", len(cards) == 1 and not app.exception)
            if cards:
                card_id = cards[0]["canvas_id"]
                app.button(key=f"prepare_export_{card_id}").click().run()
                card = app.session_state["canvases"][0]
                record("excel_prepared", bool(card.get("export_bytes")) and not app.exception,
                       byte_count=len(card.get("export_bytes") or b""))
        else:
            report["user_messages"] = [m["text"] for m in app.session_state.filtered_state.get("chat_messages", []) if m.get("role") == "assistant"]
    except Exception as error:
        record("execution", False, error_type=type(error).__name__)
    output = args.output
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["steps"] and all(s["passed"] for s in report["steps"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
