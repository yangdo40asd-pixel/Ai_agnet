"""명시적으로 실행하는 실제 API → Streamlit 선택형 대시보드·재무·AI·엑셀 통합 검사. 서버·브라우저는 열지 않는다.

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

from src.export.excel import reconcile_workbook_values
from src.models import now_kst
from src.ui.formatting import (
    format_multiple,
    format_per_share_krw,
    format_percent,
    format_price,
)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def _expected_metric_strings(result) -> list[str]:
    fin = result.financial
    roe_metric = (
        result.financial_ratios.roe
        if (result.financial_ratios and result.financial_ratios.roe is not None)
        else fin.roe_metric
    )
    roe_val = roe_metric.value if (roe_metric and roe_metric.status == "ok") else None
    return [
        format_price(fin.price),
        format_multiple(fin.per),
        format_multiple(fin.pbr),
        format_percent(roe_val),
        format_per_share_krw(fin.eps),
        format_per_share_krw(fin.bps),
    ]


def _verify_selected_result(app, result, expected_theme: str, expected_code: str) -> dict:
    check(result.theme == expected_theme, "테마 입력과 결과 테마 불일치")
    check(result.target_code == expected_code, "선택 종목코드와 결과 종목코드 불일치")
    check(result.financial.stock.code == expected_code, "금융 자료 종목코드 불일치")
    check(result.financial.price is not None, "실제 주가 누락")
    check(result.news.status == "ok" and result.news.articles, "뉴스 수집 미완료")
    check(result.commentary is not None and not app.error, "AI 리포트 생성/검증 실패")

    # 1. 상단 4카드(주가·PER·PBR·ROE) + 보조 2카드(EPS·BPS) 총 6개 지표 카드 대조
    check(len(app.metric) == 6, f"지표 카드 개수 불일치: {len(app.metric)} != 6")
    expected_metrics = _expected_metric_strings(result)
    actual_metrics = [x.value for x in app.metric]
    check(
        actual_metrics == expected_metrics,
        f"화면 지표와 조회 자료 불일치: {actual_metrics} != {expected_metrics}",
    )

    if result.financial.per_eps is not None:
        check(
            result.financial.per == result.financial.price / result.financial.per_eps,
            "PER 계산 불일치",
        )

    # 2. 일별 주가·거래량 이력(PriceHistory) 검증
    hist = result.price_history
    check(hist is not None and hist.status == "ok" and len(hist.bars) > 0, "일별 시세 이력 누락")
    check(hist.code == expected_code, "일별 시세 종목코드 불일치")
    check(hist.currency == "KRW" and not hist.adjusted, "일별 시세 통화/조정 기준 불일치")
    dates = [b.trade_date for b in hist.bars]
    check(dates == sorted(dates) and len(dates) == len(set(dates)), "일별 시세 거래일 정렬/중복 오류")

    # 3. OpenDART 재무제표·비율·재무 AI 근거(fact_ids) 대조
    fact_ids_set = {f.fact_id for f in result.financial_facts}
    if result.section_status.get("dart") == "ok":
        check(len(result.annual_summaries) >= 1, "DART 연간 재무 요약 누락")
        check(result.financial_ratios is not None, "DART 재무 비율 누락")
        check(len(result.financial_facts) >= 1, "DART FinancialFact 누락")
        for f in result.financial_facts:
            check(f.stock_code == expected_code, "FinancialFact 종목코드 불일치")
        if result.commentary.financial_commentary:
            for fstmt in result.commentary.financial_commentary:
                check(
                    bool(fstmt.fact_ids) and all(fid in fact_ids_set for fid in fstmt.fact_ids),
                    "재무 AI 설명의 fact_id 근거 불일치",
                )

    # 4. 후보 표·뉴스 링크·번호 확인
    table = app.dataframe[0].value
    check(
        list(table["종목코드"]) == [x.code for x in result.candidates],
        "화면 후보 표 종목코드 불일치",
    )
    links = {x.proto.url for x in app.get("link_button")}
    check(all(x.url in links for x in result.news.articles), "뉴스 출처 링크 누락")
    markdown = " ".join(x.value for x in app.markdown)
    check(all(f"뉴스 {x.id}." in markdown for x in result.news.articles), "뉴스 번호 누락")
    check(len(app.success) == int(result.complete), "부분 결과의 완료 표시 오류")

    # 5. 엑셀(XLSX) 바이트·파일명·내부 시트·네이티브 차트 셀 참조 대조
    check("export_bytes" in app.session_state and "export_filename" in app.session_state, "엑셀 다운로드 자료 미생성")
    export_bytes = app.session_state["export_bytes"]
    export_filename = app.session_state["export_filename"]
    check(expected_code in export_filename, "엑셀 파일명 종목코드 불일치")
    excel_check = reconcile_workbook_values(result, export_bytes)
    check(excel_check["all_sheets_present"], "엑셀 8개 시트 구성 누락")
    check(excel_check["code_matches"], "엑셀 내부 6자리 종목코드 선행0/일치 실패")
    check(excel_check["price_matches"] and excel_check["per_matches"], "엑셀 내부 주가/PER 수치 불일치")
    check(excel_check["formula_cells"] == [], "엑셀 수식 주입(Formula Injection) 방어 실패")
    check(excel_check["chart_count"] >= 2, "엑셀 네이티브 차트 누락")

    # 6. 단순 rerun 시 API 재호출 없이 동일 객체 및 엑셀 보존 확인
    app.run(timeout=180)
    check(
        not app.exception
        and app.session_state["dashboard_result"] is result
        and app.session_state["export_bytes"] is export_bytes,
        "화면 단순 재실행(rerun) 시 결과/엑셀 보존 실패",
    )

    roe_metric = (
        result.financial_ratios.roe
        if (result.financial_ratios and result.financial_ratios.roe is not None)
        else result.financial.roe_metric
    )
    return {
        "selected_stock": {
            "name": result.financial.stock.name,
            "code": result.financial.stock.code,
            "market": result.financial.stock.market,
        },
        "price": result.financial.price,
        "per": result.financial.per,
        "pbr": result.financial.pbr,
        "eps": result.financial.eps,
        "bps": result.financial.bps,
        "roe": roe_metric.value if roe_metric else None,
        "roe_basis": roe_metric.basis if roe_metric else None,
        "per_eps": result.financial.per_eps,
        "per_period_end": result.financial.per_period_end,
        "price_at": result.financial.price_at.isoformat() if result.financial.price_at else None,
        "retrieved_at": result.financial.retrieved_at.isoformat(),
        "warnings": list(result.financial.warnings),
        "history_bars": len(hist.bars) if hist else 0,
        "history_range": [hist.bars[0].trade_date, hist.bars[-1].trade_date] if (hist and hist.bars) else [],
        "dart_status": result.section_status.get("dart"),
        "annual_years": [a.bsns_year for a in result.annual_summaries],
        "financial_ratios": {
            "bsns_year": result.financial_ratios.bsns_year,
            "fs_div": result.financial_ratios.fs_div,
            "roe": result.financial_ratios.roe.value if (result.financial_ratios and result.financial_ratios.roe) else None,
            "operating_margin": (
                result.financial_ratios.operating_margin.value
                if (result.financial_ratios and result.financial_ratios.operating_margin)
                else None
            ),
            "net_margin": (
                result.financial_ratios.net_margin.value
                if (result.financial_ratios and result.financial_ratios.net_margin)
                else None
            ),
            "debt_ratio": (
                result.financial_ratios.debt_ratio.value
                if (result.financial_ratios and result.financial_ratios.debt_ratio)
                else None
            ),
        }
        if result.financial_ratios
        else None,
        "section_status": dict(result.section_status),
        "timings_ms": dict(result.timings_ms),
        "news": [
            {"id": x.id, "title": x.title, "url": x.url, "published_at": x.published_at}
            for x in result.news.articles
        ],
        "commentary": {
            "trend": [x.text for x in result.commentary.theme_trend],
            "stock": result.commentary.stock_comment,
            "financial_commentary": [
                {"text": x.text, "fact_ids": list(x.fact_ids)}
                for x in result.commentary.financial_commentary
            ],
            "opportunity": result.commentary.opportunity.text if result.commentary.opportunity else None,
            "risk": result.commentary.risk.text if result.commentary.risk else None,
            "summary": result.commentary.summary.text if result.commentary.summary else None,
        },
        "excel": {
            "filename": export_filename,
            "size_bytes": len(export_bytes),
            "sheet_names": list(excel_check["sheet_names"]),
            "chart_count": excel_check["chart_count"],
            "formula_cells_count": len(excel_check["formula_cells"]),
        },
    }


def run_case(app, theme: str, *, verify_second_candidate: bool = False):
    start = time.monotonic()
    t_disc = time.perf_counter()
    app.chat_input[0].set_value(theme).run(timeout=180)
    discovery_ms = round((time.perf_counter() - t_disc) * 1000.0, 2)

    check(not app.exception, "후보 탐색 화면 실행 예외")
    check("candidate_result" in app.session_state, "후보 탐색 결과 미생성")
    check(
        "selected_code" not in app.session_state or app.session_state["selected_code"] is None,
        "초기 상태가 선택 대기 상태가 아님",
    )
    check("dashboard_result" not in app.session_state, "종목 선택 전 상세 결과가 미리 생성됨")

    discovery = app.session_state["candidate_result"]
    check(len(discovery.candidates) == 3, "후보 개수 불일치")
    check(all(x.verified and not x.reason for x in discovery.candidates), "후보 상장 확인 실패")

    first_code = discovery.candidates[0].code
    app.selectbox(key="candidate_selector").select(first_code).run(timeout=180)
    check(not app.exception, "선택 종목 1 상세 분석 실행 예외")
    check("dashboard_result" in app.session_state, "선택 종목 1 상세 결과 생성 실패")
    result1 = app.session_state["dashboard_result"]

    primary_detail = _verify_selected_result(app, result1, discovery.theme, first_code)

    switch_detail = None
    if verify_second_candidate and len(discovery.candidates) >= 2:
        second_code = discovery.candidates[1].code
        app.selectbox(key="candidate_selector").select(second_code).run(timeout=180)
        check(not app.exception, "선택 종목 2 전환 실행 예외")
        check("dashboard_result" in app.session_state, "선택 종목 2 상세 결과 생성 실패")
        result2 = app.session_state["dashboard_result"]
        check(result2.target_code == second_code, "선택 종목 2 전환 후 종목코드 불일치")
        check(result2 is not result1, "종목 전환 후 이전 결과 객체가 그대로 남음")
        switch_detail = _verify_selected_result(app, result2, discovery.theme, second_code)

    return {
        "theme": theme,
        "status": "complete" if result1.complete else "passed_with_notice",
        "seconds": round(time.monotonic() - start, 2),
        "discovery_ms": discovery_ms,
        "candidates": [
            {"name": x.name, "code": x.code, "market": x.market}
            for x in discovery.candidates
        ],
        **primary_detail,
        "candidate_switch_verified": switch_detail is not None,
        "switched_stock": switch_detail["selected_stock"] if switch_detail else None,
        "switched_timings_ms": switch_detail["timings_ms"] if switch_detail else None,
        "switched_excel": switch_detail["excel"] if switch_detail else None,
        "ui_values_links_and_rerun": "passed",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="실제 외부 API 호출 활성화")
    parser.add_argument(
        "--themes",
        nargs="+",
        default=["반도체 테마주 분석해줘", "2차전지", "로봇"],
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=35,
        help="테마 검사 사이 대기 초. 연속 검사의 API 한도 소진 방지",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "검수자료" / "실제_API_검수.json",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("실제 호출은 --live 옵션이 있어야 실행합니다.")
    from streamlit.testing.v1 import AppTest
    from src.config import load_settings

    settings = load_settings()
    app = AppTest.from_file(str(ROOT / "src/ui/app.py"), default_timeout=180).run()
    report = {
        "checked_at": now_kst().isoformat(),
        "model": settings.groq_model,
        "dart_configured": bool(settings.dart_api_key),
        "external_responses_mocked": False,
        "browser_or_server_started": False,
        "cases": [],
    }
    for index, theme in enumerate(args.themes):
        if index and args.interval > 0:
            time.sleep(min(args.interval, 60))
        try:
            item = run_case(app, theme, verify_second_candidate=(index == 0))
        except Exception as error:
            # 인증 응답·요청 객체·예외 본문은 API 키를 포함할 수 있으므로 기록하지 않는다.
            item = {"theme": theme, "status": "failed", "error_type": type(error).__name__}
            if isinstance(error, AssertionError):
                item["check"] = str(error)
            item["app_errors"] = [x.value for x in app.error]
        report["cases"].append(item)
        print(
            json.dumps(
                {
                    k: v
                    for k, v in item.items()
                    if k
                    in {
                        "theme",
                        "status",
                        "seconds",
                        "discovery_ms",
                        "selected_stock",
                        "candidate_switch_verified",
                        "switched_stock",
                        "check",
                        "error_type",
                        "warnings",
                        "app_errors",
                    }
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    app.button(key="clear_results").click().run()
    report["clear_result"] = (
        "passed"
        if (
            not app.exception
            and not app.metric
            and "dashboard_result" not in app.session_state
            and "candidate_result" not in app.session_state
            and "export_bytes" not in app.session_state
        )
        else "failed"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if report["clear_result"] == "failed" or any(x["status"] == "failed" for x in report["cases"]):
        return 1
    return 2 if any(x["status"] == "passed_with_notice" for x in report["cases"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
