"""실제 API 검수용 호출 간격. 키·본문 없이 한도와 사용량만 기록한다."""
from contextlib import contextmanager
from contextvars import ContextVar
import math
import re
import time

from src.models import AppError

_active = ContextVar("api_verification_pacer", default=None)


def seconds(value):
    """공급자의 초 또는 1m2.5s 형식만 읽는다. 임의 문자열은 보존하지 않는다."""
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return None
    text = str(value).strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        number = float(text)
    else:
        parts = re.findall(r"(\d+(?:\.\d+)?)(ms|s|m|h|d)", text)
        if not parts or "".join(n + unit for n, unit in parts) != text:
            return None
        scales = {"ms": .001, "s": 1, "m": 60, "h": 3600, "d": 86400}
        number = sum(float(n) * scales[unit] for n, unit in parts)
    return number if math.isfinite(number) and 0 <= number <= 604800 else None


def safe_limits(headers):
    """허용한 한도 헤더의 숫자만 반환한다."""
    if not hasattr(headers, "get"):
        headers = {}
    limits = {}
    for suffix in ("limit-requests", "remaining-requests", "limit-tokens", "remaining-tokens"):
        value = headers.get("x-ratelimit-" + suffix)
        if isinstance(value, str) and re.fullmatch(r"\d{1,12}", value):
            limits[suffix.replace("-", "_")] = int(value)
    for name, header in (("retry_after_seconds", "retry-after"),
                         ("reset_tokens_seconds", "x-ratelimit-reset-tokens"),
                         ("reset_requests_seconds", "x-ratelimit-reset-requests")):
        value = seconds(headers.get(header))
        if value is not None:
            limits[name] = value
    return limits


def rate_limit_error(error):
    limits = safe_limits(getattr(getattr(error, "response", None), "headers", {}))
    delay = limits.get("retry_after_seconds")
    message = (f"AI 요청 한도에 도달했습니다. 약 {math.ceil(delay)}초 후 다시 입력해 주세요."
               if delay is not None else "AI 요청 한도에 도달했습니다. 잠시 기다린 뒤 다시 입력해 주세요.")
    return AppError("ai_rate_limit", message)


def verification_stop(error):
    """SDK가 감싼 자체 검수 중단만 복원한다. 공급자 오류 본문은 해석하지 않는다."""
    pending, seen = [error], set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, AppError) and current.code in {"ai_verification_budget", "ai_rate_limit"}:
            return current
        pending.extend(e for e in (current.__cause__, current.__context__) if isinstance(e, BaseException))
    return None


class VerificationPacer:
    """한 검수 프로세스의 HTTP 요청을 제어한다. 다른 프로세스/조직 사용량은 통제하지 못한다."""

    def __init__(self, interval=65.0, max_wait=180.0, *, max_requests=6, clock=None, sleep=None):
        if not (60 <= interval <= max_wait <= 300):
            raise ValueError("검수 간격은 60초 이상, 최대 대기는 300초 이하여야 합니다.")
        self.interval, self.max_wait = interval, max_wait
        if type(max_requests) is not int or not 1 <= max_requests <= 12:
            raise ValueError("검수 호출 예산은 1~12회여야 합니다.")
        self.max_requests = max_requests
        self.request_count = 0
        self.halted = False
        self.clock, self.sleep = clock or time.monotonic, sleep or time.sleep
        self.next_at = 0.0
        self.events = []
        self.client = None

    def before_request(self, request):
        if self.halted:
            raise AppError("ai_rate_limit", "한도 또는 잔량 소진이 확인되어 이번 검수를 중단했습니다.")
        if self.request_count >= self.max_requests:
            raise AppError("ai_verification_budget", "이번 검수의 API 호출 예산을 모두 사용해 추가 호출을 중단했습니다.")
        delay = max(0.0, self.next_at - self.clock())
        if delay > self.max_wait:
            raise AppError("ai_rate_limit", f"AI 사용량 회복까지 약 {math.ceil(delay)}초가 필요해 검수를 중단했습니다.")
        if delay:
            self.events.append({"event": "wait", "seconds": round(delay, 3)})
            print(f"API 검수 대기: {math.ceil(delay)}초", flush=True)
            # 긴 대기도 짧게 나눠 중단 가능하게 한다.
            while True:
                remaining = self.next_at - self.clock()
                if remaining <= 0:
                    break
                self.sleep(min(30.0, remaining))
        self.request_count += 1
        self.next_at = self.clock() + self.interval

    def after_response(self, response):
        limits = safe_limits(response.headers)
        # 잔량 회복을 추측해 재시도하지 않는다. 다음 실행은 별도 판단한다.
        if response.status_code == 429 or limits.get("remaining_requests") == 0:
            self.halted = True
        now = self.clock()
        self.next_at = max(self.next_at, now + self.interval)
        delay = limits.get("retry_after_seconds")
        if response.status_code == 429 and delay is not None:
            self.next_at = max(self.next_at, now + delay + 1)
        for category in ("requests", "tokens"):
            if limits.get("remaining_" + category) == 0:
                self.next_at = max(self.next_at, now + limits.get("reset_" + category + "_seconds", 0) + 1)
        self.events.append({"event": "response", "status": response.status_code, "limits": limits})

    def record_usage(self, metadata):
        usage = metadata.get("token_usage", {}) if isinstance(metadata, dict) else {}
        if not isinstance(usage, dict):
            return
        clean = {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                 if type(usage.get(key)) is int and usage[key] >= 0}
        if clean:
            self.events.append({"event": "usage", **clean})

    def record_schema_failure(self, detail, response_format, task):
        # 원문 오류·모델 생성문·API 키를 로그나 다음 프롬프트로 복사하지 않는다.
        from src.agents.schema_diagnostics import schema_failure_summary
        event = schema_failure_summary(detail, response_format, task)
        self.events.append(event)
        print(f"API 스키마 검사: {event}", flush=True)

    def report(self):
        return {"interval_seconds": self.interval, "max_wait_seconds": self.max_wait,
                "max_requests": self.max_requests, "request_count": self.request_count,
                "halted": self.halted,
                "scope": "one_verification_process", "events": list(self.events)}


def current_pacer():
    return _active.get()


@contextmanager
def paced_verification(interval=65.0, *, max_requests=6):
    import httpx
    pacer = VerificationPacer(interval, max_requests=max_requests)
    with httpx.Client(event_hooks={"request": [pacer.before_request], "response": [pacer.after_response]}) as client:
        pacer.client = client
        token = _active.set(pacer)
        try:
            yield pacer
        finally:
            _active.reset(token)
