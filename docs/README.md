# 프로젝트 자료 안내

최신 계획서는 **[D:/ai_agent/계획3_WBS기반_개발계획.md](../계획3_WBS기반_개발계획.md)** 에 있다. 원본 WBS 119개 업무별 현재 구현·수정 파일/함수·남은 작업·검수 기준이 정리돼 있다.

## 폴더별 위치

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
