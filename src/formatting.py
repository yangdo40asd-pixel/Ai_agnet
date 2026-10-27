"""화면 표시용 숫자·단위·부호 포맷 함수.

원자료(FinancialData, FinancialStatementData 등)의 정밀도는 변경하지 않고
표시 시점에만 원·주당 원·배·%·억원·주 단위로 변환한다.
"""

import math
from datetime import datetime
from decimal import Decimal
from numbers import Real

from src.models import KST


def _valid_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def format_price(value: object, missing: str = "정보 없음") -> str:
    """주가 표시 포맷 (원)."""
    number = _valid_number(value)
    if number is None:
        return missing
    return f"{number:,.0f}원" if float(number).is_integer() else f"{number:,.2f}원"


def format_per_share_krw(value: object, missing: str = "정보 없음") -> str:
    """EPS·BPS 등 주당 원화 금액 표시 포맷 (주당 원)."""
    number = _valid_number(value)
    if number is None:
        return missing
    if float(number).is_integer():
        return f"{number:,.0f}원"
    return f"{number:,.2f}원"


def format_multiple(value: object, missing: str = "정보 없음") -> str:
    """PER·PBR 등 배수 지표 표시 포맷 (배)."""
    number = _valid_number(value)
    if number is None:
        return missing
    return f"{number:,.2f}배"


def format_percent(value: object, missing: str = "정보 없음", *, signed: bool = False) -> str:
    """ROE·이익률·부채비율·등락률 표시 포맷 (%)."""
    number = _valid_number(value)
    if number is None:
        return missing
    if signed:
        if number > 0:
            return f"+{number:,.2f}%"
        if number < 0:
            return f"{number:,.2f}%"
        return "0.00%"
    return f"{number:,.2f}%"


def format_signed_krw(value: object, missing: str = "정보 없음") -> str:
    """등락폭 표시 포맷 (+/- 기호와 원 단위 명시)."""
    number = _valid_number(value)
    if number is None:
        return missing
    fmt = f"{abs(number):,.0f}원" if float(number).is_integer() else f"{abs(number):,.2f}원"
    if number > 0:
        return f"+{fmt}"
    if number < 0:
        return f"-{fmt}"
    return "0원"


def format_change_summary(
    change: object,
    change_pct: object,
    missing: str = "등락 정보 없음",
) -> str:
    """색상에만 의존하지 않고 +/− 기호와 값·비율을 함께 표시한다."""
    diff = _valid_number(change)
    pct = _valid_number(change_pct)
    if diff is None:
        return missing
    diff_text = format_signed_krw(diff)
    if pct is None:
        return diff_text
    pct_text = format_percent(pct, signed=True)
    return f"{diff_text} ({pct_text})"


def format_eok(amount_won: object, missing: str = "정보 없음") -> str:
    """원 단위 재무 금액을 표시 시점에 한 번만 억원 단위로 변환한다."""
    if isinstance(amount_won, bool) or not isinstance(amount_won, (int, float, Decimal)):
        return missing
    try:
        dec = Decimal(str(amount_won))
    except Exception:
        return missing
    if not dec.is_finite():
        return missing
    eok = float(dec / Decimal("100000000"))
    return f"{eok:,.1f}억원"


def format_volume(value: object, missing: str = "정보 없음") -> str:
    """거래량 표시 포맷 (주)."""
    number = _valid_number(value)
    if number is None or number < 0:
        return missing
    return f"{int(round(number)):,}주"


def format_timestamp(value: datetime | None, fallback: str = "확인되지 않음") -> str:
    """시각 표시 포맷 (KST)."""
    if not isinstance(value, datetime):
        return fallback
    return value.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")
