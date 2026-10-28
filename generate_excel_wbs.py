import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from datetime import date, timedelta

wb = openpyxl.Workbook()

# Sheet 1: WBS 및 간트차트
ws = wb.active
ws.title = "WBS_스케줄링"

# 날짜 정의
start_date = date(2026, 10, 13)
end_date = date(2026, 12, 8)
total_days = (end_date - start_date).days + 1
date_list = [start_date + timedelta(days=i) for i in range(total_days)]

# 색상 정의
c_navy = "1F4E79"
c_blue_header = "2E75B6"
c_light_blue = "D9E1F2"
c_gray_bg = "F2F2F2"
c_dark_gray = "595959"
c_weekend = "F8F9FA"
c_sat = "EDF2F8"
c_sun = "FDEDEC"
c_today_col = "FFF2CC" # 기준일(10/13)

# 간트 바 색상
fill_kim = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid") # 김웅건 (파랑)
fill_cho = PatternFill(start_color="70AD47", end_color="70AD47", fill_type="solid") # 조윤기 (초록)
fill_both = PatternFill(start_color="ED7D31", end_color="ED7D31", fill_type="solid") # 공통 (주황)
fill_group = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid") # 상위 그룹

thin_border = Border(
    left=Side(style='thin', color='D9D9D9'),
    right=Side(style='thin', color='D9D9D9'),
    top=Side(style='thin', color='D9D9D9'),
    bottom=Side(style='thin', color='D9D9D9')
)

box_border = Border(
    left=Side(style='thin', color='BFBFBF'),
    right=Side(style='thin', color='BFBFBF'),
    top=Side(style='thin', color='BFBFBF'),
    bottom=Side(style='thin', color='BFBFBF')
)

# 1. 헤더 타이틀 영역 (Rows 1-5)
ws["A1"] = "프로젝트 WBS (Work Breakdown Structure) & 스케줄링"
ws["A1"].font = Font(name="맑은 고딕", size=16, bold=True, color="1F4E79")

ws["A2"] = "과목명: 데이터베이스구축실습  |  담당 교수: 노준  |  팀명: AI인사이트 (김웅건, 조윤기)"
ws["A2"].font = Font(name="맑은 고딕", size=10, color="595959")

ws["A3"] = "프로젝트명"
ws["B3"] = "AI 테마주 인사이트 리포트"
ws["B3"].font = Font(name="맑은 고딕", size=10, bold=True)
ws["D3"] = "기준일"
ws["E3"] = "2026-10-13"
ws["E3"].font = Font(name="맑은 고딕", size=10, bold=True, color="C00000")
ws["G3"] = "전체 기간"
ws["H3"] = "2026-10-13 ~ 2026-12-08 (총 8주 / 57일)"

ws["A4"] = "담당 역할"
ws["B4"] = "김웅건 (AI·화면·기획)  /  조윤기 (데이터·API·검증)"
ws["G4"] = "최종 산출물"
ws["H4"] = "Streamlit 기반 AI 리포트 웹 서비스, 최종 기획/검증 보고서"

# 2. 범례 (Row 5)
ws["A5"] = "범 례:"
ws["A5"].font = Font(name="맑은 고딕", size=9, bold=True)
legends = [
    ("B5", "김웅건 담당", "4472C4", "FFFFFF"),
    ("C5", "조윤기 담당", "70AD47", "FFFFFF"),
    ("D5", "공통 협업", "ED7D31", "FFFFFF"),
    ("E5", "대/중분류 요약", "D9E1F2", "000000"),
]
for cell_id, text, bg, fg in legends:
    ws[cell_id] = text
    ws[cell_id].fill = PatternFill(start_color=bg, end_color=bg, fill_type="solid")
    ws[cell_id].font = Font(name="맑은 고딕", size=9, bold=True, color=fg)
    ws[cell_id].alignment = Alignment(horizontal="center", vertical="center")

# 3. 테이블 헤더 (Rows 6-8)
# 기본 정보 열 (A~L: 12개 컬럼)
base_headers = [
    ("WBS", 7),
    ("업무명", 30),
    ("파트", 9),
    ("담당자", 9),
    ("등급/구분", 9),
    ("시작일", 12),
    ("종료일", 12),
    ("기간(일)", 8),
    ("진행률", 8),
    ("상태", 9),
    ("주요 산출물", 24),
    ("메모 / 비고", 22)
]

for col_idx, (h_name, width) in enumerate(base_headers, 1):
    ws.merge_cells(start_row=6, start_column=col_idx, end_row=8, end_column=col_idx)
    cell = ws.cell(row=6, column=col_idx, value=h_name)
    col_letter = get_column_letter(col_idx)
    ws.column_dimensions[col_letter].width = width

# 날짜 열 (Col 13 부터)
# Row 6: 월 (Month) 병합
# Row 7: 주차 (Week) 병합
# Row 8: 일자 / 요일
korean_weekdays = ["월", "화", "수", "목", "금", "토", "일"]

# 월 병합 계산
month_spans = {}
for idx, d in enumerate(date_list):
    m_key = f"{d.year}년 {d.month}월"
    if m_key not in month_spans:
        month_spans[m_key] = [idx, idx]
    else:
        month_spans[m_key][1] = idx

for m_key, (s_idx, e_idx) in month_spans.items():
    s_col = 13 + s_idx
    e_col = 13 + e_idx
    ws.merge_cells(start_row=6, start_column=s_col, end_row=6, end_column=e_col)
    c = ws.cell(row=6, column=s_col, value=m_key)
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.font = Font(name="맑은 고딕", size=10, bold=True, color="FFFFFF")
    c.fill = PatternFill(start_color=c_navy, end_color=c_navy, fill_type="solid")

# 주차 병합 계산 (화요일 시작 기준 Week 1 ~ Week 8)
for w in range(8):
    w_start_idx = w * 7
    w_end_idx = min(w_start_idx + 6, total_days - 1)
    s_col = 13 + w_start_idx
    e_col = 13 + w_end_idx
    ws.merge_cells(start_row=7, start_column=s_col, end_row=7, end_column=e_col)
    c = ws.cell(row=7, column=s_col, value=f"Week {w+1}")
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.font = Font(name="맑은 고딕", size=9, bold=True, color="FFFFFF")
    c.fill = PatternFill(start_color=c_blue_header, end_color=c_blue_header, fill_type="solid")

# Row 8: 일자 및 요일
for idx, d in enumerate(date_list):
    col = 13 + idx
    col_letter = get_column_letter(col)
    ws.column_dimensions[col_letter].width = 3.8
    weekday_str = korean_weekdays[d.weekday()]
    c = ws.cell(row=8, column=col, value=f"{d.day}\n{weekday_str}")
    c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    c.font = Font(name="맑은 고딕", size=8, bold=(d.weekday() >= 5))
    
    # 주말 및 기준일 배경
    if d == date(2026, 10, 13):
        c.fill = PatternFill(start_color="FFE699", end_color="FFE699", fill_type="solid")
    elif d.weekday() == 5:
        c.fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    elif d.weekday() == 6:
        c.fill = PatternFill(start_color="FCE4D6", end_color="FCE4D6", fill_type="solid")
    else:
        c.fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")

# 기본 헤더 셀 서식 적용
for r in range(6, 9):
    for c_i in range(1, 13):
        cell = ws.cell(row=r, column=c_i)
        cell.fill = PatternFill(start_color=c_navy, end_color=c_navy, fill_type="solid")
        cell.font = Font(name="맑은 고딕", size=9, bold=True, color="FFFFFF")
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

# 4. WBS 데이터 정의
# [wbs, name, part, owner, grade, start_str, end_str, progress, status, deliverable, memo, is_summary, depth]
tasks = [
    # 1.0 기획 및 요구분석
    ["1.0", "기획 및 요구분석", "기획", "-", "-", "2026-10-13", "2026-10-17", 0.5, "진행중", "기획 정의서 및 PoC 기록", True, 0],
    ["1.1", "  요구사항 정의", "기획", "김웅건", "고급", "2026-10-13", "2026-10-16", 0.8, "진행중", "요구사항 정의서", True, 1],
    ["1.1.1", "    서비스 목표 및 상세 범위 정리", "기획", "김웅건", "고급", "2026-10-13", "2026-10-15", 1.0, "완료", "초기 제안서 (P01)", False, 2],
    ["1.1.2", "    사용자 시나리오 및 이용 흐름 정의", "기획", "김웅건", "고급", "2026-10-14", "2026-10-16", 0.6, "진행중", "사용자 시나리오 정의서", False, 2],
    ["1.2", "  사전 기술 검증 (PoC)", "기술", "조윤기", "고급", "2026-10-13", "2026-10-17", 0.7, "진행중", "API 확인서 및 검증 기록", True, 1],
    ["1.2.1", "    종목·금융·뉴스 외부 API 응답 재확인", "데이터", "조윤기", "고급", "2026-10-13", "2026-10-15", 1.0, "완료", "API 응답 확인표 (V01)", False, 2],
    ["1.2.2", "    AI 호출 주기 및 PoC 파이프라인 검증", "AI", "김웅건", "고급", "2026-10-15", "2026-10-17", 0.4, "진행중", "PoC 검증 기록서 (V02)", False, 2],

    # 2.0 시스템 설계
    ["2.0", "시스템 설계", "설계", "-", "-", "2026-10-16", "2026-10-19", 0.0, "대기", "시스템/화면/프롬프트 설계서", True, 0],
    ["2.1", "  아키텍처 및 데이터 규격 설계", "설계", "조윤기", "고급", "2026-10-16", "2026-10-19", 0.0, "대기", "아키텍처/규격서", True, 1],
    ["2.1.1", "    시스템 모듈 구조 및 디렉토리 확정", "구조", "조윤기", "고급", "2026-10-16", "2026-10-18", 0.0, "대기", "아키텍처 설계도 (S03)", False, 2],
    ["2.1.2", "    모듈 간 데이터 입출력 및 오류 규격 확정", "데이터", "조윤기", "고급", "2026-10-17", "2026-10-19", 0.0, "대기", "데이터 전달 규격 (S04)", False, 2],
    ["2.2", "  화면 상태 및 AI 프롬프트 설계", "설계", "김웅건", "고급", "2026-10-16", "2026-10-19", 0.0, "대기", "화면/프롬프트 설계서", True, 1],
    ["2.2.1", "    입력대기/분석중/결과/오류 화면 초안 설계", "화면", "김웅건", "고급", "2026-10-16", "2026-10-18", 0.0, "대기", "화면 상태 설계도 (S01, S02)", False, 2],
    ["2.2.2", "    AI 입력출력 및 수치 검증 기준 확정", "AI", "김웅건", "고급", "2026-10-17", "2026-10-19", 0.0, "대기", "프롬프트 검증표 (S05)", False, 2],

    # 3.0 데이터 파이프라인 개발
    ["3.0", "데이터 파이프라인 개발", "개발", "-", "-", "2026-10-20", "2026-10-26", 0.0, "대기", "stock.py, news.py 모듈", True, 0],
    ["3.1", "  종목 식별 및 티커 매핑 모듈", "종목", "김웅건", "고급", "2026-10-20", "2026-10-25", 0.0, "대기", "src/data/stock.py", True, 1],
    ["3.1.1", "    AI 후보의 KRX 상장종목코드 확인 로직", "종목", "김웅건", "고급", "2026-10-20", "2026-10-23", 0.0, "대기", "종목 확인 함수 (D01)", False, 2],
    ["3.1.2", "    시장 구분(코스피/코스닥) 및 티커 자동 매핑", "종목", "김웅건", "고급", "2026-10-22", "2026-10-25", 0.0, "대기", "시장별 매핑 로직 (D02)", False, 2],
    ["3.2", "  금융 데이터 조회 및 전처리 모듈", "금융", "조윤기", "고급", "2026-10-21", "2026-10-26", 0.0, "대기", "금융 데이터 조회기", True, 1],
    ["3.2.1", "    대표 종목 주가 및 PER/PBR 조회 모듈 분리", "금융", "조윤기", "고급", "2026-10-21", "2026-10-24", 0.0, "대기", "주가/PER 조회 함수 (D03)", False, 2],
    ["3.2.2", "    조회값 결측치 처리 및 단위/반환값 표준화", "금융", "조윤기", "고급", "2026-10-24", "2026-10-26", 0.0, "대기", "금융 반환 표준 규격 (D04)", False, 2],
    ["3.3", "  뉴스 수집 및 메타데이터 정제 모듈", "뉴스", "조윤기", "고급", "2026-10-20", "2026-10-26", 0.0, "대기", "src/data/news.py", True, 1],
    ["3.3.1", "    네이버 뉴스 검색 요청 및 제목 태그 정제", "뉴스", "조윤기", "고급", "2026-10-20", "2026-10-23", 0.0, "대기", "뉴스 요청/정제 함수 (D05)", False, 2],
    ["3.3.2", "    원문 링크, 조회 시각, 언론사 정보 보관", "뉴스", "조윤기", "고급", "2026-10-22", "2026-10-25", 0.0, "대기", "뉴스 메타 반환 로직 (D06)", False, 2],
    ["3.3.3", "    종목 미확인 / API 오류 상태값 반환 및 폴백", "오류", "조윤기", "고급", "2026-10-24", "2026-10-26", 0.0, "대기", "데이터 오류 반환 로직 (D07)", False, 2],

    # 4.0 AI 분석 에이전트 개발
    ["4.0", "AI 분석 에이전트 개발", "AI", "-", "-", "2026-10-27", "2026-11-02", 0.0, "대기", "src/agents/report.py", True, 0],
    ["4.1", "  테마 관련주 제안 체인 구현", "AI", "김웅건", "고급", "2026-10-27", "2026-10-30", 0.0, "대기", "관련주 추출 체인 (D08-1)", False, 1],
    ["4.2", "  4단 인사이트 리포트 생성 체인 구현", "AI", "김웅건", "고급", "2026-10-29", "2026-11-01", 0.0, "대기", "리포트 생성 체인 (D08-2)", False, 1],
    ["4.3", "  AI 결과 항목 및 수치 일치 가드레일 로직", "AI", "김웅건", "고급", "2026-10-31", "2026-11-02", 0.0, "대기", "결과 검증 로직 (D09)", False, 1],

    # 5.0 화면(UI) 개발
    ["5.0", "화면(UI) 개발", "UI", "-", "-", "2026-11-03", "2026-11-09", 0.0, "대기", "src/ui/app.py", True, 0],
    ["5.1", "  Streamlit 2열 대시보드 기본 화면 구성", "화면", "김웅건", "고급", "2026-11-03", "2026-11-06", 0.0, "대기", "대시보드 뼈대 화면 (D10)", False, 1],
    ["5.2", "  좌측 대화형 테마 검색창 및 Spinner 인터랙션", "화면", "김웅건", "고급", "2026-11-05", "2026-11-08", 0.0, "대기", "대화형 입력 컴포넌트", False, 1],
    ["5.3", "  우측 금융 지표 카드 및 뉴스 아코디언 배치", "화면", "김웅건", "고급", "2026-11-06", "2026-11-09", 0.0, "대기", "결과 시각화 컴포넌트", False, 1],

    # 6.0 시스템 통합 및 고도화
    ["6.0", "시스템 통합 및 고도화", "통합", "-", "-", "2026-11-10", "2026-11-18", 0.0, "대기", "통합 실행 파이프라인 v1.0", True, 0],
    ["6.1", "  UI - Data - AI 전체 처리 흐름 파이프라인 연동", "연동", "김웅건", "고급", "2026-11-10", "2026-11-13", 0.0, "대기", "통합 연동 코드 (D11)", False, 1],
    ["6.2", "  종목 미확인 / 조회 실패 원인별 UI 오류 안내", "연동", "조윤기", "고급", "2026-11-12", "2026-11-15", 0.0, "대기", "상태별 안내 로직 (D11-오류)", False, 1],
    ["6.3", "  주가 변동 추이 차트(Plotly) 및 추가 지표 확장", "확장", "조윤기", "고급", "2026-11-14", "2026-11-18", 0.0, "대기", "차트 시각화 모듈 (확장기능)", False, 1],

    # 7.0 종합 검증 및 테스트
    ["7.0", "종합 검증 및 테스트", "검증", "-", "-", "2026-11-19", "2026-11-27", 0.0, "대기", "검증 결과표 4종", True, 0],
    ["7.1", "  UI-AI-데이터 정상 흐름 연결 통합 검증", "통합", "김웅건", "고급", "2026-11-19", "2026-11-22", 0.0, "대기", "통합 검증표 (V03)", False, 1],
    ["7.2", "  미일치/누락/요청 실패 예외 응답 검증", "데이터", "조윤기", "고급", "2026-11-20", "2026-11-23", 0.0, "대기", "API 예외 검증표 (V04)", False, 1],
    ["7.3", "  주가·PER·뉴스 원자료 출처 대조 정합성 검증", "데이터", "조윤기", "고급", "2026-11-22", "2026-11-25", 0.0, "대기", "수치출처 대조표 (V05)", False, 1],
    ["7.4", "  화면 가독성 및 응답 시간(Latency) 점검", "화면", "조윤기", "고급", "2026-11-24", "2026-11-27", 0.0, "대기", "사용성/응답시간 기록 (V06)", False, 1],

    # 8.0 최종 보고서 및 시연
    ["8.0", "최종 보고서 및 시연", "문서", "-", "-", "2026-11-28", "2026-12-08", 0.0, "대기", "최종 보고서 및 시연 자료", True, 0],
    ["8.1", "  API 및 원자료 검증 결과 최종 정리", "데이터", "조윤기", "고급", "2026-11-28", "2026-12-01", 0.0, "대기", "데이터 검증 기록 (R01)", False, 1],
    ["8.2", "  기획서 본문, WBS, 출처 통합 최종 보고서 완성", "문서", "김웅건", "고급", "2026-11-30", "2026-12-04", 0.0, "대기", "최종 보고서 PDF (R02)", False, 1],
    ["8.3", "  시연 절차 점검, 발표 슬라이드 및 리허설", "시연", "공통", "고급", "2026-12-03", "2026-12-07", 0.0, "대기", "시연안 제출본 (R03)", False, 1],
    ["8.4", "  프로젝트 최종 시연 및 산출물 제출 (종강)", "시연", "공통", "고급", "2026-12-08", "2026-12-08", 0.0, "대기", "종강 시연 완료 (R04)", False, 1],
]

curr_row = 9

for t in tasks:
    wbs_id, name, part, owner, grade, s_str, e_str, prog, status, deliverable, is_summary, depth = t
    s_dt = date.fromisoformat(s_str)
    e_dt = date.fromisoformat(e_str)
    dur = (e_dt - s_dt).days + 1
    
    ws.cell(row=curr_row, column=1, value=wbs_id)
    ws.cell(row=curr_row, column=2, value=name)
    ws.cell(row=curr_row, column=3, value=part)
    ws.cell(row=curr_row, column=4, value=owner)
    ws.cell(row=curr_row, column=5, value=grade)
    ws.cell(row=curr_row, column=6, value=s_str)
    ws.cell(row=curr_row, column=7, value=e_str)
    ws.cell(row=curr_row, column=8, value=dur)
    
    # 진행률 표시
    c_prog = ws.cell(row=curr_row, column=9, value=prog)
    c_prog.number_format = '0%'
    
    ws.cell(row=curr_row, column=10, value=status)
    ws.cell(row=curr_row, column=11, value=deliverable)
    ws.cell(row=curr_row, column=12, value="") # 메모
    
    # 폰트 및 배경색
    row_font = Font(name="맑은 고딕", size=9, bold=is_summary)
    
    for c_idx in range(1, 13):
        cell = ws.cell(row=curr_row, column=c_idx)
        cell.font = row_font
        cell.border = thin_border
        if is_summary:
            cell.fill = PatternFill(start_color="F2F5F9" if depth==0 else "F9FAFC", fill_type="solid")
            if depth == 0:
                cell.font = Font(name="맑은 고딕", size=9, bold=True, color="1F4E79")
        
        # 정렬
        if c_idx in [1, 3, 4, 5, 6, 7, 10]:
            cell.alignment = Alignment(horizontal="center", vertical="center")
        elif c_idx in [8, 9]:
            cell.alignment = Alignment(horizontal="right", vertical="center")
        else:
            cell.alignment = Alignment(horizontal="left", vertical="center")

    # 간트 바 그리기 (Columns 13 ~ 13 + total_days - 1)
    for idx, d in enumerate(date_list):
        col = 13 + idx
        cell = ws.cell(row=curr_row, column=col)
        cell.border = thin_border
        
        # 날짜 범위 안에 드는지 확인
        if s_dt <= d <= e_dt:
            if is_summary:
                cell.fill = fill_group
            elif owner == "김웅건":
                cell.fill = fill_kim
            elif owner == "조윤기":
                cell.fill = fill_cho
            else:
                cell.fill = fill_both
        else:
            # 주말 및 기준일 배경
            if d == date(2026, 10, 13):
                cell.fill = PatternFill(start_color="FFF2CC", fill_type="solid")
            elif d.weekday() == 5:
                cell.fill = PatternFill(start_color="F2F5F9", fill_type="solid")
            elif d.weekday() == 6:
                cell.fill = PatternFill(start_color="FDF2F0", fill_type="solid")

    curr_row += 1

# 틀 고정 (Row 9, Column 3 고정: WBS와 업무명은 보이고 날짜 스크롤 가능)
ws.freeze_panes = "C9"

output_path = r"c:\Users\admin_17\Downloads\Ai_agnet-main\Ai_agnet-main\AI인사이트_프로젝트_WBS_스케줄링.xlsx"
wb.save(output_path)
print("Successfully generated Excel WBS:", output_path)
