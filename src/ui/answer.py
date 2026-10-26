"""검증된 답변 블록·출처·서로 다른 시각을 화면에 표시한다."""
from dataclasses import asdict
from datetime import datetime
import re

import streamlit as st

from src.data.news import safe_news_url
from src.models import ChatResponse


def escaped(value) -> str:
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>])", r"\\\1", str(value))


def time_label(value) -> str:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            pass
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds").replace("T", " ")
    return str(value or "미확인")


def response_fields(response) -> dict:
    """세션에는 데이터만 저장한다. 이전 세 값 반환도 표시할 수 있다."""
    if not isinstance(response, ChatResponse):
        return {}
    return {"intro": response.intro, "blocks": [asdict(b) for b in response.blocks],
            "lead_evidence_ids": response.lead_evidence_ids}


def evidence_metadata(item: dict) -> str:
    fields = [("제공자", item.get("source"))]
    if item.get("scope") == "headline_only":
        fields.extend((("확인 범위", "뉴스 제목 기반"), ("기사 발행", time_label(item.get("published_at")))))
    elif item.get("id") in {"PRICE", "PER", "PBR", "EPS", "BPS", "ROE"}:
        fields.append(("자료 기준", item.get("as_of") or "자료 기준 시각 미확인"))
    if item.get("period"):
        fields.append(("보고·산정 기간", item["period"]))
    if item.get("fs_div"):
        fields.append(("재무 기준", {"CFS": "연결", "OFS": "별도"}.get(item["fs_div"], item["fs_div"])))
    if item.get("formula"):
        fields.append(("산식", item["formula"]))
    fields.append(("조회 시각", time_label(item.get("retrieved_at"))))
    return " · ".join(f"{name}: {value}" for name, value in fields if value)


def source_groups(message: dict):
    """답변 안의 표시 번호를 원본 근거 ID에 연결한다. 원본 자료는 보존한다."""
    refs = {e["id"]: e for e in message.get("evidence", ())}
    blocks = message.get("blocks") or ()
    ids = (list(message.get("lead_evidence_ids", ())) +
           [i for block in blocks for i in block["evidence_ids"]]) if blocks else list(refs)
    groups, by_identity, numbers = [], {}, {}
    for key in dict.fromkeys(ids):
        if key not in refs:
            continue
        item = refs[key]
        url = safe_news_url(item.get("url"))
        identity = ("url", url) if url else ("data", item.get("source"), item.get("period"), item.get("fs_div"))
        if identity not in by_identity:
            by_identity[identity] = len(groups) + 1
            groups.append({"number": len(groups) + 1, "url": url, "items": []})
        number = by_identity[identity]
        numbers[key] = number
        groups[number - 1]["items"].append(item)
    return groups, numbers


def _reference_marks(ids, numbers):
    return " ".join(f"[{n}]" for n in dict.fromkeys(numbers[k] for k in ids if k in numbers))


def render_sources(groups):
    if not groups:
        return
    st.caption("출처")
    for group in groups:
        item = group["items"][0]
        label = f"[{group['number']}] " + str(item.get("source") or "자료 출처")
        if group["url"]:
            st.link_button(label + " · " + item["text"], group["url"])
        else:
            from src.source_presentation import data_source_label
            label = f"[{group['number']}] " + data_source_label(item)
            st.caption(escaped(label))
    with st.expander("출처 상세 · 기준과 조회 시각", expanded=False):
        for group in groups:
            for item in group["items"]:
                st.caption(escaped(f"[{group['number']}] {item.get('text', '')}"))
                st.caption(escaped(evidence_metadata(item)))


def render_answer(message: dict) -> None:
    groups, numbers = source_groups(message)
    blocks = message.get("blocks") or ()
    if blocks:
        marks = _reference_marks(message.get("lead_evidence_ids", ()), numbers)
        st.markdown(message.get("intro", "") + (" " + marks if marks else ""), unsafe_allow_html=False)
        for block in blocks:
            st.markdown("**" + escaped(block["title"]) + "**")
            marks = _reference_marks(block["evidence_ids"], numbers)
            st.markdown(block["text"] + (" " + marks if marks else ""), unsafe_allow_html=False)
    else:
        st.markdown(message.get("text", ""), unsafe_allow_html=False)
    render_sources(groups)
