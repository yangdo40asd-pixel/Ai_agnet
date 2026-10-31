"""공급자의 응답에서 공통으로 필요한 정보만 정규화한다."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Completion:
    content: object
    finish_reason: str | None
    usage: dict | None = None
