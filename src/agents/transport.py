"""업무 호출의 공통 진입점. 공급자 선택과 JSON 반환 계약을 한곳에서 유지한다."""
import time
from src.agents.output_contract import (parse_json_response, response_format, _schema_messages,
                                        FACT_TEMPERATURE, CHAT_TEMPERATURE)
from src.models import AppError


def _invoke(settings, instruction, payload, max_tokens, temperature=FACT_TEMPERATURE):
    if settings.ai_provider == "groq":
        from src.agents.providers.groq import invoke
        response = invoke(settings, instruction, payload, max_tokens, temperature, sleep=time.sleep)
    elif settings.ai_provider == "local":
        from src.agents.providers.local import invoke
        response = invoke(settings, instruction, payload, max_tokens, temperature)
    else:
        raise AppError("ai_settings", "AI 공급자는 groq 또는 local로 지정해 주세요.")
    if response.finish_reason == "length":
        raise AppError("ai_truncated", "AI 응답이 중간에 잘려 결과로 사용하지 않았습니다. 다시 시도해 주세요.")
    parsed = parse_json_response(response.content)
    if isinstance(parsed, dict) and payload.get("task") == "chat_answer":
        if isinstance(parsed.get("evidence_ids"), list) and all(isinstance(x, str) for x in parsed["evidence_ids"]):
            parsed["evidence_ids"] = list(dict.fromkeys(parsed["evidence_ids"]))
        if isinstance(parsed.get("blocks"), list):
            for block in parsed["blocks"]:
                if isinstance(block, dict) and isinstance(block.get("evidence_ids"), list) and all(isinstance(x, str) for x in block["evidence_ids"]):
                    block["evidence_ids"] = list(dict.fromkeys(block["evidence_ids"]))
    return parsed
