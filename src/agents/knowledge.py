"""코드가 관리하는 금융 개념. 시장 자료나 종목별 판단은 포함하지 않는다."""

TERMS = {
    "PER": ("주가가 주당순이익의 몇 배인지 나타내는 지표입니다.", "주가 ÷ 주당순이익", "이익 대비 주가 수준", "적자이거나 이익이 일시적으로 변한 경우 해석에 주의해야 합니다."),
    "PBR": ("주가가 주당순자산의 몇 배인지 나타내는 지표입니다.", "주가 ÷ 주당순자산", "순자산 대비 주가 수준", "자산의 질과 수익성을 함께 확인해야 합니다."),
    "ROE": ("자기자본으로 어느 정도의 이익을 냈는지 나타내는 비율입니다.", "해당 기간 순이익 ÷ 평균 자기자본 × 100", "자기자본 대비 수익성", "기간과 연결·별도 기준, 자본 변동을 함께 확인해야 합니다."),
    "EPS": ("주식 한 주에 해당하는 순이익입니다.", "보통주 귀속 순이익 ÷ 가중평균 보통주 수", "주당 이익", "기본·희석 기준과 계산 기간이 다르면 직접 비교하기 어렵습니다."),
    "BPS": ("주식 한 주에 해당하는 순자산입니다.", "보통주 귀속 순자산 ÷ 해당 주식 수", "주당 순자산", "회계상 순자산이 실제 처분 가치를 보장하지는 않습니다."),
}

TRADING_CONCEPTS = {
    "매수": "주식을 사는 행위입니다. 현재가보다 낮은 가격에 사는 행위로 정의하지 않습니다.",
    "매도": "주식을 파는 행위입니다. 현재 시장 가격에만 팔아야 한다는 뜻이 아닙니다.",
    "주문 방식": "매수·매도는 거래 방향이고, 지정가·시장가는 주문 방식입니다. 거래 방향과 가격 조건은 별개입니다.",
}


def concept_answer(keys):
    if len(keys) == 1:
        key = keys[0]
        meaning, formula, purpose, limit = TERMS[key]
        return f"**{key}**는 {meaning}\n\n계산식은 **{formula}**입니다. {limit}"
    rows = ["| 지표 | 확인하는 내용 | 계산 기준 |", "|---|---|---|"]
    rows += [f"| {k} | {TERMS[k][2]} | {TERMS[k][1]} |" for k in keys]
    return "각 지표는 보는 기준이 다릅니다.\n\n" + "\n".join(rows) + "\n\n이익 대비 가격은 PER, 순자산 대비 가격은 PBR, 자기자본 수익성은 ROE로 구분합니다. 서로 다른 기간·회계 기준의 값을 바로 비교하거나 한 지표만으로 기업 가치를 단정하지 않아야 합니다."


def verified_metric_explanation(key, item):
    """LLM 재작성도 검증 실패한 단일 지표 질문에만 확인값·정의로 응답한다."""
    meaning, formula, _, limit = TERMS[key]
    value = item.get("value_text", "정보 없음")
    paragraphs = [f"{item['text']}입니다."]
    if item.get("value") is None:
        paragraphs.append(item.get("reason") or "값이 없는 원인은 이번 자료에서 확인할 수 없습니다.")
    elif key == "PER":
        paragraphs.append(f"주가가 계산에 사용된 주당순이익의 {value}라는 의미입니다.")
    else:
        paragraphs.append(f"{key}는 {meaning} 계산식은 {formula}입니다.")
    paragraphs.append("AI의 추가 해석은 검증하지 못해 확인된 값과 기본 의미를 먼저 제공합니다.")
    return "\n\n".join(paragraphs)
