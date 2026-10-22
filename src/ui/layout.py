"""16:9 기준 화면에서 헤더와 입력 영역을 뺀 패널 높이."""

REFERENCE_VIEWPORT_HEIGHT = 1080
REFERENCE_HEADER_HEIGHT = 160
REFERENCE_CONTROLS_HEIGHT = 430

# 색상·치수만 포함한다. 사용자 입력은 HTML/CSS에 삽입하지 않는다.
WORKSPACE_CSS = """
<style>
.stMainBlockContainer {padding: 1.25rem 2rem 1rem; max-width: 1920px;}
.st-key-app_header h1 {font-size: 1.65rem; padding-top: 0;}
.st-key-chat_scroll, [class*="st-key-canvas_scroll_"] {
    border: 1px solid #dce4ed; border-radius: 14px; background: #fafcff;
    overscroll-behavior: contain;
}
[class*="st-key-canvas_card_"] {
    border: 1px solid #dce4ed; border-radius: 12px; padding: 1rem; background: white;
}
.st-key-chat_controls {padding-top: .4rem;}
.st-key-chat_controls [data-testid="stForm"] {padding: .65rem;}
@media (max-width: 899px) {
    .stMainBlockContainer {padding: 1rem .75rem;}
    section.stMain {overflow: auto;}
}
</style>
"""


def canvas_scroll_key(generation: int) -> str:
    """대화 rerun은 기존 스크롤을 유지하고 카드 추가 때만 새 영역을 만든다."""
    return f"canvas_scroll_{int(generation)}"


def panel_content_height(
    viewport_height: int = REFERENCE_VIEWPORT_HEIGHT,
    header_height: int = REFERENCE_HEADER_HEIGHT,
    controls_height: int = REFERENCE_CONTROLS_HEIGHT,
) -> int:
    """뷰포트에서 헤더와 하단 조작 높이를 뺀 스크롤 패널 높이를 반환한다."""
    if viewport_height <= 0 or header_height < 0 or controls_height < 0:
        raise ValueError("화면 높이는 0보다 커야 합니다.")
    height = viewport_height - header_height - controls_height
    if height < 240 or header_height + height + controls_height > viewport_height:
        raise ValueError("패널 높이가 기준 화면을 벗어납니다.")
    return height
