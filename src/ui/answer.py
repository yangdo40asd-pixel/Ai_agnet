"""검증된 답변 블록·출처·서로 다른 시각을 화면에 표시한다."""
from dataclasses import asdict
from datetime import datetime
import re
from urllib.parse import urlparse

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


def render_evidence(items, linked_urls: set[str]) -> None:
    seen = set()
    for item in items:
        url = safe_news_url(item.get("url"))
        identity = url or item["id"]
        if identity in seen:
            continue
        seen.add(identity)
        st.caption(escaped(evidence_metadata(item)))
        if url and url not in linked_urls:
            domain = urlparse(url).hostname
            st.link_button(f"{domain} · {item['text']}", url)
            linked_urls.add(url)
        else:
            st.caption(escaped(f"[{item['id']}] {item['text']}" + (" · 위에 표시한 원문과 동일한 출처" if url else "")))


def render_answer(message: dict) -> None:
    refs = {e["id"]: e for e in message.get("evidence", ())}
    blocks = message.get("blocks") or ()
    linked_urls = set()
    if blocks:
        st.markdown(message.get("intro", ""), unsafe_allow_html=False)
        block_ids = {key for block in blocks for key in block["evidence_ids"]}
        render_evidence([refs[i] for i in message.get("lead_evidence_ids", ()) if i in refs and i not in block_ids], linked_urls)
        for block in blocks:
            with st.container():
                st.markdown("**" + escaped(block["title"]) + "**")
                st.markdown(block["text"], unsafe_allow_html=False)
                render_evidence([refs[i] for i in block["evidence_ids"] if i in refs], linked_urls)
    else:
        st.markdown(message.get("text", ""), unsafe_allow_html=False)
        render_evidence(refs.values(), linked_urls)
