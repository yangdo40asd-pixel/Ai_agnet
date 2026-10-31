"""OpenDART 재무제표 계정 추출·기간/단위 정규화·재무비율 계산·연간/분기 비교 구성 모듈."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from src.config import Settings
from src.data.dart import (
    FS_DIVS,
    REPRT_CODES,
    fetch_corp_codes,
    fetch_financial_indices,
    fetch_statement,
    resolve_corp_code,
)
from src.models import (
    AppError,
    AnnualFinancialSummary,
    FinancialAccountRow,
    FinancialFact,
    FinancialRatios,
    FinancialStatementData,
    MetricValue,
    QuarterlyFinancialSummary,
    StockCandidate,
    now_kst,
)
from src.formatting import format_eok, format_percent

# 표준 XBRL account_id 및 확인된 계정명 매핑
ACCOUNT_RULES: dict[str, dict[str, object]] = {
    "revenue": {
        "sj_divs": ("IS", "CIS"),
        "ids": {"ifrs-full_Revenue", "ifrs_Revenue"},
        "names": {"매출액", "매출", "수익(매출액)", "영업수익"},
    },
    "operating_income": {
        "sj_divs": ("IS", "CIS"),
        "ids": {
            "dart_OperatingIncomeLoss",
            "ifrs-full_ProfitLossFromOperatingActivities",
            "ifrs_ProfitLossFromOperatingActivities",
        },
        "names": {"영업이익", "영업이익(손실)", "영업손익"},
    },
    "net_income": {
        "sj_divs": ("IS", "CIS"),
        "ids": {"ifrs-full_ProfitLoss", "ifrs_ProfitLoss"},
        "names": {
            "당기순이익",
            "당기순이익(손실)",
            "당기순손익",
            "분기순이익",
            "분기순이익(손실)",
            "반기순이익",
            "반기순이익(손실)",
            "연결당기순이익",
            "연결당기순이익(손실)",
        },
    },
    "parent_net_income": {
        "sj_divs": ("IS", "CIS"),
        "ids": {
            "ifrs-full_ProfitLossAttributableToOwnersOfParent",
            "ifrs_ProfitLossAttributableToOwnersOfParent",
        },
        "names": {
            "지배기업의 소유주에게 귀속되는 당기순이익(손실)",
            "지배기업의 소유주에게 귀속되는 당기순이익",
            "지배기업소유주지분순이익",
            "지배기업소유주지분",
            "지배주주순이익",
        },
    },
    "total_assets": {
        "sj_divs": ("BS",),
        "ids": {"ifrs-full_Assets", "ifrs_Assets"},
        "names": {"자산총계", "자산 총계"},
    },
    "total_liabilities": {
        "sj_divs": ("BS",),
        "ids": {"ifrs-full_Liabilities", "ifrs_Liabilities"},
        "names": {"부채총계", "부채 총계"},
    },
    "total_equity": {
        "sj_divs": ("BS",),
        "ids": {"ifrs-full_Equity", "ifrs_Equity"},
        "names": {"자본총계", "자본 총계"},
    },
    "parent_equity": {
        "sj_divs": ("BS",),
        "ids": {
            "ifrs-full_EquityAttributableToOwnersOfParent",
            "ifrs_EquityAttributableToOwnersOfParent",
        },
        "names": {
            "지배기업의 소유주에게 귀속되는 자본",
            "지배기업소유주지분",
            "지배주주지분",
        },
    },
    "operating_cash_flow": {
        "sj_divs": ("CF",),
        "ids": {
            "ifrs-full_CashFlowsFromUsedInOperatingActivities",
            "ifrs_CashFlowsFromUsedInOperatingActivities",
        },
        "names": {
            "영업활동현금흐름",
            "영업활동 현금흐름",
            "영업활동으로 인한 현금흐름",
            "영업활동으로인한현금흐름",
        },
    },
    "investing_cash_flow": {
        "sj_divs": ("CF",),
        "ids": {
            "ifrs-full_CashFlowsFromUsedInInvestingActivities",
            "ifrs_CashFlowsFromUsedInInvestingActivities",
        },
        "names": {
            "투자활동현금흐름",
            "투자활동 현금흐름",
            "투자활동으로 인한 현금흐름",
            "투자활동으로인한현금흐름",
        },
    },
    "financing_cash_flow": {
        "sj_divs": ("CF",),
        "ids": {
            "ifrs-full_CashFlowsFromUsedInFinancingActivities",
            "ifrs_CashFlowsFromUsedInFinancingActivities",
        },
        "names": {
            "재무활동현금흐름",
            "재무활동 현금흐름",
            "재무활동으로 인한 현금흐름",
            "재무활동으로인한현금흐름",
        },
    },
}


def parse_dart_amount(raw_value: object) -> int | Decimal | None:
    """OpenDART 금액 문자열을 원 단위 정밀도(int 또는 Decimal)로 파싱한다. 누락을 0으로 바꾸지 않는다."""
    if raw_value is None or isinstance(raw_value, bool):
        return None
    if isinstance(raw_value, int):
        return raw_value
    if isinstance(raw_value, Decimal):
        return raw_value if raw_value.is_finite() else None
    if isinstance(raw_value, float):
        try:
            dec = Decimal(str(raw_value))
            return int(dec) if dec == dec.to_integral_value() else dec
        except Exception:
            return None
    if not isinstance(raw_value, str):
        return None

    cleaned = raw_value.strip().replace(",", "").replace(" ", "")
    if not cleaned or cleaned in {"-", "N/A", "nan", "NaN", "null", "None"}:
        return None
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", cleaned):
        return None
    try:
        dec = Decimal(cleaned)
    except InvalidOperation:
        return None
    if not dec.is_finite():
        return None
    if dec == dec.to_integral_value():
        return int(dec)
    return dec


def _clean_account_name(name: object) -> str:
    if not isinstance(name, str):
        return ""
    text = re.sub(r"^[IVX0-9]+\.\s*", "", name.strip())
    return " ".join(text.split())


def match_standard_key(sj_div: str, account_id: str, account_nm: str) -> str:
    """재무제표 구분(sj_div), 표준 계정 ID(우선), 확인된 계정명 별칭으로 표준 키를 판별한다."""
    sj = (sj_div or "").strip().upper()
    acc_id = (account_id or "").strip()
    acc_nm = _clean_account_name(account_nm)

    # 1순위: 표준 account_id 정확 일치
    if acc_id and acc_id != "-":
        for key, rule in ACCOUNT_RULES.items():
            if sj in rule["sj_divs"] and acc_id in rule["ids"]:
                return key

    # 2순위: 확인된 계정명 별칭 일치
    for key, rule in ACCOUNT_RULES.items():
        if sj in rule["sj_divs"] and acc_nm in rule["names"]:
            return key
    return ""


def _determine_period_type(sj_div: str, reprt_code: str) -> tuple[str, str]:
    sj = (sj_div or "").strip().upper()
    if sj == "BS":
        return "point_in_time", "기말 잔액"
    if reprt_code == "11011":
        return "annual", "연간"
    if reprt_code == "11013":
        return ("quarter_3m", "1분기(3개월)") if sj in {"IS", "CIS"} else ("cumulative", "1분기 누적")
    if reprt_code == "11012":
        return ("quarter_3m", "2분기(3개월)") if sj in {"IS", "CIS"} else ("cumulative", "반기 누적")
    if reprt_code == "11014":
        return ("quarter_3m", "3분기(3개월)") if sj in {"IS", "CIS"} else ("cumulative", "3분기 누적")
    return "unknown", ""


def normalize_statement(
    stock_code: str,
    raw_response: dict[str, object],
    *,
    is_separate_fallback: bool = False,
) -> FinancialStatementData:
    """OpenDART 전체 재무제표 응답을 정규화한다.

    - IS/CIS 중복 계정을 합산하지 않는다(IS 우선, 없을 때만 CIS 채택).
    - BS 기말 잔액은 분기 차감 대상이 아니다.
    - 원화(KRW)가 아닌 통화 행은 원화 금액으로 취급하지 않는다.
    """
    retrieved_at = now_kst()
    corp_code = str(raw_response.get("corp_code") or "").strip() or None
    bsns_year = str(raw_response.get("bsns_year") or "").strip()
    reprt_code = str(raw_response.get("reprt_code") or "11011").strip()
    fs_div = str(raw_response.get("fs_div") or "CFS").strip()
    status = str(raw_response.get("status") or "empty")
    message = str(raw_response.get("message") or "")
    raw_list = raw_response.get("list")

    if status != "ok" or not isinstance(raw_list, list) or not raw_list:
        return FinancialStatementData(
            code=stock_code,
            corp_code=corp_code,
            bsns_year=bsns_year,
            reprt_code=reprt_code,
            fs_div=fs_div,
            rows=(),
            rcept_no="",
            source="OpenDART",
            retrieved_at=retrieved_at,
            status="empty" if status == "empty" else status,
            message=message or "조회된 재무제표 항목이 없습니다.",
            is_separate_fallback=is_separate_fallback,
        )

    # 표준 키별로 가장 우선순위가 높은 행 1개만 선택해 IS/CIS 중복 합산을 방지한다.
    # 우선순위: (1) 표준 account_id 일치 여부, (2) IS가 CIS보다 우선
    selected_by_key: dict[str, tuple[int, FinancialAccountRow]] = {}
    all_rows: list[FinancialAccountRow] = []
    rcept_no_found = ""

    for item in raw_list:
        if not isinstance(item, dict):
            continue
        currency = str(item.get("currency") or "KRW").strip().upper()
        if currency != "KRW":
            continue
        sj_div = str(item.get("sj_div") or "").strip().upper()
        if sj_div not in {"IS", "CIS", "BS", "CF"}:
            continue
        account_id = str(item.get("account_id") or "").strip()
        account_nm = str(item.get("account_nm") or "").strip()
        rcept_no = str(item.get("rcept_no") or "").strip()
        if rcept_no and not rcept_no_found:
            rcept_no_found = rcept_no

        amount = parse_dart_amount(item.get("thstrm_amount"))
        cumulative_amount = parse_dart_amount(item.get("thstrm_add_amount"))
        # 연간(11011) 또는 1분기(11013)에서 thstrm_amount가 비어 있고 누적만 있는 경우 보완
        if amount is None and reprt_code in {"11011", "11013"} and sj_div in {"IS", "CIS", "CF"}:
            amount = cumulative_amount

        period_type, period_label = _determine_period_type(sj_div, reprt_code)
        std_key = match_standard_key(sj_div, account_id, account_nm)

        row_obj = FinancialAccountRow(
            sj_div=sj_div,
            account_id=account_id,
            account_nm=account_nm,
            standard_key=std_key,
            amount=amount,
            cumulative_amount=cumulative_amount,
            currency="KRW",
            bsns_year=bsns_year,
            reprt_code=reprt_code,
            fs_div=fs_div,
            period_type=period_type,
            period_label=f"{bsns_year}년 {period_label}".strip(),
            rcept_no=rcept_no,
            source="OpenDART",
        )

        if not std_key:
            all_rows.append(row_obj)
            continue

        rule = ACCOUNT_RULES[std_key]
        id_matched = 1 if (account_id in rule["ids"]) else 0
        sj_priority = 2 if sj_div == "IS" else 1
        has_value = 1 if (amount is not None or cumulative_amount is not None) else 0
        rank = (has_value, id_matched, sj_priority)

        prev = selected_by_key.get(std_key)
        if prev is None or rank > prev[0]:
            selected_by_key[std_key] = (rank, row_obj)

    standard_rows = [pair[1] for pair in selected_by_key.values()]
    merged_rows = tuple(standard_rows + all_rows)

    if not merged_rows:
        return FinancialStatementData(
            code=stock_code,
            corp_code=corp_code,
            bsns_year=bsns_year,
            reprt_code=reprt_code,
            fs_div=fs_div,
            rows=(),
            rcept_no=rcept_no_found,
            source="OpenDART",
            retrieved_at=retrieved_at,
            status="empty",
            message="원화(KRW) 기준 재무제표 계정을 확인하지 못했습니다.",
            is_separate_fallback=is_separate_fallback,
        )

    return FinancialStatementData(
        code=stock_code,
        corp_code=corp_code,
        bsns_year=bsns_year,
        reprt_code=reprt_code,
        fs_div=fs_div,
        rows=merged_rows,
        rcept_no=rcept_no_found,
        source="OpenDART",
        retrieved_at=retrieved_at,
        status="ok",
        message="연결재무제표가 없어 별도재무제표(OFS) 기준으로 표시합니다." if is_separate_fallback else "",
        is_separate_fallback=is_separate_fallback,
    )


def get_standard_row(
    statement: FinancialStatementData,
    standard_key: str,
) -> FinancialAccountRow | None:
    for row in statement.rows:
        if row.standard_key == standard_key:
            return row
    return None


def get_standard_amount(
    statement: FinancialStatementData,
    standard_key: str,
    *,
    use_cumulative: bool = False,
) -> int | Decimal | None:
    row = get_standard_row(statement, standard_key)
    if row is None:
        return None
    if use_cumulative:
        return row.cumulative_amount if row.cumulative_amount is not None else row.amount
    return row.amount


def _extract_provided_roe(
    index_response: dict[str, object] | None,
    bsns_year: str,
    reprt_code: str,
) -> MetricValue | None:
    """OpenDART fnlttSinglIndx 응답에서 공식 제공 ROE를 추출한다.

    공식 가이드 기준: fs_div 요청 인자가 없으며 이미 % 단위로 제공된다(100을 중복 곱하지 않음).
    """
    if not isinstance(index_response, dict) or index_response.get("status") != "ok":
        return None
    items = index_response.get("list")
    if not isinstance(items, list):
        return None

    reprt_name = REPRT_CODES.get(reprt_code, reprt_code)
    for item in items:
        if not isinstance(item, dict):
            continue
        idx_nm = str(item.get("idx_nm") or "").strip()
        idx_code = str(item.get("idx_code") or "").strip()
        if "ROE" in idx_nm.upper() or "자기자본이익률" in idx_nm:
            parsed = parse_dart_amount(item.get("idx_val"))
            if parsed is None:
                continue
            val = float(parsed)
            return MetricValue(
                name="ROE",
                value=val,
                unit="%",
                currency="",
                source="OpenDART 주요 재무지표 (fnlttSinglIndx)",
                raw_field=f"idx_val ({idx_nm or idx_code})",
                period=f"{bsns_year}년 {reprt_name}",
                status="ok",
                basis="provided",
                formula="OpenDART 공식 수익성지표 제공값",
                reason="fnlttSinglIndx API 응답값(연결/별도 구분 인자 미제공 API)",
            )
    return None


def _income_margin(revenue, income, *, name, numerator_label, raw_field, period, loss_reason):
    """동일 매출 분모를 쓰는 두 이익률만 공통화한다. ROE·부채비율은 별도 규칙이다."""
    value = None
    if revenue is None or income is None:
        status = "missing"
        reason = f"매출액 또는 {numerator_label} 항목이 없어 계산할 수 없습니다."
    elif Decimal(str(revenue)) <= 0:
        status = "invalid"
        reason = f"매출액이 0 이하여서 {name}을 계산하지 않습니다."
    else:
        value = round(float((Decimal(str(income)) / Decimal(str(revenue))) * Decimal("100")), 2)
        status = "ok"
        reason = loss_reason if value < 0 else ""
    return MetricValue(
        name=name, value=value, unit="%", currency="", source="OpenDART 재무제표 기반 계산",
        raw_field=raw_field, period=period, status=status, basis="calculated",
        formula=f"{numerator_label} / 매출액 × 100", reason=reason,
    )


def calculate_ratios(
    statement: FinancialStatementData,
    index_response: dict[str, object] | None = None,
    *,
    prior_statement: FinancialStatementData | None = None,
) -> FinancialRatios:
    """동일 기간·동일 연결구분(CFS/OFS)의 재무제표로 이익률·부채비율·ROE를 계산한다."""
    if statement is None or statement.status != "ok":
        return FinancialRatios(
            status=statement.status if statement else "empty",
            message=statement.message if statement else "재무제표 자료가 없습니다.",
        )

    year = statement.bsns_year
    reprt = statement.reprt_code
    fs_div = statement.fs_div
    reprt_label = REPRT_CODES.get(reprt, reprt)
    period_label = f"{year}년 {reprt_label} ({fs_div})"
    notes: list[str] = []

    revenue = get_standard_amount(statement, "revenue")
    op_income = get_standard_amount(statement, "operating_income")
    net_income = get_standard_amount(statement, "net_income")
    parent_net = get_standard_amount(statement, "parent_net_income")
    liabilities = get_standard_amount(statement, "total_liabilities")
    equity = get_standard_amount(statement, "total_equity")
    parent_equity = get_standard_amount(statement, "parent_equity")

    op_margin_metric = _income_margin(
        revenue, op_income, name="영업이익률", numerator_label="영업이익",
        raw_field="operating_income / revenue", period=period_label,
        loss_reason="영업손실(적자)로 인해 영업이익률이 음수입니다.",
    )
    net_margin_metric = _income_margin(
        revenue, net_income, name="순이익률", numerator_label="당기순이익",
        raw_field="net_income / revenue", period=period_label,
        loss_reason="당기순손실(적자)로 인해 순이익률이 음수입니다.",
    )

    # 3. 부채비율 = 부채총계 / 자본총계 * 100 (자본 0/음수는 별도 해석 상태)
    if liabilities is None or equity is None:
        debt_metric = MetricValue(
            name="부채비율",
            value=None,
            unit="%",
            currency="",
            source="OpenDART 재무제표 기반 계산",
            raw_field="total_liabilities / total_equity",
            period=period_label,
            status="missing",
            basis="calculated",
            formula="부채총계 / 자본총계 × 100",
            reason="부채총계 또는 자본총계 항목이 없어 계산할 수 없습니다.",
        )
    elif Decimal(str(equity)) == 0:
        debt_metric = MetricValue(
            name="부채비율",
            value=None,
            unit="%",
            currency="",
            source="OpenDART 재무제표 기반 계산",
            raw_field="total_liabilities / total_equity",
            period=period_label,
            status="invalid",
            basis="calculated",
            formula="부채총계 / 자본총계 × 100",
            reason="자본총계가 0이어서 부채비율을 계산할 수 없습니다.",
        )
    elif Decimal(str(equity)) < 0:
        notes.append("자본총계가 음수(자본잠식)여서 부채비율을 양수 정상 비율로 표시하지 않습니다.")
        debt_metric = MetricValue(
            name="부채비율",
            value=None,
            unit="%",
            currency="",
            source="OpenDART 재무제표 기반 계산",
            raw_field="total_liabilities / total_equity",
            period=period_label,
            status="impairment",
            basis="calculated",
            formula="부채총계 / 자본총계 × 100",
            reason="자본총계가 음수(자본잠식 상태)여서 정상 부채비율로 해석할 수 없습니다.",
        )
    else:
        debt_val = round(float((Decimal(str(liabilities)) / Decimal(str(equity))) * Decimal("100")), 2)
        debt_metric = MetricValue(
            name="부채비율",
            value=debt_val,
            unit="%",
            currency="",
            source="OpenDART 재무제표 기반 계산",
            raw_field="total_liabilities / total_equity",
            period=period_label,
            status="ok",
            basis="calculated",
            formula="부채총계 / 자본총계 × 100",
            reason="",
        )

    # 4. ROE: (1순위) OpenDART 공식 수익성지표 제공값, (2순위) 연간 보고서(11011)일 때만 검증된 산식으로 계산
    roe_metric = _extract_provided_roe(index_response, year, reprt)
    if roe_metric is None:
        if reprt != "11011":
            roe_metric = MetricValue(
                name="ROE",
                value=None,
                unit="%",
                currency="",
                source="OpenDART",
                raw_field="ROE",
                period=period_label,
                status="missing",
                basis="provided",
                formula="",
                reason="분기·반기 실적은 임의 연율화하지 않으며 공식 ROE 지표가 제공되지 않았습니다.",
            )
        else:
            # 지배주주 순이익·지배주주 자본이 모두 있으면 해당 쌍을 쓰고, 아니면 전체 당기순이익·자본총계 쌍을 사용
            if parent_net is not None and parent_equity is not None:
                num_val = Decimal(str(parent_net))
                end_eq = Decimal(str(parent_equity))
                prior_eq = (
                    Decimal(str(get_standard_amount(prior_statement, "parent_equity")))
                    if (
                        prior_statement
                        and prior_statement.status == "ok"
                        and prior_statement.fs_div == fs_div
                        and get_standard_amount(prior_statement, "parent_equity") is not None
                    )
                    else None
                )
                pair_label = "지배주주귀속순이익"
                eq_label = "지배주주자본"
            elif net_income is not None and equity is not None:
                num_val = Decimal(str(net_income))
                end_eq = Decimal(str(equity))
                prior_eq = (
                    Decimal(str(get_standard_amount(prior_statement, "total_equity")))
                    if (
                        prior_statement
                        and prior_statement.status == "ok"
                        and prior_statement.fs_div == fs_div
                        and get_standard_amount(prior_statement, "total_equity") is not None
                    )
                    else None
                )
                pair_label = "당기순이익"
                eq_label = "자본총계"
            else:
                num_val = None
                end_eq = None
                prior_eq = None
                pair_label = "당기순이익"
                eq_label = "자본총계"

            if num_val is None or end_eq is None:
                roe_metric = MetricValue(
                    name="ROE",
                    value=None,
                    unit="%",
                    currency="",
                    source="OpenDART 재무제표 기반 계산",
                    raw_field="net_income / equity",
                    period=period_label,
                    status="missing",
                    basis="calculated",
                    formula=f"{pair_label} / {eq_label} × 100",
                    reason="당기순이익 또는 자본총계 항목이 없어 ROE를 계산할 수 없습니다.",
                )
            elif end_eq <= 0 or (prior_eq is not None and prior_eq <= 0):
                roe_metric = MetricValue(
                    name="ROE",
                    value=None,
                    unit="%",
                    currency="",
                    source="OpenDART 재무제표 기반 계산",
                    raw_field="net_income / equity",
                    period=period_label,
                    status="impairment" if end_eq < 0 else "invalid",
                    basis="calculated",
                    formula=f"{pair_label} / {eq_label} × 100",
                    reason="자본총계가 0 이하여서 ROE를 계산하지 않습니다.",
                )
            else:
                if prior_eq is not None and prior_eq > 0:
                    denom = (end_eq + prior_eq) / Decimal("2")
                    formula_str = f"{pair_label} / 평균 {eq_label}[(기초+기말)/2] × 100"
                else:
                    denom = end_eq
                    formula_str = f"{pair_label} / 기말 {eq_label} × 100"
                roe_val = round(float((num_val / denom) * Decimal("100")), 2)
                roe_metric = MetricValue(
                    name="ROE",
                    value=roe_val,
                    unit="%",
                    currency="",
                    source="OpenDART 재무제표 기반 계산",
                    raw_field="net_income / equity",
                    period=period_label,
                    status="ok",
                    basis="calculated",
                    formula=formula_str,
                    reason="공식 주요지표 미제공 연도여서 재무제표 원자료로 계산했습니다.",
                )

    return FinancialRatios(
        roe=roe_metric,
        operating_margin=op_margin_metric,
        net_margin=net_margin_metric,
        debt_ratio=debt_metric,
        bsns_year=year,
        reprt_code=reprt,
        fs_div=fs_div,
        interpretation_notes=tuple(notes),
        status="ok",
        message="",
    )


def candidate_annual_years(
    reference_year: int | None = None,
    count: int = 3,
) -> tuple[str, ...]:
    """현재 시점 기준으로 사업보고서 공시가 가능한 직전 연간 사업연도 목록(오름차순)을 반환한다.

    2026년 중에 2026년 연간 사업보고서가 이미 공시됐다고 가정하지 않는다.
    """
    current_year = reference_year or now_kst().year
    last_completed_year = current_year - 1
    start_year = last_completed_year - max(1, count) + 1
    return tuple(str(y) for y in range(start_year, last_completed_year + 1))


def build_annual_comparison(
    statements: list[FinancialStatementData] | tuple[FinancialStatementData, ...],
    index_responses_by_year: dict[str, dict[str, object]] | None = None,
) -> tuple[AnnualFinancialSummary, ...]:
    """공시된 연간 재무제표(11011)들을 동일 연결구분(CFS 또는 OFS)·동일 통화 기준으로 비교 구성한다.

    없는 연도를 보간하지 않으며, CFS와 OFS를 한 비교 계열에 섞지 않는다.
    """
    valid = [
        st_data
        for st_data in statements
        if st_data is not None and st_data.status == "ok" and st_data.reprt_code == "11011"
    ]
    if not valid:
        return ()

    # CFS가 하나라도 있으면 CFS만 비교 계열로 사용하고, 없을 때만 OFS 계열을 사용한다.
    target_fs_div = "CFS" if any(s.fs_div == "CFS" for s in valid) else valid[0].fs_div
    filtered = [s for s in valid if s.fs_div == target_fs_div]

    # 연도별 중복이 있으면 최신 접수번호(rcept_no) 우선
    by_year: dict[str, FinancialStatementData] = {}
    for item in filtered:
        existing = by_year.get(item.bsns_year)
        if existing is None or (item.rcept_no and item.rcept_no >= existing.rcept_no):
            by_year[item.bsns_year] = item

    sorted_years = sorted(by_year.keys())
    summaries: list[AnnualFinancialSummary] = []
    idx_map = index_responses_by_year or {}

    for i, year in enumerate(sorted_years):
        curr_stmt = by_year[year]
        prior_stmt = by_year[sorted_years[i - 1]] if (i > 0 and int(year) - int(sorted_years[i - 1]) == 1) else None
        ratios = calculate_ratios(
            curr_stmt,
            idx_map.get(year),
            prior_statement=prior_stmt,
        )
        summaries.append(
            AnnualFinancialSummary(
                bsns_year=year,
                reprt_code="11011",
                fs_div=target_fs_div,
                revenue=get_standard_amount(curr_stmt, "revenue"),
                operating_income=get_standard_amount(curr_stmt, "operating_income"),
                net_income=get_standard_amount(curr_stmt, "net_income"),
                parent_net_income=get_standard_amount(curr_stmt, "parent_net_income"),
                total_assets=get_standard_amount(curr_stmt, "total_assets"),
                total_liabilities=get_standard_amount(curr_stmt, "total_liabilities"),
                total_equity=get_standard_amount(curr_stmt, "total_equity"),
                parent_equity=get_standard_amount(curr_stmt, "parent_equity"),
                operating_cash_flow=get_standard_amount(curr_stmt, "operating_cash_flow"),
                investing_cash_flow=get_standard_amount(curr_stmt, "investing_cash_flow"),
                financing_cash_flow=get_standard_amount(curr_stmt, "financing_cash_flow"),
                operating_margin=ratios.operating_margin.value if (ratios.operating_margin and ratios.operating_margin.status == "ok") else None,
                net_margin=ratios.net_margin.value if (ratios.net_margin and ratios.net_margin.status == "ok") else None,
                debt_ratio=ratios.debt_ratio.value if (ratios.debt_ratio and ratios.debt_ratio.status == "ok") else None,
                roe=ratios.roe.value if (ratios.roe and ratios.roe.status == "ok") else None,
                rcept_no=curr_stmt.rcept_no,
                currency="KRW",
            )
        )

    return tuple(summaries)


def _subtract_amounts(
    annual_val: int | Decimal | None,
    cum_q3_val: int | Decimal | None,
) -> int | Decimal | None:
    if annual_val is None or cum_q3_val is None:
        return None
    diff = Decimal(str(annual_val)) - Decimal(str(cum_q3_val))
    return int(diff) if diff == diff.to_integral_value() else diff


def build_quarter_comparison(
    statements: list[FinancialStatementData] | tuple[FinancialStatementData, ...],
) -> tuple[QuarterlyFinancialSummary, ...]:
    """동일 연결구분(CFS/OFS)에서 당분기(3개월) 의미가 검증된 분기 실적만 구성한다.

    - 1분기(11013), 반기(11012), 3분기(11014)의 IS/CIS `thstrm_amount`(3개월 값)는 이미 당분기이므로 다시 차감하지 않는다.
    - 4분기 단독 실적은 동일 사업연도·동일 연결구분의 연간(11011) 금액과 3분기(11014) 누적(`thstrm_add_amount`)이 모두 있을 때만 차감 계산한다.
    """
    valid = [s for s in statements if s is not None and s.status == "ok"]
    if not valid:
        return ()

    target_fs_div = "CFS" if any(s.fs_div == "CFS" for s in valid) else valid[0].fs_div
    same_fs = [s for s in valid if s.fs_div == target_fs_div]

    grouped = {}
    for statement in same_fs:
        grouped.setdefault((statement.bsns_year, statement.reprt_code), []).append(statement)
    # 같은 보고기간의 여러 버전을 임의로 최신/유효 공시로 고르지 않는다.
    by_year_reprt = {key: entries[0] for key, entries in grouped.items() if len(entries) == 1}

    years = sorted({s.bsns_year for s in same_fs})
    results: list[QuarterlyFinancialSummary] = []

    quarter_specs = (
        ("11013", "1Q", "1분기 3개월 공시값"),
        ("11012", "2Q", "2분기 3개월 공시값(반기 누적 아님)"),
        ("11014", "3Q", "3분기 3개월 공시값(3분기 누적 아님)"),
    )

    for year in years:
        for reprt_code, q_tag, note in quarter_specs:
            stmt = by_year_reprt.get((year, reprt_code))
            if stmt is None:
                continue
            rev_row = get_standard_row(stmt, "revenue")
            op_row = get_standard_row(stmt, "operating_income")
            net_row = get_standard_row(stmt, "net_income")
            # 이미 3개월 당분기 값인 원화 행만 사용한다.
            rev_row, op_row, net_row = (r if r is not None and r.currency == "KRW"
                                      and r.period_type == "quarter_3m" else None
                                      for r in (rev_row, op_row, net_row))
            if all(r is None or r.amount is None for r in (rev_row, op_row, net_row)):
                continue
            results.append(
                QuarterlyFinancialSummary(
                    bsns_year=year,
                    reprt_code=reprt_code,
                    fs_div=target_fs_div,
                    period_label=f"{year} {q_tag}",
                    period_type="quarter_3m",
                    revenue=rev_row.amount if rev_row else None,
                    operating_income=op_row.amount if op_row else None,
                    net_income=net_row.amount if net_row else None,
                    is_standalone_quarter=True,
                    derivation_note=note,
                    rcept_no=stmt.rcept_no,
                    currency="KRW",
                )
            )

        # 4분기(4Q) 당분기 계산: 동일 연도·연결구분의 연간(11011)과 3분기(11014) 누적값이 모두 있을 때만 수행
        annual_stmt = by_year_reprt.get((year, "11011"))
        q3_stmt = by_year_reprt.get((year, "11014"))
        if annual_stmt is not None and q3_stmt is not None:
            q3_rev_row = get_standard_row(q3_stmt, "revenue")
            q3_op_row = get_standard_row(q3_stmt, "operating_income")
            q3_net_row = get_standard_row(q3_stmt, "net_income")

            q4_rev = _subtract_amounts(
                get_standard_amount(annual_stmt, "revenue"),
                q3_rev_row.cumulative_amount if q3_rev_row else None,
            )
            q4_op = _subtract_amounts(
                get_standard_amount(annual_stmt, "operating_income"),
                q3_op_row.cumulative_amount if q3_op_row else None,
            )
            q4_net = _subtract_amounts(
                get_standard_amount(annual_stmt, "net_income"),
                q3_net_row.cumulative_amount if q3_net_row else None,
            )
            if any(v is not None for v in (q4_rev, q4_op, q4_net)):
                results.append(
                    QuarterlyFinancialSummary(
                        bsns_year=year,
                        reprt_code="11011-11014",
                        fs_div=target_fs_div,
                        period_label=f"{year} 4Q",
                        period_type="quarter_3m",
                        revenue=q4_rev,
                        operating_income=q4_op,
                        net_income=q4_net,
                        is_standalone_quarter=True,
                        derivation_note="동일 연도·연결구분 사업보고서(연간)에서 3분기 누적 금액을 차감",
                        rcept_no=annual_stmt.rcept_no,
                        currency="KRW",
                    )
                )

    return tuple(results)


def build_financial_facts(
    stock: StockCandidate,
    annual_summaries: tuple[AnnualFinancialSummary, ...],
    ratios: FinancialRatios | None = None,
) -> tuple[FinancialFact, ...]:
    """검증된 재무 요약과 비율을 AI 입력 및 사실 대조용 FinancialFact 목록으로 변환한다."""
    if not stock.code:
        return ()
    facts: list[FinancialFact] = []

    for summary in annual_summaries[-3:]:
        period_str = f"{summary.bsns_year}년 연간"
        items = (
            ("revenue", "매출액", summary.revenue),
            ("operating_income", "영업이익", summary.operating_income),
            ("net_income", "당기순이익", summary.net_income),
            ("total_assets", "자산총계", summary.total_assets),
            ("total_liabilities", "부채총계", summary.total_liabilities),
            ("total_equity", "자본총계", summary.total_equity),
        )
        for key_tag, item_label, val in items:
            if val is None:
                continue
            dec_val = Decimal(str(val))
            polarity = "positive" if dec_val > 0 else ("negative" if dec_val < 0 else "zero")
            facts.append(
                FinancialFact(
                    fact_id=f"FIN_{summary.bsns_year}_{key_tag.upper()}",
                    stock_code=stock.code,
                    stock_name=stock.name,
                    item=item_label,
                    value=val,
                    display_value=format_eok(val),
                    unit="억원",
                    period=period_str,
                    fs_div=summary.fs_div,
                    source="OpenDART",
                    polarity=polarity,
                )
            )

    if ratios and ratios.status == "ok":
        ratio_period = f"{ratios.bsns_year}년 {REPRT_CODES.get(ratios.reprt_code, ratios.reprt_code)}"
        for tag, label, metric in (
            ("ROE", "ROE", ratios.roe),
            ("OP_MARGIN", "영업이익률", ratios.operating_margin),
            ("NET_MARGIN", "순이익률", ratios.net_margin),
            ("DEBT_RATIO", "부채비율", ratios.debt_ratio),
        ):
            if metric is None or metric.status != "ok" or metric.value is None:
                continue
            pol = "positive" if metric.value > 0 else ("negative" if metric.value < 0 else "zero")
            facts.append(
                FinancialFact(
                    fact_id=f"RATIO_{ratios.bsns_year}_{tag}",
                    stock_code=stock.code,
                    stock_name=stock.name,
                    item=label,
                    value=metric.value,
                    display_value=format_percent(metric.value),
                    unit="%",
                    period=metric.period or ratio_period,
                    fs_div=ratios.fs_div,
                    source=metric.source,
                    polarity=pol,
                )
            )

    return tuple(facts)


def collect_company_financials(
    stock: StockCandidate,
    settings: Settings,
    *,
    preferred_fs_div: str = "CFS",
    years: tuple[str, ...] | None = None,
    include_indices: bool = True,
) -> dict[str, object]:
    """선택 종목의 DART 기업번호 매핑 → 최근 3개년 연간 재무제표·주요지표 수집 → 비교·비율·fact 생성을 수행한다.

    DART 미설정·미공시·오류가 발생해도 예외를 밖으로 던져 주가·뉴스를 중단시키지 않고
    영역 상태(ok/empty/failed)로 반환한다.
    """
    if not stock.verified or not stock.code:
        return {
            "status": "empty",
            "message": "상장 종목코드가 확인되지 않아 재무제표를 조회하지 않습니다.",
            "statements": (),
            "annual_summaries": (),
            "quarterly_summaries": (),
            "ratios": None,
            "facts": (),
        }

    if not settings.dart_api_key:
        return {
            "status": "empty",
            "message": "DART_API_KEY가 설정되지 않아 기업 재무제표를 조회하지 않습니다.",
            "statements": (),
            "annual_summaries": (),
            "quarterly_summaries": (),
            "ratios": None,
            "facts": (),
        }

    try:
        corp_map = fetch_corp_codes(settings)
        corp_code = resolve_corp_code(stock.code, corp_map)
    except AppError as error:
        status_kind = "empty" if error.code == "dart_corp_unmapped" else "failed"
        return {
            "status": status_kind,
            "message": error.message,
            "statements": (),
            "annual_summaries": (),
            "quarterly_summaries": (),
            "ratios": None,
            "facts": (),
        }

    target_years = years or candidate_annual_years(count=3)
    target_fs = preferred_fs_div if preferred_fs_div in FS_DIVS else "CFS"
    is_fallback = False
    collected_statements: list[FinancialStatementData] = []
    index_by_year: dict[str, dict[str, object]] = {}
    last_error_msg = ""
    had_failure = False

    # 최신 연도부터 확인해 CFS가 전부 empty(013)이면 OFS로 일괄 전환(계열 혼합 금지)
    raw_by_year: dict[str, dict[str, object]] = {}
    for year in target_years:
        resp = fetch_statement(corp_code, year, "11011", target_fs, settings=settings)
        raw_by_year[year] = resp
        if resp.get("status") in {"auth_error", "rate_limit", "timeout", "failed"}:
            had_failure = True
            last_error_msg = str(resp.get("message") or "")
            if resp.get("status") in {"auth_error", "rate_limit"}:
                break

    if (
        not had_failure
        and target_fs == "CFS"
        and all(r.get("status") != "ok" for r in raw_by_year.values())
    ):
        # 연결재무제표가 없는 개별 기업인 경우 별도재무제표(OFS)로 전체 계열 재조회
        ofs_raw: dict[str, dict[str, object]] = {}
        for year in target_years:
            resp = fetch_statement(corp_code, year, "11011", "OFS", settings=settings)
            ofs_raw[year] = resp
            if resp.get("status") in {"auth_error", "rate_limit"}:
                had_failure = True
                last_error_msg = str(resp.get("message") or "")
                break
        if any(r.get("status") == "ok" for r in ofs_raw.values()):
            raw_by_year = ofs_raw
            target_fs = "OFS"
            is_fallback = True

    for year in target_years:
        resp = raw_by_year.get(year)
        if not resp:
            continue
        norm = normalize_statement(stock.code, resp, is_separate_fallback=is_fallback)
        if norm.status == "ok":
            collected_statements.append(norm)
            # 2023년 이후 연도에 대해 주요 재무지표(수익성지표 M210000) 조회 시도
            if include_indices and int(year) >= 2023:
                idx_resp = fetch_financial_indices(
                    corp_code, year, "11011", "M210000", settings=settings
                )
                if idx_resp.get("status") == "ok":
                    index_by_year[year] = idx_resp

    if not collected_statements:
        return {
            "status": "failed" if had_failure else "empty",
            "message": last_error_msg or "공시된 연간 재무제표 자료가 없습니다.",
            "statements": (),
            "annual_summaries": (),
            "quarterly_summaries": (),
            "ratios": None,
            "facts": (),
        }

    # 호출자가 years를 역순으로 주어도 최신 비율의 기준 연도가 뒤집히지 않는다.
    collected_statements.sort(key=lambda statement: int(statement.bsns_year))
    annual_summaries = build_annual_comparison(collected_statements, index_by_year)
    quarterly_summaries = build_quarter_comparison(collected_statements)
    latest_stmt = collected_statements[-1]
    prior_stmt = collected_statements[-2] if len(collected_statements) >= 2 else None
    latest_ratios = calculate_ratios(
        latest_stmt,
        index_by_year.get(latest_stmt.bsns_year),
        prior_statement=prior_stmt,
    )
    facts = build_financial_facts(stock, annual_summaries, latest_ratios)

    return {
        "status": "ok",
        "message": latest_stmt.message,
        "statements": tuple(collected_statements),
        "annual_summaries": annual_summaries,
        "quarterly_summaries": quarterly_summaries,
        "ratios": latest_ratios,
        "facts": facts,
    }
