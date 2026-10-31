"""기존 Groq 요청과 한도 정책을 보존한 공급자."""
import json
from src.config import Settings
from src.models import AppError
from src.agents.output_contract import response_format, _schema_messages, FACT_TEMPERATURE
from src.agents.rate_control import current_pacer, rate_limit_error
from src.agents.providers.result import Completion


def invoke(settings: Settings, instruction: str, payload: dict, max_tokens: int,
            temperature: float = FACT_TEMPERATURE, *, sleep) -> Completion:
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
                sleep(delay + 0.2)
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
    return Completion(response.content, response.response_metadata.get("finish_reason"), response.response_metadata.get("token_usage"))
