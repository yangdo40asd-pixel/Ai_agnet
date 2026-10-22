# 프로젝트 자료 안내

WBS 기준 계획은 **[계획3](../계획3_WBS기반_개발계획.md)** 에 있다. 원본 WBS 119개 업무별 구현·수정 파일/함수·남은 작업·검수 기준을 다룬다. **챗봇·캔버스의 최신 개선 방향은 [계획5](../계획5_근거기반_대화형분석_개선기획.md)의 9~14절부터 확인한다.** 대화 기록 없이도 읽을 수 있는 인수인계 기준, 전문 문체, 목표 답변 예시 13개, 전제 자료와 완료 기준을 기록했다. 13절은 검토 36항목 대응표, 14절은 보완 작업 18개의 수정 위치·검수 조건이다. 문서 반영 완료와 코드 구현 완료를 구분하며, 문서의 예시는 실제 시장 자료를 뜻하지 않는다.

2026-10-21 구현 재개 결과는 **[계획5의 15절](../계획5_근거기반_대화형분석_개선기획.md)** 에 있다. 자연어 요청·핵심 분석 채팅·명시적 캔버스·엑셀 실패 격리를 수정했고 로컬 213개 검사와 실제 API 한 종목 흐름을 확인했다. 실제 LLM 품질 편차와 브라우저 미검수는 남아 있다.

## 폴더별 위치

2026-10-22 구조 검토에 따른 [최소 리팩토링 계획은 계획5의 17절](../계획5_근거기반_대화형분석_개선기획.md)에 있다. 문제 7개별 우선순위·최소 변경·영향 범위·검증 방법을 기록했으며, 사용자 요청에 따라 계획 보강만 마쳤다. 코드 리팩토링은 미착수다.

증권앱 화면에서 참고할 UI·답변 구성은 [계획5의 16절](../계획5_근거기반_대화형분석_개선기획.md)에 계획으로 추가했다. 참조 이미지 원본은 `docs/참고자료/증권앱_UI참조/`에 보관한다. 이 추가 계획은 구현 완료를 뜻하지 않는다.

| 위치 | 내용 |
|---|---|
| 프로젝트 루트 | 최신 계획3, README, AGENTS, 실행/검사 배치, 패키지·환경 설정 |
| docs/계획 | 이전 계획2·초기 PROJECT_PLAN |
| docs/검수 | 코드/API 검수 결과·개발 기록·사용자 테스트 안내 |
| docs/참고자료 | API 용어집·패키지 참고자료 |
| docs/엑셀자료 | 프로젝트 폴더에 있던 WBS 두 파일·API 검토 엑셀 |
| docs/이전자료 | 이전 진행 보고서·로드맵·초기 할 일·복사본 |
| scripts/document_tools | 예전 Word 문서 생성 도구 |
| 검수자료 | 실제 API 검수 JSON 원자료, 기존 출력 경로 유지 |
| src / tests / scripts/verify_live.py | 기존 프로그램·자동 검사·실제 API 검수 도구 |

## 찾기 쉬운 링크

- [최신 계획3](../계획3_WBS기반_개발계획.md)
- [계획5 — 챗봇 최신 방향·답변 예시·체크 기준](../계획5_근거기반_대화형분석_개선기획.md)
- [챗봇·캔버스·답변 품질 상세 검토](../챗봇_설계와코드_문제점_상세검토.md)
- [대화형 챗봇 전용 개발 계획서](계획/챗봇_전용_개발계획.md)
- [계획4 대화형 캔버스](../계획4_대화형캔버스_작업계획.md)
- [계획4 구현·검수 결과](검수/계획4_구현_검수.md)
- [기획서·구현 결과·최종 보고서 정리 (D122~D124)](../기획서_구현결과_최종보고서_정리.md)
- [이전 계획2](계획/계획2.md)
- [기본 실제 API 검수 결과](검수/실제_API_검수결과.md)
- [코드 검수 결과](검수/코드_검수결과.md)
- [사용자 테스트 안내](검수/사용자_테스트_안내.md)
- [현재 기본 실행 안내](../README.md)

정리일: 2026-10-20. 파일을 삭제하거나 서로 다른 버전을 합치지 않고 분류해 이동했다. 프로젝트 안의 WBS는 이전 파일이며, 계획3의 기준 WBS는 본문에 링크된 바탕화면의 AI인사이트팀_WBS_조윤기,김웅건.xlsx다. 그 외부 원본은 이동/수정하지 않았다. 이전자료는 당시 기록이므로 최신 구현 상태는 계획3을 우선 확인한다.

Git에는 실행 코드·테스트·Markdown 문서·기존에 추적한 엑셀 자료를 보관한다. 아래 이동 목록의 예전 Word 출력물(`*.docx`)과 `scripts/document_tools`는 로컬에만 보존한다. 저장소를 새로 받으면 해당 파일들은 포함되지 않는다. 비밀 설정·가상환경·임시 검사 로그도 제외한다.

## 이번 파일 이동 목록

- 개발작업_기록.md → [docs/검수/개발작업_기록.md](<검수/개발작업_기록.md>)
- 사용자_테스트_안내.md → [docs/검수/사용자_테스트_안내.md](<검수/사용자_테스트_안내.md>)
- 실제_API_검수결과.md → [docs/검수/실제_API_검수결과.md](<검수/실제_API_검수결과.md>)
- 코드_검수결과.md → [docs/검수/코드_검수결과.md](<검수/코드_검수결과.md>)
- PROJECT_PLAN.md → [docs/계획/PROJECT_PLAN.md](<계획/PROJECT_PLAN.md>)
- 계획2.md → [docs/계획/계획2.md](<계획/계획2.md>)
- AI인사이트_프로젝트_WBS_스케줄링.xlsx → [docs/엑셀자료/AI인사이트_프로젝트_WBS_스케줄링.xlsx](<엑셀자료/AI인사이트_프로젝트_WBS_스케줄링.xlsx>)
- AI인사이트_프로젝트_WBS_스케줄링_수정본.xlsx → [docs/엑셀자료/AI인사이트_프로젝트_WBS_스케줄링_수정본.xlsx](<엑셀자료/AI인사이트_프로젝트_WBS_스케줄링_수정본.xlsx>)
- 주식지표_차트_엑셀_API검토.xlsx → [docs/엑셀자료/주식지표_차트_엑셀_API검토.xlsx](<엑셀자료/주식지표_차트_엑셀_API검토.xlsx>)
- AI_Insight_Report_Progress - 복사본.docx → [docs/이전자료/AI_Insight_Report_Progress - 복사본.docx](<이전자료/AI_Insight_Report_Progress - 복사본.docx>)
- AI_Insight_Report_Progress.docx → [docs/이전자료/AI_Insight_Report_Progress.docx](<이전자료/AI_Insight_Report_Progress.docx>)
- AI_Insight_Report_Progress.md → [docs/이전자료/AI_Insight_Report_Progress.md](<이전자료/AI_Insight_Report_Progress.md>)
- DEVELOPMENT_ROADMAP.md → [docs/이전자료/DEVELOPMENT_ROADMAP.md](<이전자료/DEVELOPMENT_ROADMAP.md>)
- PROGRESS_REPORT.md → [docs/이전자료/PROGRESS_REPORT.md](<이전자료/PROGRESS_REPORT.md>)
- todo_phase2.md → [docs/이전자료/todo_phase2.md](<이전자료/todo_phase2.md>)
- todo_setup.md → [docs/이전자료/todo_setup.md](<이전자료/todo_setup.md>)
- AI_Project_API_Glossary.docx → [docs/참고자료/AI_Project_API_Glossary.docx](<참고자료/AI_Project_API_Glossary.docx>)
- AI_Project_API_Glossary.md → [docs/참고자료/AI_Project_API_Glossary.md](<참고자료/AI_Project_API_Glossary.md>)
- PACKAGES.md → [docs/참고자료/PACKAGES.md](<참고자료/PACKAGES.md>)
- generate_glossary_docx.py → [scripts/document_tools/generate_glossary_docx.py](<../scripts/document_tools/generate_glossary_docx.py>)
- generate_report_docx.py → [scripts/document_tools/generate_report_docx.py](<../scripts/document_tools/generate_report_docx.py>)
