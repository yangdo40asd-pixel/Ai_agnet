"""명시적으로 실행하는 실제 API → Streamlit 화면 검사. 서버·브라우저는 열지 않는다.

실행: python scripts/verify_live.py --live
외부 API를 실제 호출하므로 제공자의 사용량/요금이 발생할 수 있다.
기본 unittest 검사에는 포함되지 않으며 비밀값과 외부 예외 본문을 저장하지 않는다.
종료 코드: 0=완전 결과, 2=연동 성공/해석 주의 또는 자료 누락, 1=검사 실패.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.models import now_kst


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def run_case(app, theme):
    start = time.monotonic()
    app.chat_input[0].set_value(theme).run(timeout=180)
    check(not app.exception, "화면 실행 예외")
    check("latest_result" in app.session_state, "분석 결과 생성 실패")
    result = app.session_state["latest_result"]
    check(result.theme == theme, "새 입력과 결과 불일치")
    check(len(result.candidates) == 3, "후보 개수 불일치")
    check(all(x.verified and not x.reason for x in result.candidates), "후보 상장 확인 실패")
    check(result.financial.price is not None, "실제 주가 누락")
    check(result.news.status == "ok" and result.news.articles, "뉴스 수집 미완료")
    check(result.commentary is not None and not app.error, "AI 리포트 생성/검증 실패")
    check(len(app.metric) == 2, "주가·PER 화면 누락")
    price = f"{result.financial.price:,.2f}".rstrip("0").rstrip(".") + "원"
    per = "정보 없음" if result.financial.per is None else f"{result.financial.per:,.2f}배"
    check([x.value for x in app.metric] == [price, per], "화면 지표와 조회 자료 불일치")
    if result.financial.per_eps is not None:
        check(result.financial.per == result.financial.price / result.financial.per_eps, "PER 계산 불일치")
        captions = " ".join(x.value for x in app.caption)
        check("계산했습니다" in captions and result.financial.per_period_end in captions, "PER 계산 근거 표시 누락")
    table = app.dataframe[0].value
    check(list(table["종목코드"]) == [x.code for x in result.candidates], "화면 종목코드 불일치")
    links = {x.proto.url for x in app.get("link_button")}
    check(all(x.url in links for x in result.news.articles), "뉴스 출처 링크 누락")
    markdown = " ".join(x.value for x in app.markdown)
    check(all(f"뉴스 {x.id}." in markdown for x in result.news.articles), "뉴스 번호 누락")
    check(len(app.success) == int(result.complete), "부분 결과의 완료 표시 오류")
    app.run()
    check(not app.exception and app.session_state["latest_result"] is result, "화면 재실행 결과 보존 실패")
    return {
        "theme": theme, "status": "complete" if result.complete else "passed_with_notice",
        "seconds": round(time.monotonic() - start, 2),
        "candidates": [{"name": x.name, "code": x.code, "market": x.market} for x in result.candidates],
        "price": result.financial.price, "per": result.financial.per,
        "per_eps": result.financial.per_eps, "per_period_end": result.financial.per_period_end,
        "price_at": result.financial.price_at.isoformat() if result.financial.price_at else None,
        "retrieved_at": result.financial.retrieved_at.isoformat(),
        "warnings": list(result.financial.warnings),
        "news": [{"id": x.id, "title": x.title, "url": x.url, "published_at": x.published_at} for x in result.news.articles],
        "commentary": {
            "trend": [x.text for x in result.commentary.theme_trend],
            "stock": result.commentary.stock_comment,
            "opportunity": result.commentary.opportunity.text,
            "risk": result.commentary.risk.text,
            "summary": result.commentary.summary.text,
        },
        "ui_values_links_and_rerun": "passed",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="실제 외부 API 호출 활성화")
    parser.add_argument("--themes", nargs="+", default=["반도체 테마주 분석해줘", "2차전지", "로봇"])
    parser.add_argument("--interval", type=float, default=45, help="테마 검사 사이 대기 초. 연속 검사의 API 한도 소진 방지")
    parser.add_argument("--output", type=Path, default=ROOT / "검수자료" / "실제_API_검수.json")
    args = parser.parse_args()
    if not args.live:
        parser.error("실제 호출은 --live 옵션이 있어야 실행합니다.")
    from streamlit.testing.v1 import AppTest
    from src.config import load_settings

    settings = load_settings()
    app = AppTest.from_file(str(ROOT / "src/ui/app.py"), default_timeout=180).run()
    report = {"checked_at": now_kst().isoformat(), "model": settings.groq_model,
              "external_responses_mocked": False, "browser_or_server_started": False, "cases": []}
    for index, theme in enumerate(args.themes):
        if index and args.interval > 0:
            time.sleep(min(args.interval, 60))
        try:
            item = run_case(app, theme)
        except Exception as error:
            # 인증 응답·요청 객체·예외 본문은 API 키를 포함할 수 있으므로 기록하지 않는다.
            item = {"theme": theme, "status": "failed", "error_type": type(error).__name__}
            if isinstance(error, AssertionError):
                item["check"] = str(error)
            # 앱은 외부 예외를 AppError의 고정 안내문으로 치환한다.
            item["app_errors"] = [x.value for x in app.error]
        report["cases"].append(item)
        print(json.dumps({k: v for k, v in item.items() if k in {"theme", "status", "seconds", "check", "error_type", "warnings", "app_errors"}}, ensure_ascii=False), flush=True)
    app.button[0].click().run()
    report["clear_result"] = "passed" if not app.exception and not app.metric and "latest_result" not in app.session_state else "failed"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["clear_result"] == "failed" or any(x["status"] == "failed" for x in report["cases"]):
        return 1
    return 2 if any(x["status"] == "passed_with_notice" for x in report["cases"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
