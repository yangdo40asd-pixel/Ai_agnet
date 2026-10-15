"""입력 → 후보 확인 → 수집 → AI 설명을 연결하는 처리 순서."""

from collections.abc import Callable

from src.agents.report import generate_commentary, propose_candidates
from src.config import load_settings
from src.data.news import fetch_news
from src.data.stock import candidate_options, fetch_financial, load_listing, require_target, resolve_candidates
from src.models import AnalysisResult, AppError


def normalize_theme(theme: str) -> str:
    normalized = " ".join(theme.split())
    if not normalized:
        raise AppError("input_empty", "테마를 입력해 주세요.")
    if len(normalized) > 120:
        raise AppError("input_length", "테마는 120자 이내로 입력해 주세요.")
    return normalized


def analyze_theme(theme: str, on_progress: Callable[[str], None] | None = None) -> AnalysisResult:
    progress = on_progress or (lambda _: None)
    theme = normalize_theme(theme)
    settings = load_settings()
    progress("관련 종목 후보를 제안하고 있습니다.")
    names = propose_candidates(theme, settings)
    progress("상장 여부와 시장·종목코드를 확인하고 있습니다.")
    listing = load_listing()
    candidates = resolve_candidates(names, listing)
    rejected = tuple(stock.name for stock in candidates if not stock.verified or stock.reason)
    if rejected:
        progress("확인되지 않은 종목명을 제외하고 후보를 한 번 더 확인하고 있습니다.")
        try:
            options = candidate_options(theme, candidates, listing) if listing is not None else ()
            revised_names = propose_candidates(theme, settings, rejected_names=rejected, available_names=options)
            revised = resolve_candidates(revised_names, listing)
            if all(stock.verified and not stock.reason for stock in revised):
                candidates = revised
        except AppError:
            # 최초 결과와 기존 중단/미확인 안내를 보존한다. 무한 재시도하지 않는다.
            pass
    target = require_target(candidates)
    progress("주가·PER를 조회하고 있습니다.")
    financial = fetch_financial(target)
    progress("관련 뉴스와 근거 링크를 수집하고 있습니다.")
    news = fetch_news(theme, target.name, settings)
    progress("AI 설명을 작성하고 조회값·뉴스 근거를 확인하고 있습니다.")
    try:
        commentary = generate_commentary(theme, financial, news, settings)
        ai_error = None
    except AppError as error:
        # 수집 자료를 보존하되 AI 리포트 생성 완료로 표시하지 않는다.
        commentary = None
        ai_error = error.message
    return AnalysisResult(theme, candidates, financial, news, commentary, ai_error)
