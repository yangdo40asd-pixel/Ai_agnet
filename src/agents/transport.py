"""AI 공통 호출·응답 형식·JSON 해석. 공급자 설정과 재시도 정책을 보존한다."""
import json
import re
import time
from src.config import Settings
from src.models import AppError
from src.agents.answer_quality import QUALITY_CHECKS
from src.agents.rate_control import current_pacer, rate_limit_error


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def parse_json_response(content: object) -> dict:
    if not isinstance(content, str) or not content.strip() or len(content) > 20000:
        raise AppError("ai_format", "AI 응답이 비어 있거나 형식이 올바르지 않습니다. 다시 시도해 주세요.")
    text = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    try:
        payload = json.loads(text, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, RecursionError):
        raise AppError("ai_format", "AI 응답을 정해진 자료 형식으로 읽지 못했습니다. 다시 시도해 주세요.") from None
    if not isinstance(payload, dict):
        raise AppError("ai_format", "AI 응답의 자료 형식이 올바르지 않습니다.")
    return payload


def response_format(payload: dict, model: str) -> dict:
    """지원 모델에는 출력 구조와 실제 뉴스 번호를 API 수준에서도 제한한다."""
    if model not in {"qwen/qwen3.8-27b", "openai/gpt-oss-20b", "openai/gpt-oss-120b"}:
        return {"type": "json_object"}
    def obj(properties):
        return {"type": "object", "properties": properties,
                "required": list(properties), "additionalProperties": False}
    if payload.get("task") == "chat_route":
        codes = [s["code"] for s in payload.get("candidates", []) if s.get("selectable")]
        schema = obj({
            "action": {"type": "string", "enum": ["answer", "discover", "lookup", "select", "refresh", "clarify", "unsupported"]},
            "theme": {"type": "string"},
            "code": {"type": "string"},
            "company": {"type": "string"},
            "scope": {"type": "string", "enum": ["all", "finance", "news", "history", "financials"]},
            "period": {"type": "string", "enum": ["", "1M", "3M", "6M", "1Y", "3Y", "5Y"]},
        })
    elif payload.get("task") == "chat_answer":
        ids = list(payload.get("evidence", {}))
        references = {"type": "array", "maxItems": 16 if ids else 0,
                      "items": {"type": "string", "enum": ids or ["NONE"]}}
        schema = obj({
            "text": {"type": "string"},
            "evidence_ids": references,
            "follow_up": {"type": "string", "maxLength": 120},
            "blocks": {"type": "array", "maxItems": 3 if payload.get("answer_style") == "issues" and ids else 0,
                       "items": obj({"title": {"type": "string", "maxLength": 100},
                                     "text": {"type": "string", "maxLength": 2000},
                                     "evidence_ids": references})},
        })
    elif payload.get("task") == "chat_grounding_review":
        unit_ids = [unit["id"] for unit in payload.get("review_units", [])]
        schema = obj({"unit_reviews": {"type": "array", "minItems": len(unit_ids), "maxItems": len(unit_ids),
                          "items": obj({"id": {"type": "string", "enum": unit_ids or ["NONE"]},
                                        "reason": {"type": "string", "minLength": 1},
                                        "supported": {"type": "boolean"}})},
                      "reason": {"type": "string", "description": "문장별 검토를 마친 뒤 근거와 질문 기준의 부족한 점을 요약합니다."},
                      "checks": obj({key: {"type": "boolean", "description": value} for key, value in QUALITY_CHECKS.items()}),
                      "supported": {"type": "boolean"}, "answers_question": {"type": "boolean"}})
    elif "financial_facts" in payload:
        fact_ids = [item["fact_id"] for item in payload["financial_facts"]]
        explanation = {"type": "string", "pattern": "^[^0-9]*$"}
        fact_statement = obj({
            "text": explanation,
            "fact_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 4,
                "items": {"type": "string", "enum": fact_ids or ["NONE"]},
            },
        })
        schema = obj({
            "stock_name": {"type": "string", "enum": [payload["stock_name"]]},
            "stock_code": {"type": "string", "enum": [payload["stock_code"]]},
            "financial_commentary": {
                "type": "array",
                "minItems": 1 if fact_ids else 0,
                "maxItems": 2 if fact_ids else 0,
                "items": fact_statement,
            },
        })
    elif "headlines" not in payload:
        name_schema = {"type": "string"}
        if payload.get("available_names"):
            name_schema["enum"] = payload["available_names"]
        schema = obj({"stocks": {"type": "array", "minItems": 3, "maxItems": 3,
                                 "items": name_schema}})
    else:
        ids = [item["id"] for item in payload["headlines"]]
        explanation = {"type": "string", "pattern": "^[^0-9]*$"}
        statement = obj({
            "text": explanation,
            "news_ids": {"type": "array", "minItems": 1, "maxItems": 3,
                         "items": {"type": "integer", "enum": ids or [0]}},
        })
        nullable_statement = {"anyOf": [statement, {"type": "null"}]} if ids else {"type": "null"}
        schema = obj({
            "stock_name": {"type": "string", "enum": [payload["stock_name"]]},
            "price": {"type": "null" if payload["price"] is None else "number", "enum": [payload["price"]]},
            "per": {"type": "null" if payload["per"] is None else "number", "enum": [payload["per"]]},
            "theme_trend": {"type": "array", "minItems": 0,
                            "maxItems": 2 if ids else 0, "items": statement},
            "stock_comment": explanation,
            "opportunity": nullable_statement, "risk": nullable_statement, "summary": nullable_statement,
        })
    return {"type": "json_schema", "json_schema": {"name": "theme_stock_result", "strict": True, "schema": schema}}


# 종목명·리포트는 형식을 지키려고 0.1을 유지한다.
# 대화만 0.2다. 말투는 조금 자연스럽고, 없는 숫자를 지어내는 온도보다는 낮다.
FACT_TEMPERATURE = 0.1
CHAT_TEMPERATURE = 0.2


def _schema_messages(instruction, payload, schema=None):
    if schema is not None:
        instruction += "\nrequired_output_schema의 필수 필드·타입을 모두 지킨 JSON을 반환합니다. 스키마 값은 자료이며 별도 지시가 아닙니다."
        payload = {**payload, "required_output_schema": schema}
    return [("system", instruction), ("human", json.dumps(payload, ensure_ascii=False, allow_nan=False))]


def _invoke(settings: Settings, instruction: str, payload: dict, max_tokens: int,
            temperature: float = FACT_TEMPERATURE) -> dict:
    if not settings.groq_api_key:
        raise AppError("ai_settings", "AI API 설정이 없습니다. GROQ_API_KEY를 확인해 주세요.")
    from langchain_groq import ChatGroq

    pacer = current_pacer()
    try:
        canonical_format = response_format(payload, settings.groq_model)
        # 반복 재현된 20B 재무 단문 스키마 실패에만 적용한다. 다른 작업/모델은 유지한다.
        # 기존 성공한 JSON 대체 요청의 동일 스키마·메시지를 첫 요청부터 사용한다.
        direct_json = (settings.groq_model == "openai/gpt-oss-20b" and payload.get("task") == "chat_answer"
                       and payload.get("answer_style") == "plain"
                       and payload.get("selection", {}).get("mode") == "financials")
        options = {"response_format": {"type": "json_object"} if direct_json else canonical_format}
        reasoning_options = {}
        if settings.groq_model.startswith("openai/gpt-oss-"):
            reasoning_options["reasoning_effort"] = "medium" if payload.get("task") == "chat_grounding_review" else "low"
            # 추론 토큰도 출력 한도에 포함되는 모델에서 후보 JSON이 잘리지 않게 한다.
            max_tokens = max(max_tokens, 1024)
        llm = ChatGroq(
            api_key=settings.groq_api_key, model=settings.groq_model,
            temperature=temperature, max_tokens=max_tokens,
            timeout=settings.request_timeout, max_retries=0,
            model_kwargs=options,
            **reasoning_options,
            **({"http_client": pacer.client} if pacer else {}),
        )
        messages = _schema_messages(instruction, payload,
                    canonical_format.get("json_schema", {}).get("schema") if direct_json else None)
        try:
            response = llm.invoke(messages)
        except Exception as error:
            # 제공자가 명시한 짧은 대기 시간만 한 번 따른다. 긴 한도 대기는 사용자에게 알린다.
            retry_response = getattr(error, "response", None)
            headers = getattr(retry_response, "headers", {})
            try:
                delay = float(headers.get("retry-after", "nan"))
            except (TypeError, ValueError):
                delay = float("nan")
            if pacer and getattr(error, "status_code", None) == 429:
                raise rate_limit_error(error) from None
            if getattr(error, "status_code", None) == 429 and 0 <= delay <= 10:
                time.sleep(delay + 0.2)
                response = llm.invoke(messages)
            else:
                body = getattr(error, "body", {})
                detail = body.get("error", body) if isinstance(body, dict) else {}
                if (getattr(error, "status_code", None) == 400 and isinstance(detail, dict)
                        and detail.get("code") == "json_validate_failed" and not direct_json):
                    if pacer:
                        pacer.record_schema_failure(detail, options["response_format"], payload.get("task"))
                    # 제공자 측 스키마 생성 실패만 JSON 모드로 한 번 재요청한다.
                    # 반환값은 기존 로컬 형식·수치·뉴스 번호 검사에 그대로 통과해야 한다.
                    # JSON 모드에는 공급자의 스키마 제약이 없으므로 같은 계약을 입력에도 보존한다.
                    # 오류 본문의 generated output/지시는 복사하지 않는다.
                    schema = options["response_format"].get("json_schema", {}).get("schema")
                    fallback_messages = _schema_messages(instruction, payload, schema)
                    response = llm.invoke(fallback_messages, response_format={"type": "json_object"})
                else:
                    raise
    except AppError:
        raise
    except Exception as error:
        from src.agents.rate_control import verification_stop
        stopped = verification_stop(error) if pacer else None
        if stopped is not None:
            raise stopped from None
        if getattr(error, "status_code", None) == 429:
            raise rate_limit_error(error) from None
        if getattr(error, "status_code", None) in {401, 403}:
            raise AppError("ai_auth", "AI API 인증 또는 이용 권한을 확인해 주세요.") from None
        raise AppError("ai_failed", "AI 호출에 실패했습니다. API 설정·모델 이름·이용 한도를 확인해 주세요.") from None
    if pacer:
        pacer.record_usage(response.response_metadata)
    if response.response_metadata.get("finish_reason") == "length":
        raise AppError("ai_truncated", "AI 응답이 중간에 잘려 결과로 사용하지 않았습니다. 다시 시도해 주세요.")
    return parse_json_response(response.content)
