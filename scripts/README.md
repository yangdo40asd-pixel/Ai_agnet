# Scripts Directory Architecture (역할별 세분화 구조)

본 디렉터리는 금융 AI 어시스턴트 프로젝트의 서버 제어, 실시간 평가, 테스트 픽스처, 문서 처리 및 과거 이력을 역할별로 엄격히 분리하여 관리합니다.

---

## 1. 역할별 디렉터리 구성

### 🖥️ 1. `server/` (서버 및 런타임 제어)
로컬 인공지능 모델 런타임 및 백엔드 서버를 제어하는 스크립트 모음입니다.
- **`start_local_llm.ps1`**:
  - `llama-server.exe` 데몬을 포트 1234로 실행합니다.
  - 주요 옵션: 16K 문맥(`--ctx-size 16384`), GPU 가속(`--gpu-layers 99`), Flash Attention(`--flash-attn on`), Jinja 템플릿(`--jinja`).

### 🧪 2. `e2e_eval/` (실시간 LLM 및 대화 여정 종단 검증)
포트 1234에서 구동 중인 로컬 LLM과 실제 프롬프트/파이프라인을 연결하여 생성 품질, 근거 일치성, 상투어 배제, 세부분야 축소 등을 전수 검증하는 실행기입니다.
- **`verify_diverse_e2e_llm.py`**:
  - 8대 핵심 도메인 종단 검증 (방산·2차전지 테마 발굴, 한미반도체 장비, 주가-뉴스 인과 분석, 영업이익 원인 분석, 초보자 맞춤 설명, PER 매수 판단)
  - 실행: `.\venv\Scripts\python.exe scripts/e2e_eval/verify_diverse_e2e_llm.py`
  - 결과 저장: `docs/검수/계획8_다양한_LLM_종단검수_결과_2026-10-30.json`
- **`verify_deep_journey_llm.py`**:
  - 7대 심층 대화 여정 실시간 검증 (미정 테마 추천, 로봇 발굴, 반도체 중 메모리 직접 제조 좁히기, 패키징 장비 선별, PBR 1배 미만 해석, 미래 주가 목표치 예측 거절 및 단기 시장 요인 안내, 5개년 매출 질문)
  - 실행: `.\venv\Scripts\python.exe scripts/e2e_eval/verify_deep_journey_llm.py`
  - 결과 저장: `docs/검수/계획8_심층대화여정_LLM실시간검증_결과_2026-10-30.json`
- **`verify_phase8_stage03_full.py`**:
  - 계획8 단계 03 전수 검증 (요청 생애주기 S03, 자유 입력 C01, 기간 정규화 C04, 희소 사업정보 경계 F01-V2)
  - 실행: `.\venv\Scripts\python.exe scripts/e2e_eval/verify_phase8_stage03_full.py`
- **`verify_phase8_stage04_full.py`**:
  - 계획8 단계 04 전수 검증 (테마 발굴 근거 E01-I4, 가짜 순위 거절 E01-I2/I3, 세부분야 축소 E02-I2/I3/V1)
  - 실행: `.\venv\Scripts\python.exe scripts/e2e_eval/verify_phase8_stage04_full.py`

### 📦 3. `fixtures/` (테스트 픽스처 및 평가 계약 데이터)
`tests/` 패키지의 단위 테스트들이 공통으로 사용하는 검증 픽스처와 평가 계약 모듈입니다.
- **`llm_fixture.py`**: `synthetic_result` 등 단위 테스트용 가상 기업 분석 데이터 생성
- **`evaluation_contract.py`**: 정적 평가 스위트 로더 및 계약 검증 함수
- **`verify_saved_llm.py`**: 저장된 LLM 응답 벤치마크 평가기
- **`verify_phase_w.py`**: Phase W 회귀 검증 픽스처

### 📄 4. `document_tools/` (공시 및 기업문서 수집/도구)
한국거래소(KRX KIND) 및 금융감독원(DART) 전자공시 원문 발췌/정규화 전용 파서 도구 모음입니다.

### 🏛️ 5. `archive/` (과거 개발 이력 보존)
이전 개발 단계의 검증 스크립트 및 1회성 스크래치 패치 파일들을 안전하게 보존합니다.
- **`archive/scratch_patches/`**: 1회성 패치/임시 테스트 스크립트 (14개)
- **`archive/stage_verifications/`**: 계획8 단계별 구현 과정 세부 프로브 (12개)
- **`archive/historical_phases/`**: 과거 Phase 5, Phase 6, Phase 7, Phase W 검증기 (11개)

---

## 2. 통합 러너 (Root Entry Point)

- **`verify_local.py`**:
  - 프로젝트 전체 878개 단위·회귀 테스트를 일괄 실행하는 표준 러너입니다.
  - 실행: `.\venv\Scripts\python.exe scripts/verify_local.py`
  - 호환성을 위해 루트의 `llm_fixture.py`, `verify_diverse_e2e_llm.py` 등은 해당 역할 폴더(`fixtures/`, `e2e_eval/`)로 투명하게 연결되는 포워딩 심(Forwarding Shim)을 제공합니다.
