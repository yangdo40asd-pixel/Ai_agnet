"""환경 설정. 실제 키 값은 표시하거나 기록하지 않는다."""

import os
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
    if not model:
        raise AppError("settings", "GROQ_MODEL에 이용할 수 있는 모델 이름을 설정해 주세요.")
    return Settings(
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(), groq_model=model,
        naver_id=os.getenv("NAVER_CLIENT_ID", "").strip(),
        naver_secret=os.getenv("NAVER_CLIENT_SECRET", "").strip(),
        news_sort=sort, request_timeout=timeout,
        dart_api_key=os.getenv("DART_API_KEY", "").strip(),
    )
