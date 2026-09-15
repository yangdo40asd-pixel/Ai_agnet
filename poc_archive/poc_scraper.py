import yfinance as yf
import requests
from bs4 import BeautifulSoup

def get_stock_info(ticker="005930.KS"):
    """yfinance를 이용한 주가 및 재무 정보 가져오기 (예: 삼성전자)"""
    print(f"--- [{ticker}] 주가 및 재무 데이터 (yfinance API) ---")
    try:
        stock = yf.Ticker(ticker)
        
        # 기본적인 데이터 수집
        info = stock.info
        current_price = info.get('currentPrice', '데이터 없음')
        per = info.get('trailingPE', '데이터 없음')
        pbr = info.get('priceToBook', '데이터 없음')
        
        print(f"현재가: {current_price} KRW")
        print(f"PER: {per}")
        print(f"PBR: {pbr}")
        print("\n")
    except Exception as e:
        print(f"yfinance 데이터 수집 중 오류 발생: {e}\n")

def get_naver_news(query="삼성전자"):
    """BeautifulSoup을 이용한 네이버 검색 뉴스 수집 (정적 페이지 크롤링)"""
    print(f"--- [{query}] 관련 최신 뉴스 헤드라인 (BeautifulSoup 크롤링) ---")
    url = f"https://search.naver.com/search.naver?where=news&query={query}"
    
    # 웹 브라우저처럼 보이도록 User-Agent 설정
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # 네이버 뉴스 검색 결과의 제목 텍스트 (클래스명: news_tit)
            news_titles = soup.select(".news_tit")
            
            if not news_titles:
                print("뉴스 제목을 찾지 못했습니다. 선택자(CSS Selector)를 확인해주세요.")
                
            for i, title in enumerate(news_titles[:5]):  # 최신 뉴스 상위 5개만 출력
                print(f"{i+1}. {title.text}")
                print(f"   - 링크: {title['href']}")
        else:
            print(f"웹페이지를 불러오지 못했습니다. 상태 코드: {response.status_code}")
    except Exception as e:
        print(f"크롤링 중 오류 발생: {e}")

if __name__ == "__main__":
    print("🚀 [PoC 테스트 시작] 데이터 수집 실현 가능성 검증\n")
    get_stock_info("005930.KS")   # 삼성전자 티커 기호
    get_naver_news("AI 반도체")   # 임의의 검색 키워드
