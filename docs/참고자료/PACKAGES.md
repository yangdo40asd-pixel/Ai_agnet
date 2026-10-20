# 패키지 현황 정리

> **작성일:** 2026-09-21
> **기준:** 현재 실제로 코드에서 사용 중인 것 vs 설치만 해두고 앞으로 쓸 것

---

## 현재 사용 중 (실제 코드에서 작동 확인 완료)

| 패키지 | 역할 | 사용 위치 |
|:---|:---|:---|
| `streamlit` | 웹 UI 화면 구성 (검색창, 로딩, 결과 출력) | `src/ui/app.py` |
| `langchain` | AI 에이전트 파이프라인 뼈대 | `src/ui/app.py`, `poc_archive/agent_poc.py` |
| `langchain-groq` | Groq API와 LangChain 연결 | `src/ui/app.py`, `poc_archive/agent_poc.py` |
| `finance-datareader` | KRX 전체 종목 리스트 조회, 종목명 → 코드 변환 | `src/ui/app.py`, `poc_archive/agent_poc.py` |
| `yfinance` | 종목코드 기반 실시간 주가, PER 수집 | `src/ui/app.py`, `poc_archive/agent_poc.py` |
| `requests` | 네이버 API HUB에 HTTP 요청 전송 | `src/ui/app.py`, `poc_archive/agent_poc.py` |
| `python-dotenv` | .env 파일에서 API 키 불러오기 | 모든 파이썬 파일 공통 |
| `pandas` | 수집한 종목 리스트 데이터 표 형태로 처리 | `poc_archive/agent_poc.py` |
| `beautifulsoup4` | 정적 웹페이지 HTML 파싱 | `poc_archive/poc_scraper.py` |
| `lxml` | BeautifulSoup HTML 파싱 속도 향상 엔진 | `poc_archive/poc_scraper.py` |

---

## 설치 완료, 사용 예정 (아직 코드 미작성)

| 패키지 | 역할 | 사용 예정 시점 |
|:---|:---|:---|
| `opendartreader` | 금융감독원 DART API 연동 → 기업 재무제표(매출, 영업이익, 부채) 원본 수집 | DART API 키 수령 후 즉시 |
| `selenium` | 동적 웹페이지 크롤링, 자동 로그인, 버튼 클릭 자동화 | 공식 API 없는 타겟 사이트가 생길 때 |
| `webdriver-manager` | 크롬 드라이버 자동 설치 및 버전 관리 (selenium과 세트) | selenium 도입 시 함께 |
| `langchain-google-genai` | Google Gemini API를 LangChain 에이전트에 연결 | Groq 대신 Gemini를 두뇌로 교체 또는 병행 시 |
| `reportlab` | AI 리포트를 PDF 문서로 변환 및 다운로드 기능 | 리포트 출력 기능 고도화 단계 |
| `plotly` | 주가, 재무 지표 등 데이터 시각화 (차트, 그래프) | UI 고도화 단계 |
| `aiohttp` | 비동기 HTTP 요청 처리 (여러 API 동시 호출 속도 향상) | 데이터 수집 성능 최적화 단계 |

---

## 설치 완료, 검토 중 (사용 여부 미정)

| 패키지 | 역할 | 비고 |
|:---|:---|:---|
| `langchain-openai` | OpenAI GPT와 LangChain 연결 | 현재 Groq 무료 모델로 대체 중. 유료 전환 시 검토 |
| `crewai` | 역할 분담 멀티 에이전트 (수집 담당/분석 담당 분리) | 시스템 규모가 커질 때 도입 검토 |
| `tiktoken` | OpenAI 모델 토큰 계산 도구 | langchain-openai 도입 시 함께 사용 |
| `pydantic` | 데이터 유효성 검증 (현재는 langchain 내부에서 자동 사용) | 별도 데이터 모델 설계 시 직접 활용 예정 |
