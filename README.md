# AI 테마주 인사이트 리포트

관심 테마를 입력하면 관련 종목 후보 세 개를 제안하고, 첫 번째 종목의 상장 여부를 확인한 뒤 주가·PER와 관련 뉴스 제목을 모아 설명하는 프로그램이다. 결과 화면에서 실제 조회값, 자료 출처, 조회 시각, 뉴스 링크와 AI 해석을 함께 확인할 수 있도록 작성했다.

**2026-10-15 기준 로컬 자동 검사 80개를 통과했다.** 실제 API를 호출하는 입력 → 자료 수집 → AI 리포트 → 화면 표시 검사도 수행했다. 결과와 제한은 [실제_API_검수결과.md](실제_API_검수결과.md)에 기록한다. 화면 검사는 서버·브라우저 없이 Streamlit AppTest로 수행하므로, 실제 브라우저의 시각적 배치는 별도 확인 대상이다.

## 사용자가 직접 실행하기

가장 간단한 방법으로 프로젝트 폴더의 `start.bat`을 더블 클릭하여 실행할 수 있습니다.

또는 PowerShell에서 다음 명령을 직접 실행합니다. 작업 위치는 D:\ai_agent입니다.

```powershell
Set-Location D:\ai_agent
.\venv\Scripts\python.exe -m streamlit run .\src\ui\app.py
```

기존 가상환경과 .env를 그대로 사용한다. 별도 환경을 준비한다면 Python 3.10 이상에서 requirements-core.txt의 패키지를 설치한다. 현재 환경에서 패키지를 새로 설치하거나 업데이트하는 작업은 수행하지 않았다.

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-core.txt
```

설정 항목은 [.env.example](.env.example)에 정리했다. **기존 .env를 예시 파일로 덮어쓰지 않는다.**

| 항목 | 쓰임 |
|---|---|
| GROQ_API_KEY | 현재 AI 호출에 사용하는 키 |
| GROQ_MODEL | AI 모델 이름. 기본값 openai/gpt-oss-20b는 2026-10-15 실제 호출을 확인했다. 기존 Qwen 모델의 반복적인 검증 실패를 비교한 뒤 변경했다. 향후 제공 모델과 이용 한도는 달라질 수 있다. |
| NAVER_CLIENT_ID / NAVER_CLIENT_SECRET | 현재 NAVER API HUB 방식의 뉴스 인증값 |
| NEWS_SORT | date: 발행일순(기본값), sim: 관련도순 |
| REQUEST_TIMEOUT | 뉴스·AI 요청 제한 시간, 기본 30초. KRX/yfinance의 내부 요청 전체에는 적용되지 않는다. |

AI 모델 이름이나 이용 권한이 맞지 않으면 AI 호출 실패 안내가 나온다. 현재 뉴스 URL과 인증 헤더는 기존 코드의 API HUB 방식을 유지했다. NAVER Developers의 기존 검색 API용 키를 가지고 있다면 API HUB의 인증 설정과 혼동하지 않도록 확인한다.

## 지금 작성된 처리 순서

1. 테마의 앞뒤 공백과 길이를 확인한다.
2. AI에게 서로 다른 종목 후보 세 개를 요청하고 응답 형식을 확인한다.
3. KRX 목록으로 후보명, 종목코드, 시장을 확인한다. 미확인 후보가 있으면 한 번 재제안받아 목록과 다시 대조한다. 재확인에도 실패하면 기존 미확인 안내를 유지하며, 첫 번째 후보가 미확인이면 중단한다.
4. KOSPI와 KOSDAQ의 조회 코드를 구분한다. 지원하지 않는 시장은 임의로 조회하지 않는다.
5. 대표 종목의 주가·PER를 가져온다. PER가 없으면 같은 제공자의 원화 기준 최근 12개월 희석 EPS로 계산하고 계산 근거·실적 기간을 표시한다. 예상 PER나 연간 EPS로 대체하지 않는다. 보완 자료도 없으면 정보 없음으로 남긴다.
6. 뉴스 제목 최대 세 개와 원문 또는 제공 링크, 발행 시각을 수집한다. 본문은 읽지 않는다.
7. AI에게 정해진 형식의 설명을 요청한다. 지원 모델에는 JSON Schema로 항목과 뉴스 번호를 제한하고, 모든 모델에서 응답을 다시 검사한다. 설명의 형식·근거·금지 표현 오류는 한 번 재작성하되 종목명·수치 불일치는 거부한다. 입력의 '2차전지'·'5G'·'HBM3' 같은 명칭은 숫자 오류로 판단하지 않는다.
8. 네 부분의 리포트와 실제 조회값·출처를 구분해 표시한다.

AI가 부적절한 응답을 주면 해당 설명을 표시하지 않는다. 첫 번째 AI 호출이나 상장 목록·금융 조회가 실패하면 분석이 중단된다. 뉴스가 없거나 실패한 경우 금융 자료만으로 가능한 제한된 설명을 요청하고, 뉴스 동향과 인사이트를 만들어 넣지 않는다. 두 번째 AI 호출이 실패하면 이미 조회한 자료만 표시한다. 누락·실패 결과에는 전체 분석 완료 메시지를 표시하지 않는다.

## 파일 역할

| 파일 | 역할 |
|---|---|
| src/config.py | .env 설정 읽기와 설정값 검사 |
| src/models.py | 기능 사이에서 전달하는 자료·오류 형식 |
| src/data/stock.py | 후보 상장 확인, 시장별 코드, 주가·PER 조회와 값 검사 |
| src/data/news.py | 뉴스 요청, 제목·링크·시각 정리, 실패·0건 구분 |
| src/agents/report.py | AI 후보 제안, 설명 생성, 응답 검사 |
| src/pipeline.py | 전체 처리 순서와 제한된 결과 보존 |
| src/ui/app.py | 입력, 진행 상태, 결과, 출처와 오류 안내 |
| tests/ | 외부 요청을 가짜 응답으로 대체한 코드·화면 처리 흐름 검사. 80개 통과 |
| scripts/verify_live.py | 실제 API를 호출하는 화면 흐름 검사. --live 명시 필요 |

## 실제 연동 검사 재실행

```powershell
.\venv\Scripts\python.exe scripts/verify_live.py --live
```

기본 검사 입력은 반도체·2차전지·로봇이다. 검사 사이에는 호출 한도를 고려해 45초 간격을 둔다. 실제 API 사용량이 발생하며 결과는 검수자료/실제_API_검수.json에 저장한다. 종료 코드 0은 안내 없는 성공, 2는 음수 PER 등의 안내를 포함한 연동 성공, 1은 검사 실패다. API 키는 출력·저장하지 않는다. AI가 HTTP 429와 10초 이하의 대기 시간을 보내면 해당 요청을 한 번 재시도하고, 지속되거나 더 긴 대기가 필요하면 한도 안내를 표시한다.
| poc_archive/ | 이전 실험 코드. 현재 실행 경로에 연결되지 않음 |

## 패키지 구분

현재 직접 사용하는 패키지는 requirements-core.txt에 있는 streamlit, yfinance, finance-datareader, requests, pandas, python-dotenv, langchain-groq다. 각 패키지가 필요로 하는 하위 패키지는 설치 시 함께 설치된다.

기존 requirements.txt는 이전 실험과 향후 확장 후보까지 포함하므로 그대로 보존했다. plotly, beautifulsoup4, lxml, aiohttp, langchain, langchain-openai, langchain-google-genai, crewai, tiktoken, pydantic, opendartreader, selenium, webdriver-manager, reportlab은 현재 src 코드에서 직접 사용하지 않는다. 일부는 다른 패키지의 의존성이므로 기존 환경에서 삭제할 필요는 없다.

## 사용자가 확인할 것

[사용자_테스트_안내.md](사용자_테스트_안내.md)를 따라 실제 연동과 화면을 확인한다. 에이전트가 실행한 자동 검사를 다시 돌리려면 `run_test.bat`을 실행하거나 다음 명령을 사용한다. 자세한 결과는 [코드_검수결과.md](코드_검수결과.md)에 있다.

```powershell
Set-Location D:\ai_agent
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

실제로 시연한 뒤 화면을 캡처하고, 실행일·입력·성공 또는 실패 내용을 남긴다. 기획서나 WBS의 완료 표시는 그 결과를 확인한 뒤 조정한다.

## 아직 확정하거나 구현하지 않은 부분

- AI 문장이 기사 내용과 정확히 연결되는지 자동으로 완전히 검증하지 않는다. 숫자·자료 형식·뉴스 번호 검사와 의미 검증은 다르다.
- 뉴스 제목만으로 산업 동향이나 테마 연관성을 충분히 입증하지 못할 수 있다. 원문을 직접 확인해야 한다.
- 후보의 상장 확인이 그 회사의 테마 연관성을 보증하지 않는다. 첫 후보 순서는 대표성 순위가 아니다.
- 가격 자료 시각은 regularMarketPrice와 regularMarketTime이 함께 확인될 때 표시한다. currentPrice만 확보되면 그 값에 시각을 임의 연결하지 않는다.
- 주가는 지연될 수 있다. 제공된 PER 자체의 실적 기준일은 미확인이며, 희석 EPS로 계산한 PER는 응답에 있는 실적 종료일을 표시한다.
- 뉴스·AI는 요청 제한 시간을 지정했지만 KRX/yfinance 내부 요청은 라이브러리 동작에 따른다.
- 그래프, 재무제표·PBR·ROE, 여러 종목 비교, PDF 내려받기는 기본 기능을 확인한 뒤 확장할 항목이다.

## 구현 시 확인한 자료

- [FinanceDataReader KRX 목록 구현](https://github.com/FinanceData/FinanceDataReader/blob/master/src/FinanceDataReader/krx/listing.py): 종목 목록 필드. 현재 설치된 라이브러리 소스도 직접 읽었다.
- [yfinance 자료 조회 구현](https://github.com/ranaroussi/yfinance/blob/main/yfinance/scrapers/quote.py): 금융 응답과 자료 조회 경로. 설치된 소스와 함께 확인했다.
- [NAVER API HUB 이관 가이드](https://guide.ncloud-docs.com/docs/apihub-migration): 현재 코드에서 유지한 호출 경로·인증 방식.
- [NAVER 뉴스 검색 문서](https://developers.naver.com/docs/serviceapi/search/news/news.md): 검색 정렬, 뉴스 제목·링크·발행 시각 필드.
- [LangChain ChatGroq 문서](https://docs.langchain.com/oss/python/integrations/chat/groq): AI 호출 설정. 설치된 ChatGroq 소스의 timeout·model 설정도 확인했다.
- [Streamlit 입력 문서](https://docs.streamlit.io/develop/api-reference/chat/st.chat_input): 대화형 입력 구성.

위 링크는 구현 참고 문서다. 실제 API 응답 확인 결과는 실제_API_검수결과.md, 로컬 자동 검사 결과는 코드_검수결과.md에 기록했다.
