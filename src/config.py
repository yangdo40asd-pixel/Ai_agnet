"""환경 설정. 실제 키 값은 표시하거나 기록하지 않는다."""

import os
import math
import ipaddress
from urllib.parse import urlsplit
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from src.models import AppError


@dataclass(frozen=True)
class Settings:
    groq_api_key: str = field(repr=False)
    groq_model: str
    naver_id: str = field(repr=False)
    naver_secret: str = field(repr=False)
    news_sort: str = "date"
    request_timeout: float = 30.0
    dart_api_key: str = field(default="", repr=False)
    ai_provider: str = "groq"
    local_base_url: str = "http://127.0.0.1:1234/v1"
    local_model: str = ""
    local_connect_timeout: float = 5.0
    local_read_timeout: float = 180.0
    local_turn_timeout: float = 300.0
    local_output_mode: str = "schema"
    local_api_key: str = field(default="", repr=False)
    local_model_revision: str = ""
    news_relevance_mode: str = "auto"
    local_context_window: int = 4096

    @property
    def strict_news(self):
        return self.news_relevance_mode == "strict" or (self.news_relevance_mode == "auto" and self.ai_provider == "local")


def validate_local_settings(settings):
    """모의 생성 Settings도 같은 정책으로 검사한다. 네트워크 요청은 하지 않는다."""
    try:
        url = urlsplit(settings.local_base_url)
        host = url.hostname
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
        valid = (url.scheme == "http" and loopback and url.path.rstrip("/") == "/v1"
                 and not url.username and not url.password and not url.query and not url.fragment)
        _ = url.port
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise AppError("ai_local_settings", "로컬 AI 주소는 http://127.0.0.1:포트/v1 같은 로컬 주소로 설정해 주세요.")
    if not isinstance(settings.local_model, str) or not settings.local_model.strip() or len(settings.local_model) > 256:
        raise AppError("ai_local_settings", "로컬 서버에 등록된 모델 ID를 LOCAL_LLM_MODEL에 입력해 주세요.")
    if settings.local_output_mode not in {"schema", "json"}:
        raise AppError("ai_local_settings", "로컬 출력 방식은 schema 또는 json으로 설정해 주세요.")
    for value, upper in ((settings.local_connect_timeout, 30), (settings.local_read_timeout, 600), (settings.local_turn_timeout, 1800)):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 1 <= value <= upper:
            raise AppError("ai_local_settings", "로컬 연결 시간은 1~30초, 생성 제한 시간은 1~600초, 턴 전체 제한 시간은 1~1800초로 설정해 주세요.")


def load_settings() -> Settings:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    sort = os.getenv("NEWS_SORT", "date").strip()
    if sort not in {"date", "sim"}:
        raise AppError("settings", "NEWS_SORT는 date 또는 sim으로 설정해 주세요.")
    try:
        timeout = float(os.getenv("REQUEST_TIMEOUT", "30"))
    except ValueError:
        raise AppError("settings", "REQUEST_TIMEOUT에는 초 단위 숫자를 입력해 주세요.") from None
    if not 1 <= timeout <= 120:
        raise AppError("settings", "REQUEST_TIMEOUT은 1~120초 범위로 설정해 주세요.")
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
    provider = os.getenv("AI_PROVIDER", "groq").strip().lower()
    if provider not in {"groq", "local"}:
        raise AppError("settings", "AI_PROVIDER는 groq 또는 local로 설정해 주세요.")
    if provider == "groq" and not model:
        raise AppError("settings", "GROQ_MODEL에 이용할 수 있는 모델 이름을 설정해 주세요.")
    relevance_mode = os.getenv("NEWS_RELEVANCE_MODE", "auto").strip().lower()
    if relevance_mode not in {"auto", "standard", "strict"}:
        raise AppError("settings", "NEWS_RELEVANCE_MODE는 auto, standard 또는 strict로 설정해 주세요.")
    try:
        connect_timeout = float(os.getenv("LOCAL_LLM_CONNECT_TIMEOUT", "5"))
        read_timeout = float(os.getenv("LOCAL_LLM_READ_TIMEOUT", "180"))
        turn_timeout = float(os.getenv("LOCAL_LLM_TURN_TIMEOUT", "300"))
    except ValueError:
        if provider == "local":
            raise AppError("ai_local_settings", "로컬 요청 제한 시간에는 초 단위 숫자를 입력해 주세요.") from None
        connect_timeout, read_timeout, turn_timeout = 5.0, 180.0, 300.0
    # 로컬 서버의 --ctx-size와 같은 값을 넣는다. 기본 4096은 기존 동작과 같다.
    try:
        context_window = int(os.getenv("LOCAL_LLM_CONTEXT", "4096"))
        if not 2048 <= context_window <= 131072:
            raise ValueError
    except ValueError:
        if provider == "local":
            raise AppError("ai_local_settings", "LOCAL_LLM_CONTEXT에는 2048~131072 사이의 토큰 수를 입력해 주세요.") from None
        context_window = 4096
    settings = Settings(
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(), groq_model=model,
        naver_id=os.getenv("NAVER_CLIENT_ID", "").strip(),
        naver_secret=os.getenv("NAVER_CLIENT_SECRET", "").strip(),
        news_sort=sort, request_timeout=timeout,
        dart_api_key=os.getenv("DART_API_KEY", "").strip(),
        ai_provider=provider,
        local_base_url=os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:1234/v1").strip().rstrip("/"),
        local_model=os.getenv("LOCAL_LLM_MODEL", "").strip(),
        local_connect_timeout=connect_timeout, local_read_timeout=read_timeout,
        local_turn_timeout=turn_timeout,
        local_output_mode=os.getenv("LOCAL_LLM_OUTPUT_MODE", "schema").strip(),
        local_api_key=os.getenv("LOCAL_LLM_API_KEY", "").strip(),
        local_model_revision=os.getenv("LOCAL_LLM_MODEL_REVISION", "").strip(),
        news_relevance_mode=relevance_mode,
        local_context_window=context_window,
    )
    if provider == "local":
        validate_local_settings(settings)
    return settings
