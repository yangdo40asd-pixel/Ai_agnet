import os
import requests
import yfinance as yf
import FinanceDataReader as fdr
from dotenv import load_dotenv

# 1. 환경변수(.env) 파일 로드
load_dotenv()
NAVER_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_SECRET = os.getenv("NAVER_CLIENT_SECRET")

print("="*60)
print("[테스트 1] 네이버 뉴스 API 데이터 수집 (눈 역할)")
print("="*60)
# 네이버 API HUB(NCP) 규격 헤더
headers = {
    "X-NCP-APIGW-API-KEY-ID": NAVER_ID,
    "X-NCP-APIGW-API-KEY": NAVER_SECRET
}
# 검색어: "AI 반도체"
url = "https://naverapihub.apigw.ntruss.com/search/v1/news"
params = {"query": "AI 반도체", "display": 3} # 최신 뉴스 3개만

try:
    res = requests.get(url, headers=headers, params=params)
    if res.status_code == 200:
        items = res.json().get('items', [])
        for i, item in enumerate(items, 1):
            # 깔끔한 출력을 위해 HTML 태그 제거
            title = item['title'].replace('<b>', '').replace('</b>', '').replace('&quot;', '"')
            print(f"{i}. {title}")
    else:
        print(f"X 네이버 API 에러 발생: 상태 코드 {res.status_code}")
        print(f"상세 에러 내용: {res.text}")
except Exception as e:
    print(f"요청 중 에러 발생: {e}")

print("\n" + "="*60)
print("[테스트 2] FinanceDataReader (한국 주식 종목코드 맵핑)")
print("="*60)
try:
    # 한국거래소(KRX) 전체 종목 리스트 가져오기
    krx_df = fdr.StockListing('KRX')
    samsung = krx_df[krx_df['Name'] == '삼성전자']
    
    if not samsung.empty:
        code = samsung.iloc[0]['Code']
        print(f"OK 삼성전자 종목코드 찾기 성공: {code}")
    else:
        print("X 코드를 찾을 수 없습니다.")
except Exception as e:
    print(f"에러 발생: {e}")

print("\n" + "="*60)
print("[테스트 3] yfinance (주가 및 재무 지표 수집)")
print("="*60)
try:
    # 삼성전자 (한국 주식은 코드 뒤에 .KS를 붙여야 yfinance가 인식함)
    ticker = yf.Ticker("005930.KS")
    info = ticker.info
    
    current_price = info.get('currentPrice', '정보 없음')
    trailing_pe = info.get('trailingPE', '정보 없음')
    
    print(f"OK 삼성전자 현재가: {current_price} 원")
    print(f"OK 삼성전자 PER (주가수익비율): {trailing_pe}")
except Exception as e:
    print(f"에러 발생: {e}")

print("\n테스트가 종료되었습니다.")
