"""기본 뉴스 리포트의 표시·심사에 공통으로 쓰는 내용 계약."""

HEADLINE_SCOPE = "관련 소식은 수집된 뉴스 제목을 기준으로 정리했습니다."


def news_sections(commentary):
    return (("종합 분석", (commentary.summary,)), ("테마 동향", commentary.theme_trend),
            ("기회 요인", (commentary.opportunity,)), ("위험 요인", (commentary.risk,)))
