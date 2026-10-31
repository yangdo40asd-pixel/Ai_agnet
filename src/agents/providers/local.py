"""localhost OpenAI 호환 API 공급자. 외부 공급자로 폴백하지 않는다."""
import json
import threading
import time
import httpx

from src.config import validate_local_settings
from src.models import AppError
from src.agents.output_contract import response_format, _schema_messages
from src.agents.providers.result import Completion
from src.agents.local_verification import current_local_verification, current_turn_remaining

_request_lock = threading.Lock()


def estimate_context_budget(messages: list[tuple[str, str]], max_tokens: int, context_window: int = 4096) -> dict:
    """입력 문자 수·추정 입력 토큰·예약 출력 토큰을 계산해 문맥 예산을 사전 점검한다."""
    input_chars = sum(len(str(content)) for _, content in messages)
    estimated_input_tokens = max(1, input_chars // 2)
    reserved_output_tokens = int(max_tokens)
    estimated_total_tokens = estimated_input_tokens + reserved_output_tokens
    return {
        "input_chars": input_chars,
        "estimated_input_tokens": estimated_input_tokens,
        "reserved_output_tokens": reserved_output_tokens,
        "estimated_total_tokens": estimated_total_tokens,
        "context_window": int(context_window),
        "fits_context": estimated_total_tokens <= int(context_window),
    }


def _is_complete_json_object(content) -> bool:
    """내용이 끝까지 닫힌 JSON 객체인지 확인한다. 중간에 잘린 JSON은 파싱되지 않는다."""
    try:
        return isinstance(json.loads(str(content).strip()), dict)
    except ValueError:
        return False


def invoke(settings, instruction, payload, max_tokens, temperature):
    validate_local_settings(settings)
    schema_mode = settings.local_output_mode == "schema"
    canonical = response_format(payload, settings.local_model, schema_supported=True)
    fmt = canonical if schema_mode else {"type": "json_object"}
    # 스키마 모드는 API 문법 제약이 구조를 보장한다. 같은 스키마를 본문에
    # 다시 넣어 업무 근거·심사 출력의 문맥을 소모하지 않는다.
    messages = _schema_messages(instruction, payload, None if schema_mode else canonical["json_schema"]["schema"])
    from src.agents.providers.local_payload import compact_messages
    messages = compact_messages(messages)
    budget_estimate = estimate_context_budget(messages, max_tokens, int(getattr(settings, "local_context_window", 4096) or 4096))
    headroom = budget_estimate["context_window"] - budget_estimate["estimated_input_tokens"]
    effective_max_tokens = min(max_tokens, max(300, headroom - 64)) if headroom > 300 else max_tokens
    body = {"model": settings.local_model, "messages": [{"role": "system" if r == "system" else "user", "content": c} for r, c in messages],
            "temperature": temperature, "max_tokens": effective_max_tokens, "response_format": fmt, "stream": False}
    headers = {"Authorization": "Bearer " + settings.local_api_key} if settings.local_api_key else {}
    remaining = current_turn_remaining()
    if remaining is not None and remaining <= 0:
        raise AppError("ai_local_turn_timeout", "질문 처리 전체 제한 시간을 초과했습니다. 질문을 나누어 다시 시도해 주세요.")
    lock_wait = min(settings.local_read_timeout, max(0.1, remaining)) if remaining is not None else settings.local_read_timeout
    if not _request_lock.acquire(timeout=lock_wait):
        raise AppError("ai_local_busy", "로컬 모델의 이전 요청이 처리 중입니다. 잠시 후 다시 입력해 주세요.")
    budget = current_local_verification()
    started = time.monotonic()
    event = {
        "task": payload.get("task", "financial_report" if "financial_facts" in payload else "basic_report" if "headlines" in payload else "candidates"),
        "provider": "local",
        "input_chars": budget_estimate["input_chars"],
        "estimated_input_tokens": budget_estimate["estimated_input_tokens"],
        "reserved_output_tokens": budget_estimate["reserved_output_tokens"],
    }
    try:
        remaining = current_turn_remaining()
        if remaining is not None and remaining <= 0:
            raise AppError("ai_local_turn_timeout", "질문 처리 전체 제한 시간을 초과했습니다. 질문을 나누어 다시 시도해 주세요.")
        if budget:
            budget.before_request()
        read_timeout = min(settings.local_read_timeout, max(0.1, remaining)) if remaining is not None else settings.local_read_timeout
        # 클라이언트 타임아웃은 대기 중단이며 서버 내부 연산 취소까지 보장한다고 가정하지 않는다.
        with httpx.Client(timeout=httpx.Timeout(read_timeout, connect=settings.local_connect_timeout),
                          follow_redirects=False, trust_env=False) as client:
            response = client.post(settings.local_base_url.rstrip("/") + "/chat/completions", json=body, headers=headers)
        event["http_status"] = response.status_code
        if response.status_code != 200:
            # 원문 오류나 프롬프트를 사용자/로그로 복사하지 않는다.
            if response.status_code in {401, 403}:
                code, message = "ai_local_auth", "로컬 AI 서버의 인증 설정을 확인해 주세요."
            elif response.status_code == 404:
                code, message = "ai_local_model", "로컬 AI 주소와 등록된 모델 ID를 확인해 주세요."
            elif response.status_code in {400, 413, 422}:
                code, message = "ai_local_request", "로컬 모델의 문맥 길이·출력 형식·요청 설정을 확인해 주세요."
            elif response.status_code in {429, 503}:
                code, message = "ai_local_busy", "로컬 모델이 준비 중이거나 다른 요청을 처리 중입니다."
            else:
                code, message = "ai_local_failed", "로컬 AI 서버 응답에 실패했습니다. 서버 상태를 확인해 주세요."
            raise AppError(code, message)
        try:
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("choices"), list) or not data["choices"]:
                raise ValueError("invalid choices")
            choice = data["choices"][0]
            if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict) or choice.get("finish_reason") not in {"stop", "length"}:
                raise ValueError("invalid completion")
            message = choice["message"]
            if not isinstance(message.get("content"), str):
                raise ValueError("missing content")
            usage = data.get("usage")
            usage = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                     if type(usage.get(key)) is int and usage[key] >= 0} if isinstance(usage, dict) else None
            event["usage"] = usage
            if usage and "prompt_tokens" in usage:
                event["budget_total_tokens"] = usage["prompt_tokens"] + int(max_tokens)
            finish_reason = choice.get("finish_reason")
            if finish_reason == "length" and _is_complete_json_object(message["content"]):
                # 문법 제약 생성은 JSON을 끝낸 뒤에도 공백만 계속 내보내다 출력 한도에서 멈출 수 있다.
                # 내용 자체가 완결된 JSON 객체이면 잘린 응답이 아니므로 정상 종료로 처리한다.
                event["finish_reason_original"] = "length"
                finish_reason = "stop"
            event["finish_reason"] = finish_reason
            return Completion(message["content"], finish_reason, usage)
        except (ValueError, TypeError, KeyError, IndexError):
            raise AppError("ai_local_format", "로컬 AI의 응답 구조를 확인하지 못했습니다.") from None
    except httpx.ConnectError:
        event["error_code"] = "ai_local_unavailable"
        raise AppError("ai_local_unavailable", "로컬 AI 서버에 연결할 수 없습니다. 서버 실행 상태를 확인해 주세요.") from None
    except httpx.TimeoutException:
        remaining_after = current_turn_remaining()
        if remaining_after is not None and remaining_after <= 0:
            event["error_code"] = "ai_local_turn_timeout"
            raise AppError("ai_local_turn_timeout", "질문 처리 전체 제한 시간을 초과했습니다. 질문을 나누어 다시 시도해 주세요.") from None
        event["error_code"] = "ai_local_timeout"
        raise AppError("ai_local_timeout", "로컬 AI 응답 제한 시간을 초과했습니다. 모델과 문맥 설정을 확인해 주세요.") from None
    except httpx.RequestError:
        event["error_code"] = "ai_local_failed"
        raise AppError("ai_local_failed", "로컬 AI와 통신하는 중 연결 오류가 발생했습니다.") from None
    except AppError as error:
        event["error_code"] = error.code
        raise
    finally:
        event["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if budget:
            budget.events.append(event)
        _request_lock.release()
