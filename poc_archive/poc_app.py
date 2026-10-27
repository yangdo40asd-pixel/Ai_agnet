import streamlit as st
import time

# 페이지 기본 설정
st.set_page_config(page_title="AI 인사이트 리포트 (PoC)", page_icon="📈", layout="centered")

st.title("📈 AI 인사이트 리포트 검색 (PoC)")
st.markdown("교수님 시연용: 매우 단순화된 채팅/검색 UI 뼈대입니다.")
st.divider()

# 채팅 기록을 저장할 세션 상태(Session State) 관리
if "messages" not in st.session_state:
    st.session_state.messages = []

# 이전 채팅 내용 화면에 출력
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# 사용자 입력 받기
if prompt := st.chat_input("관심 있는 테마나 키워드를 입력하세요 (예: 2차전지, AI 반도체)"):
    # 1. 사용자 메시지 추가 및 화면에 출력
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # 2. AI(시스템) 처리 과정 시뮬레이션
    with st.chat_message("assistant"):
        # UI 대기 상태(Progress) 시연을 위한 스피너
        with st.spinner(f"'{prompt}' 테마와 관련된 종목을 찾고 데이터를 수집 중입니다..."):
            time.sleep(2) # 실제 크롤링 및 API 호출이 들어갈 자리
            st.success("데이터 수집 완료!")
            
        # 가상의 결과물 출력
        response_text = f"**'{prompt}' 테마 분석 리포트 (더미 데이터)**\n\n"
        response_text += "- **관련 주식**: 삼성전자, SK하이닉스\n"
        response_text += "- **수집된 뉴스**: [속보] {prompt} 관련 시장 긍정적 전망...\n"
        response_text += "- **AI 분석**: 현재 입력하신 테마는 매우 유망한 섹터이며..."
        
        st.markdown(response_text)
        
    # 3. AI 응답을 세션 상태에 저장하여 기록 유지
    st.session_state.messages.append({"role": "assistant", "content": response_text})
