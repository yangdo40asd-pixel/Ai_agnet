"""화면과 답변 심사가 공유하는 간결한 데이터 출처 표기."""


def data_source_label(item):
    label = str(item.get("source") or "자료 출처")
    period = item.get("period")
    if period and "미확인" not in str(period):
        label += " · " + str(period)
    if item.get("fs_div"):
        label += " · " + {"CFS": "연결", "OFS": "별도"}.get(item["fs_div"], item["fs_div"])
    return label
