import sys
import os
import requests
import yfinance as yf
import FinanceDataReader as fdr
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

# 윈도우 터미널 한글/이모지 깨짐 방지
sys.stdout.reconfigure(encoding='utf-8')

# 1. 환경변수 로드 (.env 파일이 부모 폴더에 있으므로 경로 명시)
env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
load_dotenv(env_path)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NAVER_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_SECRET = os.getenv("NAVER_CLIENT_SECRET")

print("="*60)
print("▶ AI 인사이트 리포트 에이전트 시작 (Target: 반도체)")
print("="*60)

# LLM 초기화 (현재 계정에서 접근 가능한 최신 모델 사용)
llm = ChatGroq(
    groq_api_key=GROQ_API_KEY, 
    model_name="qwen/qwen3.8-27b", 
    temperature=0.1
)

# ---------------------------------------------------------
# [목표 1] 테마주 탐색 (AI 사전 지식 활용)
# ---------------------------------------------------------
print("\n[1/4] '반도체' 테마 관련주를 탐색 중입니다...")
theme = "반도체"
theme_prompt = ChatPromptTemplate.from_messages([
    ("system", "너는 한국 주식 전문가야. 사용자가 제시하는 테마와 관련된 한국거래소(KRX) 상장 주식 대표 종목 3가지만 쉼표로 구분해서 말해. 다른 부가설명은 절대 하지마. 반드시 한국어로 대답해."),
    ("human", "{theme} 관련주 알려줘")
])
chain1 = theme_prompt | llm
theme_stocks_str = chain1.invoke({"theme": theme}).content
theme_stocks = [s.strip() for s in theme_stocks_str.split(",")]
print(f" -> AI가 찾은 관련 종목: {theme_stocks_str}")

target_stock = theme_stocks[0] if theme_stocks else "삼성전자"

# ---------------------------------------------------------
# [목표 2] 주식 정보 수집 (FinanceDataReader + yfinance)
# ---------------------------------------------------------
print(f"\n[2/4] 대표 종목 '{target_stock}' 주식 데이터를 수집 중입니다...")
krx_df = fdr.StockListing('KRX')
stock_row = krx_df[krx_df['Name'] == target_stock]

if not stock_row.empty:
    stock_code = stock_row.iloc[0]['Code']
    ticker = yf.Ticker(f"{stock_code}.KS")
    info = ticker.info
    current_price = info.get('currentPrice', '정보 없음')
    per = info.get('trailingPE', '정보 없음')
    print(f" -> 현재가: {current_price}원, PER: {per}")
else:
    print(f" -> {target_stock} 종목코드를 찾지 못했습니다. 삼성전자로 대체합니다.")
    current_price = "알 수 없음"
    per = "알 수 없음"

# ---------------------------------------------------------
# [목표 3] 증권 뉴스 수집 (네이버 API)
# ---------------------------------------------------------
print(f"\n[3/4] '{theme}' 및 '{target_stock}' 관련 뉴스를 긁어오는 중입니다...")
url = "https://naverapihub.apigw.ntruss.com/search/v1/news"
headers = {"X-NCP-APIGW-API-KEY-ID": NAVER_ID, "X-NCP-APIGW-API-KEY": NAVER_SECRET}
params = {"query": f"{theme} {target_stock}", "display": 3, "sort": "sim"}

news_text = ""
res = requests.get(url, headers=headers, params=params)
if res.status_code == 200:
    for item in res.json().get('items', []):
        title = item['title'].replace('<b>', '').replace('</b>', '').replace('&quot;', '"')
        news_text += f"- {title}\n"
    print(f" -> 뉴스 수집 성공:\n{news_text}")
else:
    news_text = "최신 뉴스 수집 실패"
    print(" -> 뉴스 수집 실패")

# ---------------------------------------------------------
# [목표 4 & 5] AI 최종 리포트 산출
# ---------------------------------------------------------
print("\n[4/4] 에이전트가 팩트 데이터를 종합하여 최종 리포트를 작성하고 있습니다...\n")
report_prompt = ChatPromptTemplate.from_messages([
    ("system", """너는 전문 주식 애널리스트야. 반드시 한국어(Korean)로만 대답해. 
    제공된 [테마, 관련주, 주가데이터, 뉴스] 팩트만을 바탕으로 마크다운 형식의 깔끔한 투자 리포트를 작성해. 
    양식은 다음을 정확히 따라야 해:
    
    **[테마 리포트: {theme}]**
    
    **1. 테마 최신 동향** (뉴스를 바탕으로 2문장 요약)
    **2. 주요 관련 테마주** (관련주 나열)
    **3. 대표 종목 핵심 분석: {target_stock}** (주가, PER 기입 및 펀더멘털 단순 해석)
    **4. AI 핵심 인사이트 (3줄 요약)** (기회, 위험, 최종요약)
    
    절대 매수/매도 추천은 하지 말고 팩트만 전달해."""),
    ("human", "테마: {theme}\n관련주: {theme_stocks}\n주가데이터: 현재가 {current_price}원, PER {per}\n관련뉴스:\n{news_text}")
])

final_chain = report_prompt | llm
report = final_chain.invoke({
    "theme": theme, 
    "theme_stocks": theme_stocks_str, 
    "target_stock": target_stock,
    "current_price": current_price,
    "per": per,
    "news_text": news_text
}).content

print("="*60)
print(report)
print("="*60)
