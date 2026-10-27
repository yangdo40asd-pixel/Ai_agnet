"""화면과 독립적인 자료 갱신 판단 및 결과 메시지 조립."""
from datetime import datetime
from src.models import AnalysisResult, AnswerBlock, ChatResponse
from src.agents.chat import build_evidence


def needs_data(result: AnalysisResult, scope: str, text: str, period: str = "", *,
               now: datetime, dart_enabled: bool = False) -> bool:
    from src.agents.request import is_concept_question
    if is_concept_question(text) and not any(w in text for w in ("이 종목", "현재", result.financial.stock.name)):
        return False
    if scope == "news":
        return result.news.status == "not_collected" or (now-result.news.retrieved_at).total_seconds() > 900
    if scope == "history":
        return (bool(period and period != result.query_options.price_period)
                or result.price_history is None
                or (now-result.price_history.retrieved_at).total_seconds() > 900)
    if scope == "finance":
        return (now-result.financial.retrieved_at).total_seconds() > 300 or result.financial.collection_status == "not_collected"
    if scope == "financials":
        # 인증 설정이 없는 자료를 질문할 때마다 반복 호출하지 않는다.
        return dart_enabled and result.section_status.get("dart") == "not_collected"
    return False


def analysis_message(result: AnalysisResult, scope: str = "all") -> tuple[str, list[dict]]:
    response = analysis_response(result, scope)
    return response.text, response.evidence


def analysis_response(result: AnalysisResult, scope: str = "all") -> ChatResponse:
    """수집 결과와 근거를 채팅용 내용으로 조립한다. 상태를 변경하지 않는다."""
    evidence_map = build_evidence(result)
    evidence = [{"id": key, **item} for key, item in evidence_map.items() if key in {"PRICE", "PER", "PBR", "ROE"}]
    commentary = result.commentary
    summary_parts = [f"**{result.financial.stock.name} 조회 결과**"]
    blocks = []
    seen = {}
    if commentary:
        summary_parts.append(commentary.stock_comment)
        for label, statements in (("종합 분석", (commentary.summary,)), ("테마 동향", commentary.theme_trend), ("기회 요인", (commentary.opportunity,)),
                                  ("위험 요인", (commentary.risk,)),
                                  ("재무 분석", commentary.financial_commentary)):
            for statement in statements:
                if statement:
                    ids = tuple(key for key in [*(f"NEWS_{n}" for n in statement.news_ids), *(f"FACT_{n}" for n in statement.fact_ids)] if key in evidence_map)
                    if statement.text in seen:
                        index = seen[statement.text]
                        old = blocks[index]
                        blocks[index] = AnswerBlock(old.title, old.text, tuple(dict.fromkeys((*old.evidence_ids, *ids))))
                    else:
                        seen[statement.text] = len(blocks)
                        blocks.append(AnswerBlock(label, statement.text, ids))
                    for key in ids:
                        if key in evidence_map and key not in {e["id"] for e in evidence}:
                            evidence.append({"id": key, **evidence_map[key]})
    elif scope == "all":
        summary_parts.append("자료 수집 결과를 표시합니다. AI 종합 설명은 생성되지 않았습니다.")
    if result.news.status != "ok":
        summary_parts.append(result.news.message or "뉴스 자료를 확인하지 못했습니다.")
    if not result.complete:
        summary_parts.append("일부 자료가 없거나 설명이 생성되지 않았습니다. 확인된 범위에서 해석해야 합니다.")
    return ChatResponse("\n\n".join(summary_parts), evidence, blocks=tuple(blocks),
                        lead_evidence_ids=tuple(e["id"] for e in evidence if e["id"] in {"PRICE", "PER", "PBR", "ROE"}))
