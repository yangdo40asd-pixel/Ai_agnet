import sys
import os
import requests
import yfinance as yf
import FinanceDataReader as fdr
import streamlit as st
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate

# 1. 환경변수 로드
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
load_dotenv(env_path)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
NAVER_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_SECRET = os.getenv("NAVER_CLIENT_SECRET")

# 2. 웹페이지 화면 구성
st.set_page_config(page_title="테마주 인사이트 리포트")
st.title("테마주 인사이트 리포트")
st.write("관심 있는 주식 테마를 입력하면, 실시간 주가와 뉴스를 분석해 리포트를 제공합니다.")

# 검색창
theme_input = st.text_input("검색할 테마를 입력하세요 (예: 반도체, 2차전지, 제약바이오):", value="반도체")

# 분석 버튼
if st.button("분석 시작"):
    if not theme_input:
        st.warning("테마를 입력해주세요.")
    else:
        try:
            # 스피너(로딩)
            with st.spinner(f"'{theme_input}' 관련 데이터를 수집 및 분석 중입니다... (약 10~15초 소요)"):
                
                # LLM 세팅
                llm = ChatGroq(groq_api_key=GROQ_API_KEY, model_name="qwen/qwen3.8-27b", temperature=0.1)
                
                # [목표 1] 테마주 탐색
                theme_prompt = ChatPromptTemplate.from_messages([
                    ("system", "너는 증권사 리서치 센터 연구원이야. 이모티콘을 절대 사용하지 마. 사용자가 제시하는 테마와 관련된 한국거래소(KRX) 상장 주식 대표 종목 3가지만 쉼표로 구분해서 말해. 부가설명 절대 금지. 한국어 답변."),
                    ("human", "{theme} 관련주 알려줘")
                ])
                theme_stocks_str = (theme_prompt | llm).invoke({"theme": theme_input}).content
                theme_stocks = [s.strip() for s in theme_stocks_str.split(",")]
                target_stock = theme_stocks[0] if theme_stocks else "삼성전자"

                # [목표 2] 주식 데이터 수집
                krx_df = fdr.StockListing('KRX')
                stock_row = krx_df[krx_df['Name'] == target_stock]
                current_price = "알 수 없음"
                per = "알 수 없음"
                if not stock_row.empty:
                    stock_code = stock_row.iloc[0]['Code']
                    ticker = yf.Ticker(f"{stock_code}.KS")
                    current_price = ticker.info.get('currentPrice', '정보 없음')
                    per = ticker.info.get('trailingPE', '정보 없음')

                # [목표 3] 뉴스 수집
                url = "https://naverapihub.apigw.ntruss.com/search/v1/news"
                headers = {"X-NCP-APIGW-API-KEY-ID": NAVER_ID, "X-NCP-APIGW-API-KEY": NAVER_SECRET}
                params = {"query": f"{theme_input} {target_stock}", "display": 3, "sort": "sim"}
                res = requests.get(url, headers=headers, params=params)
                news_text = ""
                if res.status_code == 200:
                    for item in res.json().get('items', []):
                        title = item['title'].replace('<b>', '').replace('</b>', '').replace('&quot;', '"')
                        news_text += f"- {title}\n"
                else:
                    news_text = "뉴스 수집 실패"

                # [목표 4] 최종 리포트 산출
                report_prompt = ChatPromptTemplate.from_messages([
                    ("system", """너는 증권사 리서치 센터의 수석 연구원이야. 작성하는 모든 문서에 이모티콘(이모지)을 일절 사용하지 마. 
                    건조하고 전문적인 문체로 작성해. 제공된 팩트만을 바탕으로 마크다운 형식의 깔끔한 투자 리포트를 작성해. 절대 매수/매도 추천은 하지 마.
                    양식:
                    **[테마 리포트: {theme}]**
                    
                    **1. 테마 최신 동향** (뉴스를 바탕으로 2문장 요약)
                    **2. 주요 관련 테마주** (관련주 나열)
                    **3. 대표 종목 분석: {target_stock}** (주가, PER 기입 및 펀더멘털 해석)
                    **4. 핵심 인사이트 (3줄 요약)** (기회, 위험, 종합의견)"""),
                    ("human", "테마: {theme}\n관련주: {theme_stocks}\n주가: {current_price}원, PER: {per}\n뉴스:\n{news_text}")
                ])
                
                report = (report_prompt | llm).invoke({
                    "theme": theme_input, 
                    "theme_stocks": theme_stocks_str, 
                    "target_stock": target_stock,
                    "current_price": current_price,
                    "per": per,
                    "news_text": news_text
                }).content
            
            # 성공 메시지 및 리포트 출력
            st.success("분석이 완료되었습니다.")
            st.markdown(report)
            
        except Exception as e:
            st.error(f"실행 중 오류가 발생했습니다: {e}")
