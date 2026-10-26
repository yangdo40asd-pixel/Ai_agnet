"""화면과 독립적인 자료 갱신 판단 및 결과 메시지 조립."""
from datetime import datetime
from src.models import AnalysisResult, AnswerBlock, ChatResponse
from src.agents.evidence import build_evidence
from src.agents.answer_quality import select_evidence
from src.agents.report_presentation import HEADLINE_SCOPE, news_sections


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
    evidence = []
    commentary = result.commentary
    summary_parts = [f"**{result.financial.stock.name} 조회 결과**"]
    blocks = []
    comparison = select_evidence("실적", [], evidence_map, []).evidence
    compared = {k: v for k, v in comparison.items() if v.get("kind") == "annual_comparison"}
    if compared and scope in {"all", "financials"}:
        labels = {"CFS": "연결재무제표", "OFS": "별도재무제표"}
        lines = [f"{labels.get(item['fs_div'], item['fs_div'])} · {item['text']}" for item in compared.values()]
        blocks.append(AnswerBlock("연간 실적", "\n\n".join(lines), tuple(compared)))
        evidence.extend(dict(item, id=key) for key, item in compared.items())
    elif result.financial.price is not None and scope in {"all", "finance"}:
        summary_parts.append("조회된 주가는 " + evidence_map["PRICE"]["value_text"] + "입니다.")
        evidence.append(dict(evidence_map["PRICE"], id="PRICE"))
    seen = {}
    if commentary:
        for label, statements in (*news_sections(commentary),
                                  ("재무 분석", () if compared else commentary.financial_commentary)):
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
    if any(key.startswith("NEWS_") for block in blocks for key in block.evidence_ids):
        summary_parts.append(HEADLINE_SCOPE)
    if result.ai_error and commentary is None and compared:
        summary_parts.append("AI 설명을 생성하지 못해 확인된 연간 수치를 먼저 표시합니다.")
    return ChatResponse("\n\n".join(summary_parts), evidence, blocks=tuple(blocks),
                        lead_evidence_ids=tuple(e["id"] for e in evidence if e["id"] == "PRICE"))
