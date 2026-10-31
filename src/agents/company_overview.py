"""검증된 연간 비교 자료를 보존하는 종합 질문의 제한 답변."""
from decimal import Decimal, InvalidOperation


def comparison_fallback(evidence):
    facts = {key: item for key, item in evidence.items()
             if item.get("kind") == "annual_comparison" and item.get("status") == "ok"
             and item.get("item") in {"revenue", "operating_income", "operating_margin"}}
    bases = {(tuple(v.get("years", ())), v.get("fs_div"), v.get("stock_code")) for v in facts.values()}
    if len(bases) != 1:
        return None
    by_item = {v["item"]: v for v in facts.values()}
    income = by_item.get("operating_income")
    if income is None:
        return None
    try:
        previous, current = Decimal(str(income["previous"])), Decimal(str(income["current"]))
        if not previous.is_finite() or not current.is_finite():
            return None
    except (KeyError, InvalidOperation, ValueError):
        return None
    if previous >= 0 and current < 0:
        lead = "최근 확인된 연간 실적에서는 영업손익이 적자로 전환됐습니다. 본업에서 매출보다 비용이 더 많이 발생한 상태입니다."
    elif previous < 0 and current >= 0:
        lead = "최근 확인된 연간 실적에서는 영업손익이 흑자로 전환됐습니다. 본업에서 손실을 내던 상태에서 벗어난 변화입니다."
    elif current < 0:
        lead = ("최근 확인된 연간 실적에서는 영업적자가 이어졌지만 손실 규모는 줄었습니다." if current > previous else
                "최근 확인된 연간 실적에서는 영업적자가 이어졌고 손실 규모가 커졌습니다." if current < previous else
                "최근 확인된 연간 실적에서는 영업적자가 이어졌으며 손실 규모는 전년과 같습니다.")
    else:
        rev = by_item.get("revenue")
        rev_change = None
        if rev:
            try:
                prev_rev, curr_rev = Decimal(str(rev["previous"])), Decimal(str(rev["current"]))
                if curr_rev > prev_rev:
                    rev_change = "증가"
                elif curr_rev < prev_rev:
                    rev_change = "감소"
            except (KeyError, InvalidOperation, ValueError):
                pass
        if rev_change == "증가" and current > previous:
            lead = "최근 확인된 연간 실적에서는 매출과 영업이익이 모두 증가하며 견조한 성장 흐름을 나타냈습니다."
        elif rev_change == "증가" and current < previous:
            lead = "최근 확인된 연간 실적에서는 매출은 늘었으나 영업이익이 줄어 수익성이 다소 둔화된 흐름입니다."
        elif rev_change == "감소" and current > previous:
            lead = "최근 확인된 연간 실적에서는 매출이 다소 줄었으나 영업이익은 증가하며 수익성을 방어하는 흐름을 보였습니다."
        elif rev_change == "감소" and current < previous:
            lead = "최근 확인된 연간 실적에서는 매출과 영업이익이 모두 감소하며 다소 둔화된 실적 흐름을 보였습니다."
        else:
            lead = ("최근 확인된 연간 실적에서는 영업이익이 늘었습니다." if current > previous else
                    "최근 확인된 연간 실적에서는 영업이익이 줄었습니다." if current < previous else
                    "최근 확인된 연간 실적에서는 영업이익이 전년과 같습니다.")
    details = [v["text"] for v in facts.values() if v.get("text")]
    if not details:
        return None
    return lead + "\n\n" + "\n\n".join(details), [dict(v, id=k, answer_origin="verified_fallback") for k, v in facts.items()]
