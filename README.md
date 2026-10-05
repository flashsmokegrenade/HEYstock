# HEYstock: AI 멀티 에이전트 금융 리서치 및 온체인 앵커링 플랫폼

HEYstock은 LLM 멀티 에이전트 협업 아키텍처와 블록체인 무결성 검증 기술을 결합한 금융 리서치 시스템입니다.
전문 분석 에이전트들이 기술적 지표, 펀더멘털, 거시 경제, 소셜 센티먼트를 다각도로 분석하고, 강세론과 약세론의 상호 토론 및 리스크 검증을 거쳐 최종 투자 합의(Consensus)와 3단 시나리오 맵을 도출합니다.

---

## 빠른 실행 가이드 (Quick Start)

본 프로젝트는 평가 환경을 위해 API 키(OPENAI_API_KEY)가 포함된 .env 파일이 사전에 구성되어 있습니다. 별도의 환경 변수 설정 없이 아래 순서대로 실행하면 웹 대시보드가 구동됩니다.

### 1단계: 필수 라이브러리 일괄 설치
1. HEYstock 프로젝트 폴더를 엽니다.
2. 탐색기 상단의 주소 표시줄을 클릭한 뒤, 영문으로 cmd를 입력하고 Enter를 누릅니다. (현재 폴더 위치로 명령 프롬프트 창이 열립니다.)
3. 열린 창에 아래 명령어를 입력하고 Enter를 누릅니다.

pip install -r requirements.txt

### 2단계: 메인 웹 대시보드 실행
1. 라이브러리 설치가 끝난 동일한 명령 프롬프트(CMD) 창에서 곧바로 아래 명령어를 입력하고 Enter를 누릅니다.

streamlit run app.py

(환경에 따라 실행되지 않을 경우 python -m streamlit run app.py 를 입력합니다.)

2. 명령어 실행 후 기본 웹 브라우저가 자동으로 열리며 웹 대시보드(http://localhost:8501)로 바로 연결됩니다.
(자동으로 열리지 않을 경우 브라우저 주소창에 http://localhost:8501 을 입력하여 접속합니다.)

### 주요 기능 확인 사항
- 종목 입력: 검색창에 미국 주식 티커(예: GOOG, NVDA, AAPL, TSLA) 입력
- 인터랙티브 차트: Plotly 기반 캔들스틱, 이동평균선(10EMA, 50/200SMA), 볼린저 밴드, 거래량 보조지표 확인 (마우스 드래그 확대 및 축소 지원)
- 에이전트별 분석: Technical, Fundamental, Sentiment, Macro 4대 영역별 정량 점수(Domain Score) 및 요약 열람
- 온체인 무결성 검증: '블록체인 앵커링' 탭에서 분석 리포트의 SHA-256 고유 해시값과 원장(chain_ledger.json) 무결성 대조

---

## 보조 실행 모드: 원클릭 콘솔 분석기

터미널 환경에서 백엔드 파이프라인의 실시간 텍스트 스트리밍과 자동 아카이빙을 확인하는 모드입니다.

1. 프로젝트 폴더의 분석기_시작.bat 파일을 더블클릭합니다.
2. 콘솔 창 안내에 따라 분석할 주식 티커(예: GOOG)를 입력합니다.
3. 4대 도메인 에이전트의 데이터 수집, 강·약세 토론, 리스크 합의가 콘솔에 실시간 출력되며, 최종 리포트는 투자 등급별로 stock_db 폴더에 자동 분류 저장됩니다.

---

## 시스템 구동 파이프라인

HEYstock은 데이터 수집부터 의사결정, 리포트의 블록체인 앵커링까지 총 5단계 파이프라인으로 구동됩니다.

1. 멀티 도메인 데이터 인제스천
- 시장 및 차트 지표: yfinance, stockstats 기반 보조지표 계산
- 거시 경제 지표: FRED 연준금리, 10년물 국채금리, CPI
- 정성 데이터: 최신 공시, 뉴스, 소셜 센티먼트 수집

2. 전문 분석가 에이전트 평가 (Analyst Stage)
- Technical Analyst: 10EMA, 50/200SMA, RSI, MACD, ATR, 볼린저 밴드
- Fundamental Analyst: 재무제표, TTM/Forward P/E, 잉여현금흐름(FCF), ROE
- Sentiment Analyst: 뉴스 호악재 판별 및 투자자 심리 정량화
- Macro/News Analyst: 금리, 인플레이션 등 거시 지표 기반 시장 레짐 판정

3. 투자 전략 토론 및 리스크 심의 (Debate & Risk Stage)
- Bull vs Bear Debate: 강세 분석가와 약세 분석가의 다면 논쟁 (Research Manager 중재)
- Trader Planning: 도출된 리서치 결과를 바탕으로 실질적 매매 포지션 수립
- Risk Management: Aggressive / Neutral / Conservative 3자 리스크 검증

4. 최종 합의 및 시나리오 맵 도출 (Consensus & Synthesis)
- Multi-Agent Consensus: 5단계 종합 등급 판정 (Strong Buy ~ Sell / Balanced)
- Strategic Scenario Map: 상방 확장, 박스권 횡보, 하방 무효화 3단 조건부 시나리오
- Automated Categorization: 의견별 자동 분류 저장 (stock_db/1_Buy, stock_db/2_Hold 등)

5. 블록체인 무결성 앵커링 (Integrity Anchoring)
- 최종 리포트 데이터에 SHA-256 해시를 적용하여 분산 원장(chain_ledger.json)에 체이닝 기록

---

## 문제 해결 (Troubleshooting)

- 순정 PC에서 파이썬 명령어가 동작하지 않는 경우
  - python.org에서 Python 3.10 이상 버전을 설치합니다.
  - 설치 첫 화면 하단의 'Add python.exe to PATH'(환경 변수 추가)를 반드시 체크해야 터미널 명령어가 동작합니다.

- streamlit: command not found 에러가 발생하는 경우
  - python -m streamlit run app.py 명령어로 대체하여 실행하거나, pip install -r requirements.txt 가 정상 완료되었는지 확인합니다.

- 포트 충돌(Port 8501 is already in use) 안내가 뜨는 경우
  - 아래 명령어로 다른 포트를 지정하여 실행합니다:
    streamlit run app.py --server.port 8502

---

## 디렉토리 구조

HEYstock/
├── app.py                   # Streamlit 인터랙티브 웹 대시보드 메인
├── main.py                  # 콘솔 분석기 파이프라인 진입점
├── 분석기_시작.bat           # 콘솔 분석기 원클릭 실행 배치 파일
├── blockchain_anchor.py     # SHA-256 리포트 무결성 체이닝 및 검증 모듈
├── chart_builder.py         # Plotly 기반 주가 및 보조지표 차트 시각화 모듈
├── market_data.py           # 시장, 거시경제, 뉴스 데이터 수집 및 전처리
├── report_explainer.py      # 리포트 구조화 및 시각화 요약 모듈
├── chain_ledger.json        # 블록체인 해시 원장 데이터베이스
├── tradingagents/           # LangGraph 기반 멀티 에이전트 오케스트레이션 코어
├── results/                 # 분석 산출물 저장 디렉토리
├── requirements.txt         # 프로젝트 의존성 패키지 목록
├── .env                     # LLM API 키 환경 변수 파일 (사전 구성 완료)
└── README.md                # 시스템 명세 및 순정 환경 실행 가이드