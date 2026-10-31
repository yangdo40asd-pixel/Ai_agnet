"""후보 탐색의 사업 자료 보완. 기존 선택/결과/캔버스와 독립적인 데이터 흐름."""
from dataclasses import replace

from src.data.business import collect_business_profiles, has_direct_theme_support
from src.data.business_sources import collect_business_details, current_business_source
from src.models import AppError


def enrich_discovery(discovery, settings):
    business_error = ''
    try:
        profiles = collect_business_profiles(discovery.latest_candidates, settings)
    except AppError as error:
        # 상장 대조와 누적 후보를 버리지 않는다. 실제 결측은 답변에서 회사별로 표시한다.
        profiles = ()
        business_error = error.code
    current_codes = {p.stock_code for p in profiles}
    existing = tuple(p for p in discovery.business_profiles if p.stock_code not in current_codes)
    combined = (*existing, *profiles)
    by_code = {p.stock_code: p for p in combined}
    candidates = []
    for stock in discovery.candidates:
        profile = by_code.get(stock.code)
        if business_error or profile is None or stock.name != profile.stock_name:
            candidates.append(stock)
            continue
        supported = has_direct_theme_support(discovery.theme, profile)
        candidates.append(replace(stock,
            association_reason=f"업종: {profile.industry} · 주요제품: {profile.products}",
            association_source=profile.source_url,
            association_status="source_supported" if supported else "business_only"))
    from src.models import now_kst
    old_sources = tuple(getattr(discovery, 'business_sources', ()))
    fresh = {s.stock_code for s in old_sources if current_business_source(s)
             and 0 <= (now_kst() - s.retrieved_at).total_seconds() < 3600}
    profile_by_code = {p.stock_code: p for p in combined}
    needed = tuple(s for s in discovery.latest_candidates if s.selectable and s.code not in fresh
                   and (settings.dart_api_key or (s.code in profile_by_code
                        and profile_by_code[s.code].stock_name == s.name and profile_by_code[s.code].website_url)))
    detail_sources = old_sources
    statuses = dict(getattr(discovery, 'business_source_statuses', ()))
    if needed:
        try:
            batch = collect_business_details(needed, settings, profiles=combined)
            replaced_codes = {s.stock_code for s in batch.sources}
            detail_sources = (*[s for s in old_sources if s.stock_code not in replaced_codes], *batch.sources)
            statuses.update(batch.statuses)
        except AppError as error:
            statuses.update((s.code, error.code) for s in needed)
    return replace(discovery, candidates=tuple(candidates), business_profiles=combined, business_error=business_error,
                   business_sources=tuple(detail_sources), business_source_statuses=tuple(statuses.items()))
