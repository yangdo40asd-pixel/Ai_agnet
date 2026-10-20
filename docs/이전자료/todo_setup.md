# 필수 패키지 설치 진행표

> 🚨 **[최우선 모토] "빠르게 하지 말고, 천천히 그러나 정확하게 (Slowly but Accurately)"**
> 속도에 타협하지 않고 각 모듈의 완벽한 검증과 안정적인 데이터 흐름을 최우선 가치로 둡니다.

프로젝트 초기 세팅을 위해 우선적으로 설치해야 하는 필수 라이브러리 목록 체크리스트입니다. 설치를 완료한 항목은 `[x]`로 표시하여 진척도를 관리하세요.

## 1. 가상환경 및 기본 설정
- [x] 파이썬 가상환경(venv) 생성 및 활성화
- [x] `pip install --upgrade pip` (pip 모듈 최신화)

## 2. 웹 UI 및 프론트엔드 (시각화 포함)
- [x] `streamlit` (웹 챗봇 및 화면 인터페이스 구축)
- [x] `plotly` (반응형 주식 차트 및 데이터 시각화)

## 3. 금융 데이터 및 크롤링 (퍼포먼스 강화)
- [x] `yfinance` (글로벌 주가 및 재무 지표 데이터 수집)
- [x] `FinanceDataReader` (한국 주식 종목코드, 상장폐지 정보, 테마 매핑)
- [x] `requests` (웹 API 호출 및 HTTP 통신)
- [x] `beautifulsoup4` (웹 페이지 텍스트 파싱)
- [x] `lxml` (크롤링 파싱 속도 대폭 향상)
- [x] `aiohttp` (비동기 통신으로 다중 종목 동시 데이터 수집)

## 4. AI 및 에이전트 구성 (안정성 강화)
- [x] `langchain` (LLM 파이프라인 뼈대 구성)
- [x] `langchain-openai` (OpenAI API 연동)
- [x] `langchain-groq` (Groq API 연동)
- [x] `crewai` (다중 에이전트 역할 분담 및 협업 프레임워크)
- [x] `tiktoken` (뉴스 데이터 과부하 및 프롬프트 토큰 초과 방지)
- [x] `pydantic` (AI 응답의 완벽한 구조화 및 화면 깨짐 방지)

## 5. 데이터 처리 및 유틸리티
- [x] `pandas` (수집된 데이터 전처리 및 표 형태 가공)
- [x] `python-dotenv` (로컬 환경에서 `.env` 파일로 API Key 안전하게 관리)
