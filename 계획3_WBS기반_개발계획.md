# 계획3 — WBS 기준 현재 구현과 남은 확인 계획

갱신일: **2026-10-20** · 작업 위치: **D:\ai_agent**

기준 WBS: [AI인사이트팀_WBS_조윤기,김웅건.xlsx](<C:/Users/admin_25/Desktop/2학년2학기/노준_교수님/스케줄/1013/AI인사이트팀_WBS_조윤기,김웅건.xlsx>)의 WBS_스케줄링 시트.

아래 기존 업무 집계는 원본 **7개 대분류·32개 중분류·119개 소분류** 기준이다. 이후 사용자가 승인한 **기본 테마 분석 서비스 → 대화형 챗봇** 9개 업무를 추가 구현했다. 챗봇 범위는 기존 119개 집계와 별도로 기록하며, 엑셀 간트/Week 완료 표시는 변경하지 않았다.

## 최신 추가: 대화형 챗봇

코드 보류는 사용자의 ‘챗봇 기능 추가 기능 진행’ 요청으로 해당 범위에서 해제됐다. 구현 세부 사항과 남은 사용자 확인은 [챗봇 구현·검수 기록](<D:/ai_agent/docs/검수/챗봇_구현_검수.md>)에 정리했다.

- [x] 연속 질문과 종목 분석을 포함한 챗봇 이용 흐름 정의.
- [x] 사용자·AI 메시지와 현재 테마·종목의 대화 상태 설계.
- [x] 일반 질문·테마 분석·종목 변경의 대화 의도 구분.
- [x] 이전 대화와 선택 종목을 반영한 후속 질문 처리.
- [x] 기존 종목·금융·뉴스 조회 기능 연결.
- [x] 수집 자료와 대화 문맥을 결합한 근거 기반 답변 생성.
- [x] 사용자·AI 메시지를 누적하는 대화형 화면.
- [x] AI 종합 분석 리포트를 챗봇 대화 응답으로 표시.
- [x] 새 대화 시작 및 대화 기록·분석 문맥 초기화.
- [ ] 실제 브라우저에서 긴 대화의 가독성과 다양한 자연어 표현 확인.

`src/agents/chat.py`, `src/ui/app.py`, `src/ui/state.py` 중심으로 구현했다. 신규 챗봇 검사 21개 포함 전체 154개 자동 검사가 통과했다. 실제 AI API에는 가상 종목 자료를 주입하여 일반 용어/선택 종목/PBR 누락의 세 사례를 확인했다. 새 금융·뉴스 API 전체 검수 또는 전체 개발 완료를 뜻하지 않는다.

연계: [실행 안내](<D:/ai_agent/README.md>) · [구현·검증 정리](<D:/ai_agent/기획서_구현결과_최종보고서_정리.md>) · [자료 위치 안내](<D:/ai_agent/docs/README.md>)

## 1. 현재 상태와 완료 기준

현재 주 UI는 **대화 입력 → 의도 구분 → 테마 탐색 또는 후속 답변**이다. 테마 탐색은 **후보3개 제안/상장 대조 → 사용자 선택 → 선택 종목 수집 → 채팅 리포트·상세 대시보드 → XLSX 다운로드**로 이어진다. 첫 후보 자동 분석은 이전 호출을 위한 analyze_theme 호환 경로에 남아 있다.

- [x] 사용자 후보 선택·종목 전환·가격 범위 변경·재조회·결과 초기화가 구현됐다.
- [x] 주가/PER/PBR/ROE 카드, EPS/BPS 보조 카드, 선택 종목 OHLCV, 연간 손익·BS·CF·비율, 재무 사실 근거 AI, 8시트 네이티브 차트 XLSX가 연결됐다.
- [x] 챗봇 추가 전 자동 검사 133개가 통과했고, 챗봇 추가 후 전체 154개가 17.878초에 통과했다.
- [x] 2026-10-20 10:36~10:37 KST의 검수자료/실제_API_검수.json 기록을 재확인했다. 그 기록은 실제 외부 응답을 사용했다고 명시하며 브라우저/별도 서버는 시작하지 않았다. 이번 문서 수정에서는 실제 API를 재호출하지 않았다.
- [ ] 관련 후보 전체의 동시 가격/미니 차트: 기본 경로는 미선택 후보를 조회하지 않는다.
- [ ] 분기/반기 실제 수집과 보고서/사업연도 선택: 변환/표시 함수는 있지만 활성 수집은 최근3개 연간 중심이다.
- [ ] 공식 ROE 범위/계산 대체의 설명, 확장 실패를 포함한 전체 완료 표시, 이용조건·반복 요청 검증은 보완 확인이 필요하다.
- [ ] 실제 브라우저 가독성·Excel 열기/수정·최종 캡처·제출본·리허설·제출은 별도 확인 대기다.

### 체크가 뜻하는 것

- `[x] 구현·검사 확인`: 해당 업무의 명시된 구현과 자동 검사/실행 기록을 확인했다. 모든 회사·시간대·브라우저에서 완전 검증했다는 뜻은 아니다.
- `[ ] 부분 구현·확인 대기`: 코드 일부가 있어도 업무 범위나 실제 확인이 남아 있다. 본문에 남은 일을 적는다.
- `[ ] 미수행`: 제출/리허설 등 실행 증거가 없다.

이번 기준의 업무 체크는 **구현·검사 확인 92개 / 부분·확인 대기 24개 / 미수행 3개**다. 난이도·공수·사용자 확인을 가중하지 않은 개수이므로 개발 진행률이나 전체 완료율로 환산하지 않는다. 특히 ‘제출 제외100% 완료’로 표현하지 않는다.

### Week 기준과 현재 코드 기준

**원본 WBS의 Week1~2 스냅샷은 유지한다.** Week1은10/6~12, Week2는10/13~19이며 현재10/20 확장 기록을 그 기간 완료 내역에 소급해 넣지 않는다. 이 MD는 현재 구현 기준이고 원본 날짜/Week/간트/진행률 수정 지시가 아니다. 담당은 원본대로 김웅건(AI·프론트엔드), 조윤기(데이터·API·백엔드), 공동 기획서 작성은 공통으로 둔다.

## 2. 실제 구조와 코드 연결

```text
D:\ai_agent
├─ src/config.py               Groq/NAVER/DART 설정
├─ src/models.py               후보·조회옵션·지표·이력·재무·비율·사실·통합결과
├─ src/pipeline.py             후보 탐색 / 선택 분석 분리
├─ src/data/stock.py           상장 대조·선택 코드·주가/PER/EPS/BPS/PBR
├─ src/data/history.py         OHLCV·관련 후보 요약
├─ src/data/dart.py            기업번호·재무/지표 API·응답 상태
├─ src/data/financials.py      계정/기간/단위·연간/분기 변환·비율·fact_id
├─ src/agents/report.py        기본/재무 AI·형식/수치/근거 검사
├─ src/ui/app.py               입력·후보 선택·좌우 패널
├─ src/ui/state.py             선택/조건/결과/파일 무효화·세션 재사용
├─ src/ui/dashboard.py         지표/재무/뉴스/AI/파일 표시
├─ src/ui/charts.py             가격/실적/재무구조/미니 차트
├─ src/ui/formatting.py         원·배·주당원·%·억원·시각 포맷
├─ src/export/excel.py          8시트·셀 참조 차트·파일명·일부 원자료 대조
├─ tests                       12개 모듈·133개 검사
├─ scripts/verify_live.py       명시적 실제 API 검수
├─ 검수자료/실제_API_검수.json  최신 실제 실행 기록
└─ docs                        이전 계획·검수·참고자료·엑셀·이전자료
```

위 파일은 실제로 존재한다. 이전 계획의 ‘신규 제안/아직 없는 파일’ 설명은 폐기한다. DashboardResult는 독립 새 클래스가 아니라 **AnalysisResult 별칭**이다. FinancialData에 지표별 MetricValue가 연결되고 Statement는 news_ids/fact_ids를 구분한다.

| 기존/신규 함수 | 현재 역할 | 남은 연결 또는 해석 제한 |
|---|---|---|
| pipeline.discover_theme_candidates | 후보 제안·상장 대조·선택 대기 자료 생성 | 테마 연관성의 참/거짓 자체를 검증하지 않음 |
| stock.resolve_selected_target | 현재 후보의 code·selectable 검증 | 후보 밖 코드/미지원 시장을 거부 |
| pipeline.analyze_selected_stock | 선택 금융→가격이력→연간DART→뉴스→기본/재무AI | 사업연도/보고서 옵션의 DART 전달은 미완전 |
| history.fetch_related_stock_summaries | 선택 종목 이력 재사용, 미선택은ready | 기본 fetch_unselected=False |
| financials.collect_company_financials | 최근3개 연간11011 수집·CFS/OFS 처리 | 실제 분기 보고서 수집 경로는 미연결 |
| financials.build_quarter_comparison | 당분기/누적 의미를 구분하는 변환 함수 | 연간 자료만으로 실제 분기 차트 완성 아님 |
| financials.calculate_ratios | 이익률/부채비율·공식ROE 우선/계산 대체 | 평균자본 없음 시 기말자본 경로 존재, 공식ROE fs_div 근거 구분 필요 |
| report.generate_financial_commentary | 검증 사실id에 근거한 재무 설명 | id·부호·범위 검사와 의미 검토는 다름 |
| state.ensure_export_bundle | 같은result_id의 파일bytes 재사용 | 제공자 API 캐시와는 다른 세션 결과 재사용 |
| excel.reconcile_workbook_values | 시트·대표값·코드·수식·차트참조 자동 검사 | 모든 셀·실제 Excel 수동 편집 확인 아님 |
| models.AnalysisResult.complete | 기본금융 경고/뉴스/기본AI 중심 판단 | 이력·DART·재무AI 전체 성공과 동일하지 않음 |

## 3. 코드 작업 재개 시 확인할 순서 — 현재 보류

1. **상태·기준의 정확성:** 전체 완료 표시와 확장 section_status, 공식ROE 범위 및 평균/기말자본 계산 설명을 우선 검토한다.
2. **조회 조건 연결:** QueryOptions의 사업연도/보고서와 실제 DART 요청·표시·파일을 연결할 범위를 결정한다.
3. **분기·관련 후보 요약:** 실제 분기 수집과 차트 전달, 미선택 후보의 제한된 가격/미니차트 조회를 연결한다.
4. **검수 범위 확대:** PBR/BPS 유효 실응답, 비표준계정·정정·특수회사·모든 엑셀 데이터 대조·반복 요청을 확인한다.
5. **사용자 확인/제출:** 실제 브라우저/Excel·화면 캡처·최종 제출본·리허설·시연을 수행한다.

종목·기간 변경 시 기존 차트·뉴스·AI·파일을 같은 결과 단위로 무효화하는 구조는 유지한다. 없는 값은0이 아닌 정보 없음으로 남기고, 원/억원·소수/%·조회시각/자료시각·CFS/OFS를 섞지 않는다. UI의 연간 결과가 있다고 분기 선택까지 완성됐다고 설명하지 않는다.

## 4. WBS 중분류·소분류별 상세 상태

원본 업무명/행을 유지한다. 아래 ‘완료·검수 기준’은 해당 업무를 확인할 기준이며 아직 실행하지 않은 모든 사례까지 통과했다는 뜻은 아니다. `[ ]`에는 구체적인 잔여 범위를 함께 적었다.

### 4-1. 기획 및 기본 설계

#### 기획서 작성

담당: **공통**

- [x] **프로젝트 기획서 작성** — WBS `D9`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 공동 기획서 작성 이력이 있으며 기획·구현 설명 문서가 존재한다. 원본 제출용 HWP/PDF 갱신 완료를 뜻하지 않는다.
  - 코드·문서: [docs/계획/계획2.md](<D:/ai_agent/docs/계획/계획2.md>), [docs/계획/PROJECT_PLAN.md](<D:/ai_agent/docs/계획/PROJECT_PLAN.md>)
  - 유지·후속 확인: 제출본 반영은 D124~D127에서 별도 확인한다.
  - 완료·검수 기준: 최종 설명이 입력→후보→선택→조회→분석→다운로드와 일치한다.

#### 서비스 요구사항 정의

담당: **김웅건**

- [x] **서비스 대상 사용자 및 테마 검색 목적 정의** — WBS `D10`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 기획 문서에 관심 테마의 종목 탐색·자료 이해를 돕는 서비스 목적이 있다.
  - 코드·문서: [docs/계획/PROJECT_PLAN.md](<D:/ai_agent/docs/계획/PROJECT_PLAN.md>), [README.md](<D:/ai_agent/README.md>)
  - 유지·후속 확인: 최종 제출본에도 투자수익 보장과 정보 탐색 지원을 구분해 적는다.
  - 완료·검수 기준: 투자수익 보장이 아니라 정보 탐색과 이해의 개선으로 목적을 설명한다.

- [x] **테마 입력부터 결과 확인까지 사용자 시나리오 작성** — WBS `D11`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 테마 입력→후보 탐색→사용자 선택→상세 분석→엑셀 저장 흐름이 구현돼 있다.
  - 코드·문서: [docs/계획/계획2.md](<D:/ai_agent/docs/계획/계획2.md>), [src/pipeline.py](<D:/ai_agent/src/pipeline.py>), [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 현재 동작은 이 문서와 구현 결과 정리 문서를 기준으로 설명한다.
  - 완료·검수 기준: 선택 전 상태와 선택 실패 때의 흐름이 빠지지 않는다.

- [x] **기본 기능과 추가 기능의 개발 범위 구분** — WBS `D12`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 현재 선택형 분석과 회원/주문/실시간 호가 등 제외 범위를 문서로 구분했다.
  - 코드·문서: [docs/계획/계획2.md](<D:/ai_agent/docs/계획/계획2.md>), [README.md](<D:/ai_agent/README.md>)
  - 유지·후속 확인: 추가 범위 요청이 생기면 기존 완료 범위를 자동 확대하지 않는다.
  - 완료·검수 기준: WBS 확장 업무가 예상 화면의 어느 영역을 만드는지 연결된다.

#### 데이터 요구사항 정의

담당: **조윤기**

- [x] **주가·금융 지표·재무제표 수집 항목 정의** — WBS `D13`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: models.py에 독립 지표·가격 이력·재무제표·비율·사실 근거·관련 종목 자료형이 있다.
  - 코드·문서: [src/models.py](<D:/ai_agent/src/models.py>), [src/data/stock.py](<D:/ai_agent/src/data/stock.py>)
  - 유지·후속 확인: 자료형 존재와 모든 회사에서의 값 확보를 구분한다.
  - 완료·검수 기준: 지표별 원필드/계산식과 반환 모델이 대응된다.

- [ ] **데이터 API의 비용·화면 제공·다운로드 조건 조사** — WBS `D14`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 조회 제공자와 과거 API 검토표는 있으나 확장 화면 제공·파일 재배포 조건의 최종 확인 근거는 이번 기록만으로 충분하지 않다.
  - 코드·문서: [docs/엑셀자료/주식지표_차트_엑셀_API검토.xlsx](<D:/ai_agent/docs/엑셀자료/주식지표_차트_엑셀_API검토.xlsx>), [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [src/data/news.py](<D:/ai_agent/src/data/news.py>)
  - 남은 작업: 제공자별 비용·계정 한도·표시/다운로드 조건·확인일·공식 근거를 검토표에 확정한다.
  - 완료·검수 기준: 확인일·공식 링크·허용 범위·미확정 항목을 기록한다. 미확정 경로를 출시 경로로 확정하지 않는다.

- [ ] **데이터 조회 기간·기준일·단위·출처 항목 정의** — WBS `D15`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 지표별 단위/출처/기간, 보고서/연결 구분이 모델에 있다. 조회 옵션 전체 연결과 공식 ROE의 연결/별도 귀속은 별도 확인이 필요하다.
  - 코드·문서: [src/models.py](<D:/ai_agent/src/models.py>), [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [src/data/news.py](<D:/ai_agent/src/data/news.py>)
  - 남은 작업: 공식 제공값 메타와 자체 계산 근거를 분리하고 입력 옵션이 실제 수집 요청에 적용되는지 확인한다.
  - 완료·검수 기준: 조회 시각을 가격 기준 시각이나 실적 기준일로 대체하지 않는다.

#### 백엔드 구조·데이터 규격 설계

담당: **조윤기**

- [x] **종목·금융·뉴스 수집 모듈 구조 설계** — WBS `D16`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: history·dart·financials·export·dashboard·charts·state가 분리돼 실제 파이프라인/UI에 연결됐다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [src/data/news.py](<D:/ai_agent/src/data/news.py>), [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 중복 책임과 예외 경계는 후속 코드 검토 때 확인한다.
  - 완료·검수 기준: 차트/엑셀 작성 함수 안에서 API를 호출하지 않는다.

- [x] **데이터 수집 결과의 공통 반환 형식 설계** — WBS `D17`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 확장 자료형을 구현하고 DashboardResult는 AnalysisResult의 별칭으로 사용한다.
  - 코드·문서: [src/models.py](<D:/ai_agent/src/models.py>)
  - 유지·후속 확인: 별도 DashboardResult 클래스가 있다고 기술하지 않는다.
  - 완료·검수 기준: 기존 테스트 fixture를 이유 없이 깨뜨리지 않고 종목·기간·출처를 보존한다.

- [ ] **금융값 누락·요청 실패·종목 미확인 상태 규격 설계** — WBS `D18`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: section_status로 금융/이력/DART/뉴스/AI 상태를 보관한다. complete는 여전히 기본 금융·뉴스·AI 중심 조건이다.
  - 코드·문서: [src/models.py](<D:/ai_agent/src/models.py>), [src/pipeline.py](<D:/ai_agent/src/pipeline.py>)
  - 남은 작업: 전체 완료 메시지가 모든 확장 수집 성공을 의미하지 않도록 코드 보완 여부를 검토한다. 이번에는 코드를 변경하지 않는다.
  - 완료·검수 기준: DART 없음 때 가격·뉴스는 남고 종목 식별 실패 때는 조회를 중단한다.

#### 기본 AI 처리 구조 설계

담당: **김웅건**

- [x] **테마 기반 종목 후보 제안의 입력·출력 형식 설계** — WBS `D19`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: propose_candidates·response_format·validate_candidate_names가 후보 3개 JSON 계약을 제한한다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [src/data/stock.py](<D:/ai_agent/src/data/stock.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 세 이름·공백·중복·잘못된 JSON 검사가 유지된다.

- [x] **금융·뉴스 자료를 결합하는 기본 AI 입력 구조 설계** — WBS `D20`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 기본 금융/뉴스 입력과 별도 재무 FinancialFact 입력을 구현했다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>)
  - 유지·후속 확인: 뉴스 번호와 재무 사실id의 유효성 검사를 유지한다.
  - 완료·검수 기준: 재무 미수집 때 실적을 만들어 넣지 않고 뉴스/재무 근거를 구분한다.

- [x] **분석 리포트 구성 항목 및 근거 표시 방식 설계** — WBS `D21`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 기본 리포트와 fact_id 인용 재무 설명을 분리해 표시한다.
  - 코드·문서: [src/models.py](<D:/ai_agent/src/models.py>), [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 의미 검토 완료와 형식 검사 통과를 구분해 기록한다.
  - 완료·검수 기준: 금융 수치는 수집 원자료에서 직접 표시한다.

#### 기본 사용자 화면 설계

담당: **김웅건**

- [x] **대화형 테마 입력 영역과 결과 영역 배치 설계** — WBS `D22`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: app.main이 좌측 후보/선택·우측 대시보드로 표시한다. 채팅 입력은 페이지 하단 구성이다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 좁은 화면 가독성은 D117에서 사용자가 실제 확인한다.
  - 완료·검수 기준: 선택 전 화면을 분석 완료처럼 보이게 하지 않는다.

- [x] **관련 뉴스·AI 설명·출처 표시 영역 설계** — WBS `D23`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: dashboard에 지표·가격·재무·관련 후보·인사이트·뉴스·다운로드 렌더러가 있다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 관련 후보 모두의 시세 표시가 완료됐다고 설명하지 않는다.
  - 완료·검수 기준: 핵심 숫자가 먼저 보이면서 원문·근거 번호를 확인할 수 있다.

- [ ] **입력 대기·분석 중·결과·조회 실패 화면 상태 설계** — WBS `D24`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 선택 대기·전환·오류·부분 결과·파일 초기화 상태를 구현했고 모의 검사가 있다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>), [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>)
  - 남은 작업: 확장 영역 상태와 전체 성공 표시의 관계, 실제 실패 화면의 가독성을 확인한다.
  - 완료·검수 기준: 새 종목 제목 아래 이전 자료를 남기지 않고 실패 영역만 안내한다.

### 4-2. 기본 테마 분석 서비스

#### 상장 종목 식별·코드 연결

담당: **조윤기**

- [x] **국내 상장 종목 목록 조회 기능 구현** — WBS `D25`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: load_listing이 KRX 목록의 형식·필수 열·비어 있음을 검사한다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [tests/test_data_rules.py](<D:/ai_agent/tests/test_data_rules.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 잘못된 목록을 임의 회사 목록으로 대체하지 않는다.

- [x] **AI 후보 종목명과 공식 상장 종목명 대조 기능 구현** — WBS `D26`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: normalize_name·resolve_candidates가 정확 이름 대조와 모호한 이름 거부를 한다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [tests/test_data_rules.py](<D:/ai_agent/tests/test_data_rules.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 유사 이름 추측 연결 없이 미확인 후보는 선택 불가다.

- [x] **종목코드와 코스피·코스닥 시장 구분 기능 구현** — WBS `D27`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 종목코드·시장을 StockCandidate에 보관한다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 종목코드가 숫자로 바뀌거나 불명확한 이름이 임의 연결되지 않는다.

- [x] **시장별 금융 조회 코드 변환 기능 구현** — WBS `D28`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: yahoo_ticker가 KOSPI .KS·KOSDAQ 계열 .KQ를 구분한다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [tests/test_data_rules.py](<D:/ai_agent/tests/test_data_rules.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: code 존재뿐 아니라 ticker·reason까지 확인한다.

- [x] **상장 종목명·종목코드·시장별 조회 코드 검증** — WBS `D29`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 시장·미확인·중복·재제안 재대조 검사가 통과했다.
  - 코드·문서: [tests/test_data_rules.py](<D:/ai_agent/tests/test_data_rules.py>), [tests/test_live_regressions.py](<D:/ai_agent/tests/test_live_regressions.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 기존 정확 일치 검사를 유지하고 몰래 다음 후보로 바꾸지 않는다.

#### 기본 금융 정보 수집·값 처리

담당: **조윤기**

- [x] **대표 종목의 조회 가능한 주가 수집 기능 구현** — WBS `D30`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: fetch_financial·financial_from_info가 symbol·원화·유효 주가를 확인한다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [tests/test_data_rules.py](<D:/ai_agent/tests/test_data_rules.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 다른 회사 응답이나 원화 미확인 가격을 원화로 표시하지 않는다.

- [x] **주가 자료의 기준 시각·통화·출처 반환 기능 구현** — WBS `D31`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 조회/가격 시각과 출처, 시각 불명 안내가 있다.
  - 코드·문서: [src/models.py](<D:/ai_agent/src/models.py>), [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: currentPrice에 근거 없는 regularMarketTime을 붙이지 않는다.

- [x] **PER 조회 및 반환 기능 구현** — WBS `D32`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: trailingPE 또는 유효한 최신 TTM 희석 EPS로 계산한 PER를 반환한다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [tests/test_live_regressions.py](<D:/ai_agent/tests/test_live_regressions.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 0 EPS·미래 기간·통화 불명·오래된 기간 대체를 거부하고 음수는 안내한다.

- [x] **금융 지표 결측값과 유효하지 않은 숫자 처리 기능 구현** — WBS `D33`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: bool·NaN·무한대 제외와 누락 유지, 가격/PER 동시 없음 중단이 있다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [tests/test_data_rules.py](<D:/ai_agent/tests/test_data_rules.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 누락을 0으로 채우거나 손실 값을 임의 양수로 바꾸지 않는다.

#### 뉴스 수집·원문 정보 연결

담당: **조윤기**

- [x] **테마·대표 종목을 결합한 뉴스 검색 요청 기능 구현** — WBS `D34`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 테마 요청 문구를 정리하고 분석 종목명을 검색어에 결합한다.
  - 코드·문서: [src/data/news.py](<D:/ai_agent/src/data/news.py>), [tests/test_live_regressions.py](<D:/ai_agent/tests/test_live_regressions.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 종목 변경 뒤 이전 종목 뉴스가 남지 않는다.

- [x] **뉴스 제목의 HTML 태그·문자 표기 정제 기능 구현** — WBS `D35`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: clean_title이 HTML·엔티티·공백을 정제하고 길이를 제한한다.
  - 코드·문서: [src/data/news.py](<D:/ai_agent/src/data/news.py>), [tests/test_data_rules.py](<D:/ai_agent/tests/test_data_rules.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 원문 태그가 실행되거나 제목으로 그대로 표시되지 않는다.

- [x] **기사 링크·발행 시각·원문 사이트 수집 기능 구현** — WBS `D36`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 원문/대체 링크·발행 시각·도메인을 보관한다.
  - 코드·문서: [src/data/news.py](<D:/ai_agent/src/data/news.py>), [src/models.py](<D:/ai_agent/src/models.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 없는 링크·시각을 생성하지 않고 안전하지 않은 주소는 클릭 불가다.

- [x] **뉴스 정렬·중복 제거·수집 건수 제한 기능 구현** — WBS `D37`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 정렬 설정·중복 제거·최대3건 제한이 있다.
  - 코드·문서: [src/data/news.py](<D:/ai_agent/src/data/news.py>), [src/config.py](<D:/ai_agent/src/config.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: rerun으로 뉴스가 중복 누적되지 않는다.

- [x] **뉴스 검색 결과 없음과 일부 항목 누락 처리 기능 구현** — WBS `D38`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 뉴스 0건·실패·일부 누락을 구분한다.
  - 코드·문서: [src/data/news.py](<D:/ai_agent/src/data/news.py>), [tests/test_additional_regressions.py](<D:/ai_agent/tests/test_additional_regressions.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 뉴스 없음이 인증 실패와 다른 안내이고 가격은 보존된다.

- [x] **뉴스 제목·링크·발행 시각 정합성 검증** — WBS `D39`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 뉴스 제목·링크·시간·번호·안전 URL 검사가 있다.
  - 코드·문서: [tests/test_data_rules.py](<D:/ai_agent/tests/test_data_rules.py>), [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 현재 종목 뉴스 번호와 AI 근거가 일치한다.

#### AI 후보 제안·응답 확인

담당: **김웅건**

- [x] **사용자 테마 입력을 전달하는 후보 제안 프롬프트 작성** — WBS `D40`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 후보 프롬프트가 테마를 입력 자료로 전달한다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 사용자 입력으로 출력 형식·검증을 우회하지 않는다.

- [x] **관련 종목 후보를 지정 형식으로 반환하는 AI 호출 기능 구현** — WBS `D41`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 지원 모델 JSON Schema와 제한적 JSON 재요청이 있다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [tests/test_live_regressions.py](<D:/ai_agent/tests/test_live_regressions.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 후보 선택·차트 기간 변경이 후보 AI를 다시 호출하지 않는다.

- [x] **후보 개수·종목명 공백·중복 응답 검사 기능 구현** — WBS `D42`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 후보 수·공백·중복·JSON 중복 키를 검사한다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [src/agents/report.py](<D:/ai_agent/src/agents/report.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 잘못된 후보는 금융 조회 전 차단된다.

- [x] **여러 테마의 후보 제안 형식과 중복 처리 검증** — WBS `D43`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 모의 검사와 10월15일 실제 3개 테마 기록이 있다.
  - 코드·문서: [tests/test_data_rules.py](<D:/ai_agent/tests/test_data_rules.py>), [tests/test_live_regressions.py](<D:/ai_agent/tests/test_live_regressions.py>), [docs/검수/실제_API_검수결과.md](<D:/ai_agent/docs/검수/실제_API_검수결과.md>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 과거 성공을 모든 테마/현재 시점 보장으로 표현하지 않는다.

#### AI 분석 자료·리포트 생성

담당: **김웅건**

- [x] **확인된 종목과 금융 지표를 AI 입력 자료로 변환** — WBS `D44`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 확인 회사명·주가·PER를 AI 입력으로 만든다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 화면 종목과 AI 입력 종목이 일치한다.

- [x] **뉴스 제목과 근거 번호를 AI 입력 자료로 구성** — WBS `D45`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 뉴스 id·제목·발행 시각을 AI에 전달한다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 본문 미수집인데 본문 분석이라고 표현하지 않는다.

- [x] **누락된 지표와 수집 실패 정보를 AI 입력에 반영** — WBS `D46`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: warnings/뉴스 상태 전달과 자료 없음 추론 제한이 있다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [tests/test_report_pipeline.py](<D:/ai_agent/tests/test_report_pipeline.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 없는 재무값을 AI가 생성하지 않는다.

- [x] **뉴스 제목 기반 테마 동향 설명 생성 기능 구현** — WBS `D47`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 뉴스 근거가 있는 theme_trend를 표시한다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 뉴스 없음 때 현재 사건처럼 동향을 생성하지 않는다.

- [x] **대표 종목 금융 지표 설명 생성 기능 구현** — WBS `D48`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 기본 금융 자료의 stock_comment가 있고 새 수치 생성은 제한한다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 기본 설명 완료를 재무 분석 완료로 확대 해석하지 않는다.

- [x] **기회·위험·종합 의견의 핵심 인사이트 생성 기능 구현** — WBS `D49`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 기회·위험·종합 의견이 뉴스 근거와 연결된다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [src/models.py](<D:/ai_agent/src/models.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 투자 권유·근거 없는 단정을 계속 검사한다.

- [x] **리포트 필수 항목과 응답 형식 검사 기능 구현** — WBS `D50`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: parse_json_response·validate_report가 필수 키·타입·구조를 검사한다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [tests/test_report_pipeline.py](<D:/ai_agent/tests/test_report_pipeline.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 잘못된 JSON을 형식만 수선해 검증 없이 채택하지 않는다.

- [x] **AI 응답의 종목명·금융 수치 일치 검사 기능 구현** — WBS `D51`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 회사명과 표시 정밀도의 가격/PER를 대조한다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [tests/test_live_regressions.py](<D:/ai_agent/tests/test_live_regressions.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 불일치 설명은 버리고 검증된 수집 자료는 보존한다.

- [x] **설명에 연결된 뉴스 근거 번호 검사 기능 구현** — WBS `D52`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 존재하는 news_ids만 허용하고 중복을 검사한다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 현재 기사에 없는 번호가 근거로 보이지 않는다.

- [x] **미제공 수치·임의 링크·투자 추천 표현 검사 기능 구현** — WBS `D53`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: _comment_text가 새 숫자·URL·추천 문구를 제한한다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [tests/test_report_pipeline.py](<D:/ai_agent/tests/test_report_pipeline.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 확장을 위해 기본 숫자/추천 검사를 통째로 제거하지 않는다.

- [x] **리포트 수치·종목명·뉴스 근거 일치 검증** — WBS `D54`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 종목·수치·뉴스 근거 불일치와 원자료 보존 검사가 있다.
  - 코드·문서: [tests/test_report_pipeline.py](<D:/ai_agent/tests/test_report_pipeline.py>), [tests/test_live_regressions.py](<D:/ai_agent/tests/test_live_regressions.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 기존 회귀 검사와 새 검사가 모두 통과한다.

- [x] **자료 누락 상황의 설명 제한과 응답 처리 검증** — WBS `D55`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 뉴스/PER/AI 누락 때 제한 설명·자료 보존 검사가 있다.
  - 코드·문서: [tests/test_report_pipeline.py](<D:/ai_agent/tests/test_report_pipeline.py>), [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 하나의 확장 실패가 다른 정상 영역을 삭제하지 않는다.

#### 대화형 검색·지표 화면

담당: **김웅건**

- [x] **테마 입력창과 분석 요청 기능 구현** — WBS `D56`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 테마 제출은 discover_theme_candidates에 연결되고 상세 조회는 선택 후 실행된다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 입력 검사·선택 대기·외부 호출 경계를 유지한다.
  - 완료·검수 기준: 빈 입력·길이 초과는 외부 호출하지 않는다.

- [x] **사용자 입력 내용과 분석 진행 상태 표시 기능 구현** — WBS `D57`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 사용자 입력과 st.status 단계 안내를 표시한다. 챗봇 추가 후 chat_messages에 최근 40개 사용자/AI 메시지·리포트를 보관하고 화면에 표시한다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>), [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>)
  - 유지·후속 확인: 실제 표시되는 대화 이력의 범위를 과장하지 않는다.
  - 완료·검수 기준: 단순 rerun이 중복 요청을 만들지 않는다.

- [x] **빈 입력·재입력 안내·기존 결과 초기화 기능 구현** — WBS `D58`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 새 테마/지우기는 후보·선택·상세·오류·파일 상태를 정리한다.
  - 코드·문서: [src/pipeline.py](<D:/ai_agent/src/pipeline.py>), [src/ui/app.py](<D:/ai_agent/src/ui/app.py>), [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>)
  - 유지·후속 확인: 재조회/조건 변경과 단순 rerun의 차이를 유지한다.
  - 완료·검수 기준: 새 테마 실패 화면에 이전 테마 결과가 남지 않는다.

- [x] **관련 종목 후보와 대표 종목 정보 표시 기능 구현** — WBS `D59`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 후보 표·선택 드롭다운·관련 후보 전환 버튼이 선택 code 기준으로 연결된다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 미선택 후보의 가격/미니차트 동시 조회는 아직 기본 경로에 연결되지 않았다.
  - 완료·검수 기준: 후보2 선택 시 제목·대표 표시·전체 데이터가 바뀐다.

- [x] **주가·PER 지표 카드 표시 기능 구현** — WBS `D60`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 주가·PER·PBR·ROE 네 카드와 EPS·BPS 보조 카드를 구현했다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 카드 존재가 데이터 제공자의 모든 값 제공을 뜻하지 않는다.
  - 완료·검수 기준: 기존 두 지표의 누락/정밀도 규칙을 유지한다.

- [x] **지표별 단위·누락 상태·출처·조회 시각 표시 기능 구현** — WBS `D61`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 단위·누락·출처·시각·제공/계산 근거를 표시하며 없는 값은 정보 없음으로 남긴다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>), [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>)
  - 유지·후속 확인: 공식 ROE 제공값의 기준과 연결 재무표 범위를 동일하다고 단정하지 않는다.
  - 완료·검수 기준: 값 없음은 정보 없음이며 0원/0배가 아니다.

#### 뉴스·AI 설명 화면

담당: **김웅건**

- [x] **뉴스 제목·발행 시각·원문 이동 기능 구현** — WBS `D62`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 뉴스 제목·발행 시간·원문 이동 버튼이 있다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 없는 원문 링크나 작동하지 않는 더보기를 생성하지 않는다.

- [x] **AI 리포트 항목별 결과 표시 기능 구현** — WBS `D63`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 뉴스 기반 항목과 기업 재무 근거 설명을 dashboard.render_insights에서 표시한다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: AI 실패/근거 부족 안내를 보존한다.
  - 완료·검수 기준: 표시 이동 때문에 데이터/AI를 재호출하지 않는다.

- [x] **AI 설명과 뉴스 근거 번호 연결 표시 기능 구현** — WBS `D64`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: Statement의 news_ids/fact_ids를 구분해 현재 결과 근거를 표시한다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 의미상 타당성은 기계적인 id 존재 검사와 별도 확인한다.
  - 완료·검수 기준: 근거 이동은 현재 결과 기사/재무 항목으로 연결된다.

- [x] **부분 결과·AI 응답 실패 안내 표시 기능 구현** — WBS `D65`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: AI 설명 실패 시 검증된 다른 자료를 보존하는 경로와 영역별 상태가 있다.
  - 코드·문서: [src/pipeline.py](<D:/ai_agent/src/pipeline.py>), [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 기본 complete 표시가 확장 실패까지 검사하지 않는 제한은 D18에 남긴다.
  - 완료·검수 기준: AI 실패 때 가격·재무표·뉴스를 쓸 수 있다.

#### 데이터 오류·중단 처리

담당: **조윤기**

- [x] **필수 자료 조회 실패 시 처리 중단 기능 구현** — WBS `D66`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 종목 미확인·필수 금융 실패에서 기본 흐름을 중단한다.
  - 코드·문서: [src/pipeline.py](<D:/ai_agent/src/pipeline.py>), [src/data/stock.py](<D:/ai_agent/src/data/stock.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 미확인 종목을 조회하거나 몰래 다른 후보로 바꾸지 않는다.

- [x] **인증 실패·시간 초과·결측값 반환 결과 검증** — WBS `D67`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 기본 뉴스 인증/timeout/HTTP와 AI 인증/429·결측 검사 등이 있다.
  - 코드·문서: [src/data/news.py](<D:/ai_agent/src/data/news.py>), [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [tests/test_data_rules.py](<D:/ai_agent/tests/test_data_rules.py>), [tests/test_live_regressions.py](<D:/ai_agent/tests/test_live_regressions.py>)
  - 유지·후속 확인: 기존 검증과 동작을 유지한다. 현재 기능 연결은 위 실제 구조와 결과를 기준으로 설명한다.
  - 완료·검수 기준: 기본 검사 통과를 모든 제공자 오류 처리 완료로 주장하지 않는다.

#### 기본 서비스 연동

담당: **김웅건**

- [x] **화면의 테마 입력과 후보 제안 기능 연결** — WBS `D68`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 후보 탐색과 선택 상세 분석 경로를 분리해 UI에 연결했다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>), [src/pipeline.py](<D:/ai_agent/src/pipeline.py>)
  - 유지·후속 확인: 기존 analyze_theme은 첫 후보 호환 경로이며 주 UI 동작으로 설명하지 않는다.
  - 완료·검수 기준: 후보 선택마다 후보 AI를 재생성하지 않는다.

- [x] **수집 데이터와 AI 리포트 생성 기능 연결** — WBS `D69`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 선택 종목 수집·기본 AI·재무 AI·결과 객체·파일 생성이 연결됐다.
  - 코드·문서: [src/pipeline.py](<D:/ai_agent/src/pipeline.py>), [src/agents/report.py](<D:/ai_agent/src/agents/report.py>)
  - 유지·후속 확인: 입력 옵션/영역 상태의 보완 과제는 별도로 유지한다.
  - 완료·검수 기준: 화면·AI·엑셀이 서로 다른 종목/기간 자료를 사용하지 않는다.

- [x] **기본 테마 입력부터 리포트 표시까지 정상 흐름 검증** — WBS `D70`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 현재 선택형 AppTest와 실제 연동 기록이 있다. 최신 로컬 검사 총133개가 통과했다.
  - 코드·문서: [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>), [scripts/verify_live.py](<D:/ai_agent/scripts/verify_live.py>), [docs/검수/실제_API_검수결과.md](<D:/ai_agent/docs/검수/실제_API_검수결과.md>)
  - 유지·후속 확인: 실행된 입력/검사 범위를 모든 테마·모든 회사로 확대 해석하지 않는다.
  - 완료·검수 기준: 기본 통과를 실행하지 않은 차트·엑셀 검증으로 기록하지 않는다.

- [x] **재입력·실패 후 재시도·결과 지우기 동작 검증** — WBS `D71`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 선택 전환·실패 초기화·재조회·rerun 보존·지우기·파일 갱신 자동 검사가 있다.
  - 코드·문서: [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>)
  - 유지·후속 확인: 실제 사용자 클릭/파일 열기 확인은 별도로 남긴다.
  - 완료·검수 기준: 실패 뒤 이전 파일을 새 종목 파일로 제공하지 않는다.

### 4-3. 종목 선택 및 수집 보완

#### 확장 화면 설계

담당: **김웅건**

- [x] **관련 종목 후보 수와 사용자 분석 종목 선택 규칙 정의** — WBS `D72`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 후보3개를 공식 대조하고 selectable 후보만 사용자가 선택한다. 최초는 선택 대기다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [src/pipeline.py](<D:/ai_agent/src/pipeline.py>), [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 상장 일치와 테마 연관성 검증은 다르다는 안내를 유지한다.
  - 완료·검수 기준: 미확인 후보 사유는 표시하되 선택 불가이며 현재 후보 밖 코드는 거부된다.

- [ ] **금융 지표·재무 차트·엑셀 다운로드 화면 설계** — WBS `D73`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 좌우 화면·6지표·가격/재무·다운로드 배치는 구현됐다. 관련 후보 전체의 동시 시세/미니차트는 미연결이다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>), [src/ui/dashboard.py](<D:/ai_agent/src/ui/dashboard.py>), [src/ui/charts.py](<D:/ai_agent/src/ui/charts.py>)
  - 남은 작업: 미선택 후보 요약 조회와 실제 화면 가독성을 추가 확인한다.
  - 완료·검수 기준: 없는 자료를 가짜 그래프로 채우지 않고 선택 대기·없음·실패를 표시한다.

#### 확장 API·수집 순서 연결

담당: **조윤기**

- [x] **확장 수집 API의 실제 인증과 서비스별 응답 확인** — WBS `D74`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 2026-10-20 10:36~10:37 KST JSON에 기본/확장 외부 응답과 DART 수집 성공 기록이 있다.
  - 코드·문서: [src/config.py](<D:/ai_agent/src/config.py>), [src/data/dart.py](<D:/ai_agent/src/data/dart.py>), [src/data/history.py](<D:/ai_agent/src/data/history.py>), [scripts/verify_live.py](<D:/ai_agent/scripts/verify_live.py>)
  - 유지·후속 확인: 오늘 문서 수정에서는 실제 API를 재호출하지 않는다. 확인된 당시 입력 범위로 기록한다.
  - 완료·검수 기준: 성공·잘못된 키·미공시·제한을 구분한다. 실행하기 전 실제 확인 완료로 체크하지 않는다.

- [x] **API 인증 실패·요청 제한·시간 초과 상태 반환 기능 구현** — WBS `D75`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: DART/이력의 인증·한도·timeout·자료 없음 처리와 모의 검사를 추가했다.
  - 코드·문서: [src/models.py](<D:/ai_agent/src/models.py>), [src/config.py](<D:/ai_agent/src/config.py>), [src/data/dart.py](<D:/ai_agent/src/data/dart.py>), [src/data/history.py](<D:/ai_agent/src/data/history.py>)
  - 유지·후속 확인: 외부 장애/반복 부하에서의 완전한 복구 검증 완료로 확대하지 않는다.
  - 완료·검수 기준: DART013 자료 없음·020 제한·010/011 키 문제·HTTP 실패가 구분되고 무한 재시도하지 않는다.

- [ ] **선택 종목 식별과 금융 데이터 수집 순서 연결** — WBS `D76`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 선택 코드로 금융·이력·DART·뉴스·AI가 이어진다. DART 호출에는 fs_div만 전달되고 QueryOptions의 사업연도/보고서가 전체 연결되지는 않았다.
  - 코드·문서: [src/pipeline.py](<D:/ai_agent/src/pipeline.py>), [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [src/models.py](<D:/ai_agent/src/models.py>)
  - 남은 작업: 사업연도/보고서 옵션을 실제 수집과 표시·파일까지 연결할지 후속 코드 작업으로 결정한다.
  - 완료·검수 기준: 반환 symbol/corp_code가 선택 회사와 다르면 자료를 거부한다.

#### 분석 종목 선택·재조회

담당: **김웅건**

- [x] **상장 확인된 후보의 분석 종목 선택 기능 구현** — WBS `D77`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: resolve_selected_target·discover_theme_candidates·analyze_selected_stock 및 선택 UI가 구현됐고 선택/전환 검사가 통과했다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [src/pipeline.py](<D:/ai_agent/src/pipeline.py>), [src/ui/app.py](<D:/ai_agent/src/ui/app.py>), [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>)
  - 유지·후속 확인: 현재 후보 밖 코드/미확인 시장 거부 규칙을 유지한다.
  - 완료·검수 기준: 후보1/2/3의 제목·ticker·뉴스 종목·AI 입력·엑셀 종목이 각각 일치한다.

- [x] **종목 변경·재요청 시 이전 결과 초기화 상태 연결** — WBS `D78`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: state 모듈이 종목/조건/재조회 변경 시 상세·AI·오류·파일을 무효화하고 동일 결과 rerun을 보존한다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>), [src/ui/state.py](<D:/ai_agent/src/ui/state.py>), [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>)
  - 유지·후속 확인: 세션 내 결과 재사용과 제공자 데이터 캐시를 구분한다.
  - 완료·검수 기준: A→B 성공/실패·같은 종목 재조회·새 테마·지우기를 구분 검사한다.

### 4-4. 금융 지표·가격 이력 확장

#### 추가 금융 지표 수집

담당: **조윤기**

- [x] **EPS 조회 및 반환 기능 구현** — WBS `D79`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: EPS를 독립 MetricValue로 수집하고 PER 보완용 EPS와 메타를 구분한다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [src/models.py](<D:/ai_agent/src/models.py>), [tests/test_live_regressions.py](<D:/ai_agent/tests/test_live_regressions.py>)
  - 유지·후속 확인: 제공 필드/기준 기간 누락 시 누락으로 유지한다.
  - 완료·검수 기준: PER가 있어도 EPS를 반환한다. 0/음수/누락을 구분하고 PER 보완 EPS와 의미가 다르면 분리한다.

- [x] **BPS 조회 및 반환 기능 구현** — WBS `D80`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: BPS 파싱·반환·카드·파일 처리가 있다. 현재 실제 검수 사례에서는 미제공 값도 있다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [src/models.py](<D:/ai_agent/src/models.py>)
  - 유지·후속 확인: 코드 구현과 실제 제공값 확보를 구분하고 임의 값을 채우지 않는다.
  - 완료·검수 기준: 주당 원·기준 기간·원필드가 남고 미확인 자본/주식수로 추정하지 않는다.

- [x] **PBR 조회 및 반환 기능 구현** — WBS `D81`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: PBR 파싱·반환 및 조건부 가격/BPS 계산 경로가 활성 코드에 있다. 실제 검수의 일부 종목은 정보 없음이다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [src/models.py](<D:/ai_agent/src/models.py>), [poc_archive/poc_scraper.py](<D:/ai_agent/poc_archive/poc_scraper.py>)
  - 유지·후속 확인: PoC 기능으로 설명하지 않고 현재 src 구현과 계산 근거를 기준으로 설명한다.
  - 완료·검수 기준: 결측을 0배로 만들지 않고 출처·기간을 보존한다. 아카이브 복사만으로 완료 처리하지 않는다.

- [ ] **주가·금융 지표와 제공 원자료의 값 대조** — WBS `D82`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 기본 수치와 확장 파싱 자동 검사가 있다. 실제 검수 JSON에는 PBR/BPS가 없는 사례가 기록됐다.
  - 코드·문서: [src/data/stock.py](<D:/ai_agent/src/data/stock.py>), [tests/test_data_rules.py](<D:/ai_agent/tests/test_data_rules.py>), [scripts/verify_live.py](<D:/ai_agent/scripts/verify_live.py>)
  - 남은 작업: 유효한 PBR/BPS가 제공된 실제 사례를 확보해 단위·기간·원필드까지 대조한다.
  - 완료·검수 기준: 종목·단위·기간·반올림을 구분하고 화면 포맷이 원자료를 바꾸지 않는다.

#### 주가·거래량 이력 수집

담당: **조윤기**

- [x] **이용 허용 범위 내 일별 주가·거래량 이력 수집 기능 구현** — WBS `D83`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 일별 OHLCV·시간대·통화·거래일·가격 조정 기준 정규화와 검사, 실제62개 가격행 기록이 있다.
  - 코드·문서: [src/data/history.py](<D:/ai_agent/src/data/history.py>), [src/models.py](<D:/ai_agent/src/models.py>), [tests/test_history.py](<D:/ai_agent/tests/test_history.py>)
  - 유지·후속 확인: 휴장일/다른 기간/다른 종목 사례는 실제 확인 범위를 구분한다.
  - 완료·검수 기준: 거래일 오름차순·통화·거래량·빈 기간·가격조정 기준을 검사하고 휴장일을 가짜 거래로 채우지 않는다.

#### 추가 지표·가격 차트 화면

담당: **김웅건**

- [x] **PBR·EPS·BPS 추가 지표 카드 표시 기능 구현** — WBS `D84`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 독립 EPS/BPS/PBR 카드·ROE 카드·누락 표시·포맷이 구현됐다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>), [src/ui/dashboard.py](<D:/ai_agent/src/ui/dashboard.py>)
  - 유지·후속 확인: 값 미제공은 카드가 존재해도 정보 없음으로 남긴다.
  - 완료·검수 기준: ROE 없으면 정보 없음이고 서로 다른 실적 기간을 같은 날짜 값처럼 합치지 않는다.

- [x] **이용 허용 범위 내 주가·거래량 차트 표시 기능 구현** — WBS `D85`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 선택 종목의 가격 선/거래량 막대 Plotly 차트가 실제 연결됐다.
  - 코드·문서: [src/ui/charts.py](<D:/ai_agent/src/ui/charts.py>), [src/ui/dashboard.py](<D:/ai_agent/src/ui/dashboard.py>), [requirements-core.txt](<D:/ai_agent/requirements-core.txt>)
  - 유지·후속 확인: 미선택 후보 전체 미니 차트와 동일 완료 범위로 묶지 않는다.
  - 완료·검수 기준: 원/주 축이 혼동되지 않고 선택 종목·범위·차트 원자료가 일치한다.

### 4-5. 기업 재무 분석 확장

#### DART 종목·보고서 연결

담당: **조윤기**

- [x] **상장 종목코드와 DART 기업 고유번호 연결 기능 구현** — WBS `D86`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: corpCode.xml 처리·stock_code→corp_code 매핑과 선행0/중복 검사 및 실제 연동 기록이 있다.
  - 코드·문서: [src/data/dart.py](<D:/ai_agent/src/data/dart.py>), [src/models.py](<D:/ai_agent/src/models.py>), [src/config.py](<D:/ai_agent/src/config.py>)
  - 유지·후속 확인: 이름 유사도 추측 연결을 하지 않는다.
  - 완료·검수 기준: 문자열 선행0 보존·매핑 없음·중복·잘못된 XML을 처리하고 이름 추측 연결을 하지 않는다.

- [ ] **연간·분기·누적 및 연결·별도 재무제표 구분 기능 구현** — WBS `D87`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 보고서/연결 구분 모델·요청 함수·분기 변환 함수는 있다. 활성 수집은 최근3개 연간 11011 중심이다.
  - 코드·문서: [src/data/dart.py](<D:/ai_agent/src/data/dart.py>), [src/models.py](<D:/ai_agent/src/models.py>)
  - 남은 작업: 분기/반기 실제 수집, 기간 선택, UI 옵션 적용까지 연결하고 실제 응답을 확인한다.
  - 완료·검수 기준: 당분기·누적·기말 잔액을 구분하고 미공시 당해 연간 보고서를 가정하지 않는다.

#### 재무제표 수집·표준화

담당: **조윤기**

- [x] **OpenDART 매출액·영업이익·순이익 수집 기능 구현** — WBS `D88`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 손익계정 매핑·매출/영업이익/순이익 정규화·연간 수집/표시 경로가 있다.
  - 코드·문서: [src/data/dart.py](<D:/ai_agent/src/data/dart.py>), [src/data/financials.py](<D:/ai_agent/src/data/financials.py>), [src/models.py](<D:/ai_agent/src/models.py>)
  - 유지·후속 확인: 계정 이름이 다른 회사는 추가 검증하며 모든 회사 완전 지원을 보장하지 않는다.
  - 완료·검수 기준: 전체/지배기업 순이익을 구분하고 중복 IS/CIS 계정을 합산하지 않는다.

- [x] **자산·부채·자본 수집 기능 구현** — WBS `D89`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 자산·부채·자본의 BS 수집/정규화/표시를 구현했다.
  - 코드·문서: [src/data/dart.py](<D:/ai_agent/src/data/dart.py>), [src/data/financials.py](<D:/ai_agent/src/data/financials.py>)
  - 유지·후속 확인: 기말 잔액과 누적 금액을 구분하고 원값 정밀도를 보존한다.
  - 완료·검수 기준: 기말 잔액에 분기 누적 차감을 하지 않고 누락을 0으로 채우지 않는다.

- [x] **영업·투자·재무활동 현금흐름 수집 기능 구현** — WBS `D90`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 영업/투자/재무 CF 수집/정규화/표시를 구현했다.
  - 코드·문서: [src/data/dart.py](<D:/ai_agent/src/data/dart.py>), [src/data/financials.py](<D:/ai_agent/src/data/financials.py>)
  - 유지·후속 확인: 음수를 오류나 단순 적자로 해석하지 않는다.
  - 완료·검수 기준: 유출 부호를 보존하고 투자 현금흐름 음수를 오류나 적자로 임의 해석하지 않는다.

- [x] **재무제표 금액·기간·계정·출처 표준화 기능 구현** — WBS `D91`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 정수/Decimal 금액·계정·보고서·범위·출처 메타를 보관하고 표시 때 억원으로 변환한다.
  - 코드·문서: [src/data/financials.py](<D:/ai_agent/src/data/financials.py>), [src/models.py](<D:/ai_agent/src/models.py>)
  - 유지·후속 확인: 표·차트·파일에서 이중 변환을 하지 않는다.
  - 완료·검수 기준: 쉼표·음수·공백·누락을 정확히 처리하고 억원 변환은 표시 때 한 번만 한다.

#### 재무 지표·비교 자료

담당: **조윤기**

- [x] **영업이익률·순이익률 계산 및 반환 기능 구현** — WBS `D92`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 같은 기간의 이익/매출로 이익률을 계산하며 매출0/누락 처리가 있다.
  - 코드·문서: [src/data/financials.py](<D:/ai_agent/src/data/financials.py>), [tests/test_financials.py](<D:/ai_agent/tests/test_financials.py>)
  - 유지·후속 확인: 원자료와 계산값을 구분한다.
  - 완료·검수 기준: 매출0/누락은 계산 불가, 음수 이익률은 유지하고 기간 혼합을 거부한다.

- [x] **부채비율 계산 및 반환 기능 구현** — WBS `D93`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 부채/자본 계산과 자본0·음수의 해석 불가 처리가 있다.
  - 코드·문서: [src/data/financials.py](<D:/ai_agent/src/data/financials.py>), [tests/test_financials.py](<D:/ai_agent/tests/test_financials.py>)
  - 유지·후속 확인: 자본잠식을 정상 낮은 비율로 표시하지 않는다.
  - 완료·검수 기준: 자본잠식을 낮은 정상 비율로 오인시키지 않고 근거 계정으로 추적 가능하다.

- [ ] **OpenDART ROE·수익성 지표 조회 및 반환 기능 구현** — WBS `D94`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 공식 ROE 우선 수집과 직접 계산 대체가 있다. 전기 자본 없음 시 기말 자본만으로 계산하는 경로도 존재한다.
  - 코드·문서: [src/data/dart.py](<D:/ai_agent/src/data/dart.py>), [src/data/financials.py](<D:/ai_agent/src/data/financials.py>), [src/models.py](<D:/ai_agent/src/models.py>)
  - 남은 작업: 평균자본 방식과 기말자본 대체를 구분하고, 공식 API에 fs_div 인자가 없는 한계를 메타에 반영할지 검토한다.
  - 완료·검수 기준: 제공/계산을 구분하고 비율에 100을 중복 적용하거나 분기/연간을 섞지 않는다.

- [x] **연도별 손익·재무구조 비교 자료 구성 기능 구현** — WBS `D95`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 최근3개 연간 비교 자료를 동일 범위 중심으로 구성하며 CFS 없음 때 OFS 전환 경로가 있다.
  - 코드·문서: [src/data/financials.py](<D:/ai_agent/src/data/financials.py>)
  - 유지·후속 확인: 3~5개년 가변 선택 전체 구현이라고 쓰지 않는다.
  - 완료·검수 기준: 없는 연도를 보간하지 않고 범위 변경은 별도 계열/비교 불가로 처리한다.

- [ ] **재무제표 기간·구분·금액 단위 정합성 검증** — WBS `D96`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 재무 기간/구분/금액과 계산의 모의 검사가 있다. 분기 변환은 fixture로 검사하지만 실제 분기 전체 연결은 없다.
  - 코드·문서: [tests/test_dart.py](<D:/ai_agent/tests/test_dart.py>), [tests/test_financials.py](<D:/ai_agent/tests/test_financials.py>), [scripts/verify_live.py](<D:/ai_agent/scripts/verify_live.py>)
  - 남은 작업: 실제 분기·정정·비표준계정·공식비율 범위 대조를 추가하고 검사 수준을 나눠 기록한다.
  - 완료·검수 기준: 잘못된 차감·중복 계정 합산·단위 이중 변환을 잡아낸다.

#### 재무 기반 AI 설명

담당: **김웅건**

- [x] **재무제표 항목과 조회 기간을 AI 입력 자료로 변환** — WBS `D97`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: build_financial_facts가 실제 재무 항목·기간·값·근거를 AI 입력으로 구성한다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [src/models.py](<D:/ai_agent/src/models.py>), [src/pipeline.py](<D:/ai_agent/src/pipeline.py>)
  - 유지·후속 확인: 전체 원문/키를 전송하지 않고 필요한 정규화 사실만 전달한다.
  - 완료·검수 기준: 입력 크기를 제한하고 키·헤더·외부 원문 전체를 보내지 않는다.

- [x] **대표 종목 재무제표 설명 생성 기능 구현** — WBS `D98`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: generate_financial_commentary·validate_financial_commentary가 사실id 기반 별도 설명을 생성·검사한다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [src/models.py](<D:/ai_agent/src/models.py>)
  - 유지·후속 확인: 기본 숫자 검사를 유지하고 현재 결과의 사실id만 허용한다.
  - 완료·검수 기준: 기본 숫자 검사를 없애지 않고 다른 회사·기간·없는 사실의 설명을 거부한다.

- [ ] **확장 금융·재무 자료에 근거한 AI 설명 내용 검토** — WBS `D99`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 사실id·부호·범위·증감 관련 구조 검사와 실제 설명 기록이 있다.
  - 코드·문서: [tests/test_financial_commentary.py](<D:/ai_agent/tests/test_financial_commentary.py>), [src/agents/report.py](<D:/ai_agent/src/agents/report.py>)
  - 남은 작업: 전문가/사용자에 의한 의미·문맥·회계기간 적절성 검토는 별도 완료 확인한다.
  - 완료·검수 기준: 형식 통과와 의미 검토를 구분한다. 음수 PER·자본잠식·기간 누락을 포함한다.

#### 재무 표·차트 화면

담당: **김웅건**

- [x] **손익·재무상태·현금흐름 자료의 표 표시 기능 구현** — WBS `D100`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 연간 실적 요약과 상세 BS/CF 표, 비율·원문 링크가 구현됐다.
  - 코드·문서: [src/ui/dashboard.py](<D:/ai_agent/src/ui/dashboard.py>), [src/ui/formatting.py](<D:/ai_agent/src/ui/formatting.py>)
  - 유지·후속 확인: 실제 캡처와 좁은 화면 확인은 D117/D123에서 다룬다.
  - 완료·검수 기준: 전기/당기만 쓰지 않고 실제 연도·기간·범위·단위를 보인다.

- [ ] **연도별 매출액·영업이익·순이익 차트 표시 기능 구현** — WBS `D101`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 연간 실적 차트가 연결됐고 분기 차트/정규화 함수는 있다. 활성 수집은 연간 보고서만 전달한다.
  - 코드·문서: [src/ui/charts.py](<D:/ai_agent/src/ui/charts.py>), [src/data/financials.py](<D:/ai_agent/src/data/financials.py>)
  - 남은 작업: 당분기 보고서를 실제 수집/전달해 분기 차트를 끝까지 검증한다.
  - 완료·검수 기준: 반기/3분기 누적을 단독 2분기/3분기로 잘못 표시하지 않는다.

- [x] **연도별 자산·부채·자본 비교 차트 표시 기능 구현** — WBS `D102`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 자산·부채·자본 비교 차트와 음수 자본/단위 처리의 자동 검사가 있다.
  - 코드·문서: [src/ui/charts.py](<D:/ai_agent/src/ui/charts.py>)
  - 유지·후속 확인: 음수/누락 실제 회사 사례는 추가 확인 범위를 기록한다.
  - 완료·검수 기준: 음수 자본 표시 가능하며 계정 중복으로 합계가 왜곡되지 않는다.

- [ ] **ROE·이익률·부채비율 표시 기능 구현** — WBS `D103`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: ROE·이익률·부채비율·산출 구분 표시는 있다. 공식 ROE와 재무표 연결 범위가 같다고 확정할 근거는 제한적이다.
  - 코드·문서: [src/ui/dashboard.py](<D:/ai_agent/src/ui/dashboard.py>), [src/ui/formatting.py](<D:/ai_agent/src/ui/formatting.py>)
  - 남은 작업: ROE 제공/직접계산과 기준·평균/기말자본 차이를 일관되게 표시한다.
  - 완료·검수 기준: %·기간·제공/계산·해석 불가 사유를 확인할 수 있다.

- [ ] **차트의 기간·단위·출처 표시 기능 구현** — WBS `D104`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 가격/연간 재무 차트의 기간·단위·출처가 연결됐다. 분기 실제 요청 연결과 공식지표 범위는 확인이 남았다.
  - 코드·문서: [src/ui/charts.py](<D:/ai_agent/src/ui/charts.py>), [src/ui/dashboard.py](<D:/ai_agent/src/ui/dashboard.py>)
  - 남은 작업: 미연결 기간을 차트 제목만 바꿔 표시하지 않고 메타 대조를 추가한다.
  - 완료·검수 기준: 연도·분기·단위·CFS/OFS가 틀리면 차트 완료로 인정하지 않는다.

### 4-6. 엑셀 자료 제공·서비스 통합

#### 통합 자료·엑셀 생성

담당: **조윤기**

- [x] **재무제표·재무지표·뉴스 수집 결과 통합 반환 기능 구현** — WBS `D105`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: AnalysisResult에 지표·이력·재무·비율·뉴스·AI를 통합하고 DashboardResult는 그 별칭이다.
  - 코드·문서: [src/models.py](<D:/ai_agent/src/models.py>), [src/pipeline.py](<D:/ai_agent/src/pipeline.py>)
  - 유지·후속 확인: 화면/엑셀은 같은 결과 객체를 사용한다.
  - 완료·검수 기준: 화면/엑셀이 같은 객체를 받고 별도 재조회로 값이 갈라지지 않는다.

- [x] **선택 종목의 지표·재무제표·출처 시트 구성 기능 구현** — WBS `D106`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 요약·핵심지표·일별시세·손익·BS·CF·뉴스·출처및산식 8시트 생성이 있다.
  - 코드·문서: [src/export/__init__.py](<D:/ai_agent/src/export/__init__.py>), [src/export/excel.py](<D:/ai_agent/src/export/excel.py>)
  - 유지·후속 확인: 누락·문자열 코드·출처·단위 보존 규칙을 유지한다.
  - 완료·검수 기준: 코드 선행0·숫자 타입·원값·단위·출처 보존, 키/내부 예외 비노출을 확인한다.

- [x] **수치 변경이 반영되는 엑셀 차트 생성 기능 구현** — WBS `D107`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 셀 참조 네이티브 차트를 생성하고 실제 검수 파일 메타에5개 차트가 기록됐다.
  - 코드·문서: [src/export/excel.py](<D:/ai_agent/src/export/excel.py>), [requirements-core.txt](<D:/ai_agent/requirements-core.txt>)
  - 유지·후속 확인: Excel에서 셀을 바꿨을 때 차트가 갱신되는 사용자 확인은 D110에서 별도 수행한다.
  - 완료·검수 기준: 이미지로 대체하지 않고 셀 변경 후 Excel 차트 갱신을 별도 확인한다.

- [x] **다운로드용 XLSX 파일·파일명 생성 기능 구현** — WBS `D108`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 메모리 XLSX bytes·파일명 생성이 구현됐고 종목 전환 파일 기록이 있다.
  - 코드·문서: [src/export/excel.py](<D:/ai_agent/src/export/excel.py>), [src/models.py](<D:/ai_agent/src/models.py>)
  - 유지·후속 확인: 공용 고정 경로를 덮어쓰지 않고 동일 결과 파일을 재사용한다.
  - 완료·검수 기준: 유효 XLSX bytes이며 공용 고정 경로 파일을 덮어쓰지 않는다.

- [ ] **엑셀 수치·종목·기간·출처의 원자료 대조 검증** — WBS `D109`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: reconcile_workbook_values와 자동 검사로 시트·종목코드·가격/PER·일부 대표값·차트 참조를 확인한다.
  - 코드·문서: [tests/test_excel_export.py](<D:/ai_agent/tests/test_excel_export.py>)
  - 남은 작업: 모든 재무/뉴스/메타 값을 원자료와 전수 대조한 것으로 표현하지 않고 누락된 대조 범위를 추가한다.
  - 완료·검수 기준: 원/억원·소수/% 변환이 중복되지 않고 0과 누락을 구분한다.

- [ ] **엑셀 파일 열기·차트 편집·누락 자료 표시 검증** — WBS `D110`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: OOXML/셀/차트 참조/문자열 안전 자동 검사는 통과했다. 실제 Excel 열기·셀 수정·차트 편집 확인은 없다.
  - 코드·문서: [tests/test_excel_export.py](<D:/ai_agent/tests/test_excel_export.py>), [src/export/excel.py](<D:/ai_agent/src/export/excel.py>)
  - 남은 작업: 사용자가 Excel에서 열고 수정/저장/차트 갱신을 확인한 뒤 수동 확인 완료를 기록한다.
  - 완료·검수 기준: 뉴스/테마가 = 등으로 시작해도 의도치 않은 수식이 되지 않는다. 자동 검사만으로 실제 Excel 확인 완료라 적지 않는다.

#### 엑셀 다운로드 화면

담당: **김웅건**

- [x] **선택 종목 엑셀 다운로드 버튼 구현** — WBS `D111`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: st.download_button에 현재 결과 bytes·파일명·MIME을 연결했다.
  - 코드·문서: [src/ui/dashboard.py](<D:/ai_agent/src/ui/dashboard.py>), [src/ui/app.py](<D:/ai_agent/src/ui/app.py>)
  - 유지·후속 확인: 클릭 때문에 외부 자료를 재조회하지 않는다.
  - 완료·검수 기준: 다운로드 클릭이 금융·AI API를 다시 호출하지 않는다.

- [x] **다운로드 파일명·종목·조회 기간 안내 표시 기능 구현** — WBS `D112`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 다운로드 대상 코드·가격 범위·생성 시각·파일명 표시가 있다.
  - 코드·문서: [src/ui/dashboard.py](<D:/ai_agent/src/ui/dashboard.py>), [src/export/excel.py](<D:/ai_agent/src/export/excel.py>)
  - 유지·후속 확인: 사업연도/보고서 가변 옵션이 연결된 것으로 확대 설명하지 않는다.
  - 완료·검수 기준: 화면 안내·파일명·파일 내부 메타가 일치한다.

- [x] **종목 재선택·재조회 시 다운로드 자료 갱신 기능 구현** — WBS `D113`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: result_id에 따라 bytes/파일명을 재사용/무효화하는 상태 코드와 종목 전환 검사가 있다.
  - 코드·문서: [src/ui/state.py](<D:/ai_agent/src/ui/state.py>), [src/ui/app.py](<D:/ai_agent/src/ui/app.py>), [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>)
  - 유지·후속 확인: 종목·범위·재조회 변경 뒤 파일 식별 일치를 유지한다.
  - 완료·검수 기준: A 파일을 B 화면에서 내려받지 않고 같은 결과 rerun은 재생성하지 않는다.

#### 확장 결과 화면 연결

담당: **김웅건**

- [ ] **분석 결과와 지표·차트·엑셀 다운로드 화면 연결** — WBS `D114`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 지표·연간 재무·가격·뉴스·AI·파일은 동일 결과로 연결됐다. 분기 실제 연결/미선택 후보 요약·확장 완료 판단은 남았다.
  - 코드·문서: [src/pipeline.py](<D:/ai_agent/src/pipeline.py>), [src/ui/app.py](<D:/ai_agent/src/ui/app.py>), [src/ui/dashboard.py](<D:/ai_agent/src/ui/dashboard.py>)
  - 남은 작업: 그 미연결 부분은 후속 코드 작업으로 검토하며 문서에서는 부분 구현으로 둔다.
  - 완료·검수 기준: 뉴스·DART·이력·AI의 개별 실패가 서로 다른 정상 영역을 숨기지 않는다.

- [ ] **확장 지표·재무제표·차트·다운로드 화면 표시 검증** — WBS `D115`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 선택형 화면/지표/연간 재무/파일의133개 검사와 실제 사례 기록이 있다.
  - 코드·문서: [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>), [tests/test_dashboard.py](<D:/ai_agent/tests/test_dashboard.py>)
  - 남은 작업: 분기·공식ROE 범위·미선택 요약·특수 회사 사례는 실제 경로 확인을 추가한다.
  - 완료·검수 기준: 위젯 개수만 세지 않고 종목·값·단위·출처를 대조한다.

- [x] **종목 변경 후 차트·다운로드 파일 결과 일치 검증** — WBS `D116`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 후보 전환 모의 검사와 삼성전자→SK하이닉스 실제 전환/파일 교체 기록이 있다.
  - 코드·문서: [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>), [tests/test_excel_export.py](<D:/ai_agent/tests/test_excel_export.py>)
  - 유지·후속 확인: 검증한 사례를 모든 후보·모든 기간 전환으로 확대하지 않는다.
  - 완료·검수 기준: 카드·series·AI근거·뉴스·파일명·XLSX 내부 코드가 같은 선택을 가리킨다.

- [ ] **화면 가독성과 분석 대기 안내 검토** — WBS `D117`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: AppTest로 위젯/자료 상태를 검사했다. 실제 브라우저의 폭·잘림·스크롤·시각적 가독성은 미확인이다.
  - 코드·문서: [src/ui/app.py](<D:/ai_agent/src/ui/app.py>), [tests/test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>), [docs/검수/사용자_테스트_안내.md](<D:/ai_agent/docs/검수/사용자_테스트_안내.md>)
  - 남은 작업: 사용자가 실제 실행 화면을 확인하고 결과를 남긴다.
  - 완료·검수 기준: 차트/표 잘림을 확인하고 코드 검사와 시각 확인을 따로 기록한다.

### 4-7. 서비스 정리·제출 준비

#### 수집 안정성·실행 문서

담당: **조윤기**

- [ ] **데이터 수집 구간의 응답 시간 측정** — WBS `D118`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: financial/history/dart/news/commentary/financial_commentary 구간과 후보 탐색 화면 경과시간을 기록한다.
  - 코드·문서: [src/pipeline.py](<D:/ai_agent/src/pipeline.py>), [scripts/verify_live.py](<D:/ai_agent/scripts/verify_live.py>), [docs/검수/실제_API_검수결과.md](<D:/ai_agent/docs/검수/실제_API_검수결과.md>)
  - 남은 작업: 목록 단독·엑셀 생성 시간·캐시 적중률까지 별도 측정한 것은 아니므로 필요 범위를 추가한다.
  - 완료·검수 기준: 키 없이 소요시간·상태·건수를 남기고 총시간을 데이터 수집 시간이라 부르지 않는다.

- [ ] **반복 요청 시 실패·제한·누락 발생 여부 확인** — WBS `D119`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 기존429 모의/실제 이력, rerun 보존과 선택 전환 검사 기록은 있다.
  - 코드·문서: [src/agents/report.py](<D:/ai_agent/src/agents/report.py>), [tests/test_live_regressions.py](<D:/ai_agent/tests/test_live_regressions.py>), [scripts/verify_live.py](<D:/ai_agent/scripts/verify_live.py>)
  - 남은 작업: 반복/동시 요청·복구·서비스 한도·장시간 안정성 시험을 별도로 수행한다.
  - 완료·검수 기준: 무한 재시도가 없고 오류/부분 결과가 영구 정상 캐시가 되지 않는다.

- [ ] **사용 API와 데이터 항목·출처 설명서 작성** — WBS `D120`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 핵심 패키지·제공자·필드 설명은 코드/문서에 있다. 비용/표시/재배포 조건 최종 표는 미확정이다.
  - 코드·문서: [README.md](<D:/ai_agent/README.md>), [docs/검수/실제_API_검수결과.md](<D:/ai_agent/docs/검수/실제_API_검수결과.md>), [src/config.py](<D:/ai_agent/src/config.py>)
  - 남은 작업: 실사용 API만 남겨 조건·확인일·근거를 확정하고 버전 표를 실제 설치값 기준으로 관리한다.
  - 완료·검수 기준: 미사용 후보 API·아카이브 예시를 현재 사용 API로 적지 않는다.

- [x] **데이터 수집 및 외부 연동 검증 결과표 작성** — WBS `D121`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 실제_API_검수.json과 이번 결과 정리 문서에 입력·일시·선택·시각·구간·파일 메타를 기록했다.
  - 코드·문서: [docs/검수/실제_API_검수결과.md](<D:/ai_agent/docs/검수/실제_API_검수결과.md>), [검수자료/실제_API_검수.json](<D:/ai_agent/검수자료/실제_API_검수.json>), [scripts/verify_live.py](<D:/ai_agent/scripts/verify_live.py>)
  - 유지·후속 확인: 기존 검수 MD의 역사 기록은 참조 자료이며 최신 판단은 JSON과 수정된3문서를 우선한다.
  - 완료·검수 기준: 과거 기록을 현재 검증으로 오인시키지 않고 성공/부분/실패/미실행을 구분한다.

#### 기획서·구현 결과 정리

담당: **김웅건**

- [x] **서비스 흐름도·아키텍처·화면 설계도 정리** — WBS `D122`
  - 판단: **구현·검사 확인(아래 범위)**
  - 현재 근거: 이 문서와 구현 결과 정리 문서에서 실제 경로·모듈·외부 제공자·화면 구성도를 갱신했다.
  - 코드·문서: [docs/계획/PROJECT_PLAN.md](<D:/ai_agent/docs/계획/PROJECT_PLAN.md>), [README.md](<D:/ai_agent/README.md>), [기획서_구현결과_최종보고서_정리.md](<D:/ai_agent/기획서_구현결과_최종보고서_정리.md>)
  - 유지·후속 확인: 도식은 실제 화면 캡처와 구분하고 분기/후보 요약 제한을 반영한다.
  - 완료·검수 기준: 미구현은 계획으로 표시하고 삭제 요청한 파일경로/DB 여부 설명을 다시 넣지 않는다.

- [ ] **실제 구현 화면과 기능 설명 작성** — WBS `D123`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 구현 기능 설명과 실제 API 기록은 있다. 사용자가 실제 브라우저에서 얻은 최종 화면 캡처는 없다.
  - 코드·문서: [README.md](<D:/ai_agent/README.md>), [docs/검수/사용자_테스트_안내.md](<D:/ai_agent/docs/검수/사용자_테스트_안내.md>), [기획서_구현결과_최종보고서_정리.md](<D:/ai_agent/기획서_구현결과_최종보고서_정리.md>)
  - 남은 작업: 실제 캡처·입력·선택 코드·조회일과 예상 이미지의 구분을 추가한다.
  - 완료·검수 기준: 실제/예시 수치·캡처 날짜·선택 종목·단위가 구분된다.

- [ ] **WBS·참고 자료·검증 결과를 최종 보고서에 반영** — WBS `D124`
  - 판단: **부분 구현·확인 대기**
  - 현재 근거: 현재3개 MD를 일치시키는 보고서 반영 초안을 작성했다. 최종 HWP/PDF 제출본의 편집/검토까지 끝난 것은 아니다.
  - 코드·문서: [docs/계획/PROJECT_PLAN.md](<D:/ai_agent/docs/계획/PROJECT_PLAN.md>), [docs/검수/실제_API_검수결과.md](<D:/ai_agent/docs/검수/실제_API_검수결과.md>), [기획서_구현결과_최종보고서_정리.md](<D:/ai_agent/기획서_구현결과_최종보고서_정리.md>)
  - 남은 작업: 최종 양식에 반영하고 표/그림/주석·페이지·입력란을 확인한다. 과거 Week1~2 스냅샷은 유지한다.
  - 완료·검수 기준: 그림/표/주석 번호·페이지·본문/기능명이 일치한다.

#### 발표·제출 준비

담당: **김웅건**

- [ ] **발표 자료와 최종 보고서 제출본 작성** — WBS `D125`
  - 판단: **미수행**
  - 현재 근거: 최종 발표자료와 제출본 완료 증거가 없다.
  - 코드·문서: [docs/계획/PROJECT_PLAN.md](<D:/ai_agent/docs/계획/PROJECT_PLAN.md>), [docs/검수/실제_API_검수결과.md](<D:/ai_agent/docs/검수/실제_API_검수결과.md>)
  - 남은 작업: 발표자료·최종 HWP/PDF를 작성하고 열어 확인한다.
  - 완료·검수 기준: 제출 형식으로 열어 페이지·이미지·출처·입력란을 확인한다.

- [ ] **시연 리허설 및 제출 산출물 확인** — WBS `D126`
  - 판단: **미수행**
  - 현재 근거: 최종 확장 버전의 실제 사용자 시연 리허설/산출물 확인은 기록되지 않았다.
  - 코드·문서: [scripts/verify_live.py](<D:/ai_agent/scripts/verify_live.py>), [docs/검수/사용자_테스트_안내.md](<D:/ai_agent/docs/검수/사용자_테스트_안내.md>)
  - 남은 작업: 사용자가 실행·종목 전환·파일 저장/열기·발표 리허설을 수행하고 기록한다.
  - 완료·검수 기준: 자동 검사와 사용자 조작 확인을 분리하며 실패 시 설명 범위를 준비한다.

- [ ] **프로젝트 최종 시연 및 산출물 제출** — WBS `D127`
  - 판단: **미수행**
  - 현재 근거: 실제 최종 시연/외부 제출 완료 증거가 없다.
  - 코드·문서: [docs/계획/PROJECT_PLAN.md](<D:/ai_agent/docs/계획/PROJECT_PLAN.md>)
  - 남은 작업: 실제 시연/제출 후 제출본·버전·확인 결과를 남긴다.
  - 완료·검수 기준: 코드 작성·파일 생성만으로 외부 제출 완료라 적지 않는다.

## 5. 검증 기록과 제출 전 확인

### 로컬 자동 검사

2026-10-20 이번 문서 수정 직전 검토에서 자동 검사 133개가 14.860초에 모두 통과했다. 이번 수정은 MD만 대상으로 하며 그 뒤 코드를 변경하지 않았다. 실제 외부 응답은 모의 자료로 대체하며, 함수 개수와 실제 실행 합계가 일치한다.

| 파일 | 검사 수 |
|---|---:|
| [test_additional_regressions.py](<D:/ai_agent/tests/test_additional_regressions.py>) | 4 |
| [test_dart.py](<D:/ai_agent/tests/test_dart.py>) | 6 |
| [test_dashboard.py](<D:/ai_agent/tests/test_dashboard.py>) | 5 |
| [test_data_rules.py](<D:/ai_agent/tests/test_data_rules.py>) | 20 |
| [test_excel_export.py](<D:/ai_agent/tests/test_excel_export.py>) | 4 |
| [test_financial_commentary.py](<D:/ai_agent/tests/test_financial_commentary.py>) | 5 |
| [test_financials.py](<D:/ai_agent/tests/test_financials.py>) | 7 |
| [test_history.py](<D:/ai_agent/tests/test_history.py>) | 10 |
| [test_live_regressions.py](<D:/ai_agent/tests/test_live_regressions.py>) | 25 |
| [test_report_pipeline.py](<D:/ai_agent/tests/test_report_pipeline.py>) | 13 |
| [test_selection_pipeline.py](<D:/ai_agent/tests/test_selection_pipeline.py>) | 9 |
| [test_user_flow.py](<D:/ai_agent/tests/test_user_flow.py>) | 25 |
| **합계** | **133** |

### 실제 외부 연동 기록

2026-10-20 10:36~10:37 KST의 검수자료/실제_API_검수.json 기록을 재확인했다. 그 기록은 실제 외부 응답을 사용했다고 명시하며 브라우저/별도 서버는 시작하지 않았다. 이번 문서 수정에서는 실제 API를 재호출하지 않았다.

반도체 최초 선택(삼성전자)과 후보2 전환(SK하이닉스), 2차전지(LG화학), 로봇 입력의 당시 응답을 기록한다. 로봇 입력에서 선택된 삼성전자의 테마 관련성이 검증됐다는 뜻은 아니다. 기록의 complete는 스크립트/모델의 제한된 판정이며 모든 확장 업무100% 완료 판정이 아니다.

- [ ] 실제 브라우저의 가독성/잘림/모바일 또는 좁은 화면 확인.
- [ ] 실제 Excel에서 열기·셀 값 변경·차트 갱신·저장 확인.
- [ ] 설명의 의미·기간·공식ROE 범위/산식 검토.
- [ ] 데이터 API 비용·화면 제공·다운로드 조건 확인.
- [ ] 확장 오류/장시간 반복·동시 요청과 복구 확인.
- [ ] 실제 화면 캡처·HWP/PDF 최종 편집·발표/리허설·제출.

### 문서의 우선순위

현재 구현/미완료 판단은 이 계획서·수정된README·구현결과 정리와 검수JSON을 함께 본다. docs의 이전 계획/검수MD에는 당시80개/55개 검사 등 역사 기록이 남을 수 있으며 이번 수정 대상은 아니다. 과거 날짜의 기록을 지우거나 현재 실행으로 바꾸지 않는다.

### 공식 참조

- [OpenDART 기업번호](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019018)
- [OpenDART 전체 재무제표](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020)
- [OpenDART 주요 재무지표](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2022001)
- [yfinance 공식 프로젝트](https://github.com/ranaroussi/yfinance)
- [XlsxWriter 차트](https://xlsxwriter.readthedocs.io/working_with_charts.html)

위 링크는 기존 설계 참조이며 이번 MD 수정에서 새로운 API 호출/이용권한 확인을 수행한 것은 아니다. 특히 도구의 오픈소스 라이선스와 원천 데이터의 화면/파일 제공 조건을 구분한다.
