import os
import glob
import re
import datetime
import threading
import time
import streamlit as st
import plotly.graph_objects as go
import pandas as pd

from market_data import MarketDataProvider
from chart_builder import build_interactive_chart
from tradingagents.graph.trading_graph import TradingAgentsGraph

# ==============================================================================
# 1. 페이지 설정 & Apple HIG 스타일 타이포그래피 CSS
# ==============================================================================
st.set_page_config(
    page_title="BBstock AI Research & Strategic Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    /* 기본 폰트 및 베이스라인 정돈 (Apple HIG 스타일) */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
    }
    
    /* 결정 배지 (Pill Badge) */
    .decision-container {
        display: inline-flex;
        align-items: center;
        gap: 12px;
        background: rgba(255, 255, 255, 0.04);
        padding: 6px 16px;
        border-radius: 20px;
        border: 1px solid rgba(255, 255, 255, 0.08);
        margin-bottom: 14px;
    }
    .decision-label {
        font-size: 12.5px;
        font-weight: 600;
        color: #9e9e9e;
        letter-spacing: 0.5px;
        text-transform: uppercase;
    }
    .decision-pill {
        font-size: 13px;
        font-weight: 700;
        padding: 4px 14px;
        border-radius: 12px;
        letter-spacing: 0.3px;
    }
    .pill-hold { background-color: rgba(245, 158, 11, 0.18); color: #fbbf24; border: 1px solid rgba(245, 158, 11, 0.35); }
    .pill-buy { background-color: rgba(16, 185, 129, 0.18); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.35); }
    .pill-sell { background-color: rgba(239, 68, 68, 0.18); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.35); }

    /* 전략 및 본문 카드 */
    .strategy-card {
        background: rgba(255, 255, 255, 0.02);
        border: 1px solid rgba(255, 255, 255, 0.07);
        border-radius: 8px;
        padding: 18px 22px;
        font-size: 14.5px;
        line-height: 1.7;
        color: #e0e0e0;
        margin-bottom: 16px;
    }

    /* 도메인 점수 태그 */
    .score-badge {
        font-size: 12px;
        font-weight: 600;
        padding: 4px 10px;
        border-radius: 6px;
        background: rgba(38, 166, 154, 0.12);
        color: #80cbc4;
        border: 1px solid rgba(38, 166, 154, 0.25);
        display: inline-block;
        margin-top: 8px;
        margin-bottom: 8px;
    }

    /* 법적 면책 고지 배너 */
    .disclaimer-banner {
        margin-top: 36px;
        padding: 14px 18px;
        background: rgba(255, 255, 255, 0.015);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 8px;
        font-size: 12px;
        color: #888888;
        line-height: 1.6;
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. 전역 상태 관리 & 데이터 캐싱
# ==============================================================================
if "active_ticker" not in st.session_state:
    st.session_state["active_ticker"] = "GOOG"

if "analysis_task" not in st.session_state:
    st.session_state["analysis_task"] = {
        "status": "idle",
        "ticker": "",
        "report_content": "",
        "report_path": None,
        "error_msg": "",
        "start_time": 0
    }

@st.cache_data(ttl=300, show_spinner=False)
def fetch_cached_chart_data(ticker: str, days: int) -> pd.DataFrame:
    try:
        provider = MarketDataProvider()
        return provider.fetch_candlestick_data(ticker, days=days)
    except Exception:
        return pd.DataFrame()

# ==============================================================================
# 3. 비동기 백그라운드 분석 워커
# ==============================================================================
def _run_analysis_worker(task_dict: dict, ticker: str, date_str: str):
    try:
        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            graph = TradingAgentsGraph(config=DEFAULT_CONFIG.copy())
        except Exception:
            graph = TradingAgentsGraph()

        result = graph.propagate(ticker, date_str)
        time.sleep(1)

        patterns = [
            f"stock_db/**/*{ticker}*.*",
            f"results/**/*{ticker}*.*",
            f"**/*{ticker}*_report.*",
            f"**/*{ticker}*.*"
        ]
        found_files = []
        for p in patterns:
            found_files.extend(glob.glob(p, recursive=True))

        valid_files = [
            f for f in set(found_files) 
            if f.endswith(('.txt', '.md')) and os.path.isfile(f) and not f.endswith('.py')
        ]

        extracted_text = ""
        if valid_files:
            latest_file = max(valid_files, key=os.path.getmtime)
            task_dict["report_path"] = latest_file
            with open(latest_file, "r", encoding="utf-8") as rf:
                extracted_text = rf.read()

        if not extracted_text:
            if isinstance(result, tuple) and len(result) > 0:
                final_state = result[0]
            else:
                final_state = result

            if isinstance(final_state, dict):
                parts = [f"### {k}\n{v}" for k, v in final_state.items() if isinstance(v, str) and v.strip()]
                extracted_text = "\n\n".join(parts)
            elif isinstance(final_state, str):
                extracted_text = final_state

        task_dict["report_content"] = extracted_text
        task_dict["status"] = "complete"

    except Exception as e:
        task_dict["status"] = "error"
        task_dict["error_msg"] = str(e)

# ==============================================================================
# 4. 상태 기반 정밀 섹션 파서 (신규 헤더 & 레거시 동시 지원)
# ==============================================================================
def parse_full_report_statefully(raw_text: str, fallback_ticker: str = "UNKNOWN") -> dict:
    if not raw_text:
        return {
            "ticker": fallback_ticker,
            "decision": "NEUTRAL",
            "bias_label": "신호 혼재 및 관망",
            "final_strategy": "리포트 내용이 없습니다.",
            "scores": {"Fundamental": 50, "Technical": 50, "Sentiment": 50, "News": 50},
            "domains": {},
            "cleaned_full": ""
        }

    # 주요 상위 섹션 정의 (컴플라이언스 신규 헤더 Integrated Market Perspectives 최우선 반영)
    section_patterns = [
        (re.compile(r'^(?:#+\s*)?(?:past_context|instrument_context|trade_date|sender|company_of_interest|asset_type)\b', re.I), "ignore"),
        (re.compile(r'^(?:#+\s*)?(?:technical\s*(?:analysis)?(?:\s*analysis)?|market_report)\b', re.I), "technical"),
        (re.compile(r'^(?:#+\s*)?(?:fundamental\s*(?:analysis)?(?:\s*analysis)?)\b', re.I), "fundamental"),
        (re.compile(r'^(?:#+\s*)?(?:news\s*(?:analysis)?(?:\s*analysis)?)\b', re.I), "news"),
        (re.compile(r'^(?:#+\s*)?(?:sentiment\s*(?:analysis)?(?:\s*analysis)?)\b', re.I), "sentiment"),
        # 신규 Integrated Market Perspectives 및 Multi-Agent Consensus, 레거시 헤더 포괄
        (re.compile(r'^(?:#+\s*)?(?:integrated\s*market\s*perspectives|multi-agent\s*consensus|final_trade_decision|final\s*execution|최종\s*종합|investment_plan)\b', re.I), "final_strategy"),
        (re.compile(r'^(?:#+\s*)?(?:trader_investment_plan|trader(?:\'s)?\s*(?:initial\s*)?strategy)\b', re.I), "trader_plan")
    ]

    sections = {
        "technical": [],
        "fundamental": [],
        "news": [],
        "sentiment": [],
        "final_strategy": [],
        "trader_plan": [],
        "general": []
    }

    current_sec = "general"
    lines = raw_text.splitlines()

    for line in lines:
        stripped = line.strip()
        matched_sec = None
        for pat, s_name in section_patterns:
            clean_l = re.sub(r'^[#*=\-\s]+', '', stripped)
            if pat.search(stripped) or pat.search(clean_l):
                matched_sec = s_name
                break

        if matched_sec is not None:
            current_sec = matched_sec
            continue

        if current_sec != "ignore":
            sections[current_sec].append(line)

    sec_texts = {k: "\n".join(v).strip() for k, v in sections.items()}

    # 최종 요약 텍스트 합성
    strategy_parts = []
    if sec_texts["final_strategy"]:
        strategy_parts.append(sec_texts["final_strategy"])
    if sec_texts["trader_plan"]:
        strategy_parts.append(f"### Trader Perspective\n{sec_texts['trader_plan']}")
    if not strategy_parts and sec_texts["general"]:
        strategy_parts.append(sec_texts["general"])

    combined_strategy = "\n\n".join(strategy_parts).strip()

    # 컨센서스 및 관점 추출 (MULTI-AGENT CONSENSUS 및 레거시 태그 병행 파싱)
    decision = "NEUTRAL"
    bias_label = "신호 혼재 및 관망"

    cons_m = re.search(r'MULTI-AGENT CONSENSUS:\s*\*\*?([A-Za-z /_\-]+)\*\*?', raw_text, re.IGNORECASE)
    bias_m = re.search(r'종합\s*(?:분석\s*)?관점\s*[:：]\s*\*\*?([^\n\*]+)\*\*?', raw_text, re.IGNORECASE)

    if cons_m:
        decision = cons_m.group(1).upper().strip()
        if bias_m:
            bias_label = bias_m.group(1).strip()
        else:
            if any(w in decision for w in ["BULLISH", "BUY", "OVERWEIGHT"]):
                bias_label = "상승 신호 우세"
            elif any(w in decision for w in ["BEARISH", "SELL", "UNDERWEIGHT"]):
                bias_label = "하방 리스크 경계"
            else:
                bias_label = "신호 혼재 및 균형"
    else:
        # 레거시 폴백 탐색
        dec_m = (
            re.search(r'FINAL TRANSACTION PROPOSAL:\s*\*\*?([A-Za-z_ ]+)\*\*?', raw_text, re.IGNORECASE) or
            re.search(r'Recommendation\s*[:：]\s*\*\*?([A-Za-z_ ]+)\*\*?', raw_text, re.IGNORECASE) or
            re.search(r'최종\s*(?:투자의견|결정)\s*[:：]\s*\*\*?([A-Za-z_ ]+)\*\*?', raw_text, re.IGNORECASE) or
            re.search(r'\b(BUY|HOLD|SELL|UNDERWEIGHT|OVERWEIGHT)\b', raw_text)
        )
        if dec_m:
            decision = dec_m.group(1).upper().strip()
            if any(w in decision for w in ["BUY", "OVERWEIGHT"]):
                bias_label = "상승 신호 우세"
            elif any(w in decision for w in ["SELL", "UNDERWEIGHT"]):
                bias_label = "하방 리스크 경계"

    # 각 도메인 점수 및 텍스트 빌드
    def build_domain_info(sec_key, default_bull):
        d_text = sec_texts.get(sec_key, "")
        bull = default_bull
        bear = 100 - default_bull

        if d_text:
            s_m = (
                re.search(r'Bull\s*Score\s*[:：]?\s*📈?\s*(\d+)\s*/\s*Bear\s*Score\s*[:：]?\s*📉?\s*(\d+)', d_text, re.I) or
                re.search(r'Bull\s*Score\s*[:：]?\s*📈?\s*(\d+)', d_text, re.I) or
                re.search(r'Bull\s*[:：]?\s*(\d+)\s*/\s*Bear\s*[:：]?\s*(\d+)', d_text, re.I)
            )
            if s_m:
                try:
                    bull = int(s_m.group(1))
                    bear = int(s_m.group(2)) if len(s_m.groups()) > 1 and s_m.group(2) else 100 - bull
                except Exception:
                    pass

        return {
            "text": d_text if d_text else "상세 분석 내용이 작성되었습니다.",
            "bull": bull,
            "bear": bear
        }

    domains = {
        "Technical": build_domain_info("technical", 50),
        "News": build_domain_info("news", 50),
        "Sentiment": build_domain_info("sentiment", 50),
        "Fundamental": build_domain_info("fundamental", 50)
    }

    scores = {k: v["bull"] for k, v in domains.items()}

    # TXT 다운로드 파일 조립
    clean_download_blocks = [
        f"=== {fallback_ticker} MULTI-AGENT RESEARCH & CONSENSUS REPORT ===",
        f"Date: {datetime.date.today()}",
        f"Multi-Agent Consensus: {decision} ({bias_label})\n"
    ]
    if combined_strategy:
        clean_download_blocks.append(f"--- [INTEGRATED MARKET PERSPECTIVES & SCENARIOS] ---\n{combined_strategy}\n")
    for d_name, d_val in domains.items():
        clean_download_blocks.append(f"--- [{d_name.upper()} ANALYSIS (Bull: {d_val['bull']} / Bear: {d_val['bear']})] ---\n{d_val['text']}\n")

    clean_download_blocks.append(
        "--- [LEGAL DISCLAIMER] ---\n"
        "This report is an automated quantitative research summary synthesized by AI multi-agents "
        "based on publicly available market data. It does NOT constitute financial advice or trade recommendations.\n"
        "본 보고서는 AI 멀티 에이전트 시스템이 공시 데이터 및 기술 지표를 바탕으로 자동 생성한 "
        "정량적 관측 요약본이며, 금융투자상품의 매수/매도를 권유하거나 투자 자문을 제공하지 않습니다. "
        "모든 투자 판단과 책임은 투자자 본인에게 있습니다."
    )

    cleaned_full_download = "\n".join(clean_download_blocks)

    return {
        "ticker": fallback_ticker,
        "decision": decision,
        "bias_label": bias_label,
        "final_strategy": combined_strategy,
        "scores": scores,
        "domains": domains,
        "cleaned_full": cleaned_full_download
    }

# ==============================================================================
# 5. 4대 도메인 밸런스 레이더 차트
# ==============================================================================
def create_radar_chart(scores: dict, ticker: str) -> go.Figure:
    categories = ["펀더멘털", "기술적 분석", "뉴스/이슈", "소셜 심리"]
    values = [
        scores.get("Fundamental", 50),
        scores.get("Technical", 50),
        scores.get("News", 50),
        scores.get("Sentiment", 50)
    ]
    
    categories_closed = categories + [categories[0]]
    values_closed = values + [values[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values_closed,
        theta=categories_closed,
        fill='toself',
        fillcolor='rgba(38, 166, 154, 0.25)',
        line=dict(color='#26a69a', width=2),
        name=ticker
    ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(color="#888", size=9), gridcolor="rgba(255,255,255,0.1)"),
            angularaxis=dict(tickfont=dict(size=11, color="#ddd"), gridcolor="rgba(255,255,255,0.1)")
        ),
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=35, r=35, t=25, b=25),
        height=260,
        showlegend=False
    )
    return fig

# ==============================================================================
# 6. 사이드바 제어 영역
# ==============================================================================
st.sidebar.title("🤖 BBstock Control")

sidebar_ticker = st.sidebar.text_input("분석 종목 티커", value=st.session_state["active_ticker"]).upper().strip()
analysis_date = st.sidebar.date_input("분석 기준 일자", datetime.date.today())

run_button = st.sidebar.button("🚀 AI 심층 분석 실행", type="primary", use_container_width=True)

st.sidebar.markdown("---")
st.sidebar.subheader("📂 기존 리포트 불러오기")

report_files = (
    glob.glob("stock_db/**/*.txt", recursive=True) + 
    glob.glob("stock_db/**/*.md", recursive=True) + 
    glob.glob("results/**/*.txt", recursive=True) + 
    glob.glob("results/**/*.md", recursive=True)
)
report_files = [f for f in set(report_files) if os.path.isfile(f)]

report_options = {"-- 새로 생성 또는 직접 입력 종목 보기 --": None}
for path in sorted(report_files, key=os.path.getmtime, reverse=True):
    name = os.path.basename(path)
    report_options[name] = path

selected_report_name = st.sidebar.selectbox("저장된 리포트 목록", list(report_options.keys()))

if run_button:
    if not sidebar_ticker:
        st.error("티커를 입력하세요.")
    else:
        st.session_state["active_ticker"] = sidebar_ticker
        st.session_state["analysis_task"]["status"] = "running"
        st.session_state["analysis_task"]["ticker"] = sidebar_ticker
        st.session_state["analysis_task"]["report_content"] = ""
        st.session_state["analysis_task"]["report_path"] = None
        st.session_state["analysis_task"]["error_msg"] = ""
        st.session_state["analysis_task"]["start_time"] = time.time()
        
        date_str = analysis_date.strftime("%Y-%m-%d")
        t = threading.Thread(
            target=_run_analysis_worker,
            args=(st.session_state["analysis_task"], sidebar_ticker, date_str),
            daemon=True
        )
        t.start()

if selected_report_name and report_options[selected_report_name]:
    sel_path = report_options[selected_report_name]
    st.session_state["analysis_task"]["report_path"] = sel_path
    st.session_state["analysis_task"]["status"] = "complete"
    try:
        with open(sel_path, "r", encoding="utf-8") as f:
            st.session_state["analysis_task"]["report_content"] = f.read()
    except Exception:
        pass
    t_match = re.search(r'\[(.*?)\]', selected_report_name) or re.search(r'([A-Za-z]+)', selected_report_name)
    if t_match:
        st.session_state["active_ticker"] = t_match.group(1).upper()

current_ticker = st.session_state["active_ticker"]

# ==============================================================================
# 7. 메인 대시보드 화면
# ==============================================================================
st.title(f"📊 {current_ticker} AI Research & Strategic Intelligence")

# ------------------------------------------------------------------------------
# 섹션 A: 독립 실시간 시세 차트
# ------------------------------------------------------------------------------
@st.fragment
def render_chart_component(ticker: str):
    c_head, c_slider = st.columns([1.5, 1])
    with c_head:
        st.markdown("#### 📈 실시간 시세 및 기술적 지표")
    with c_slider:
        lookback = st.slider("조회 기간 (일수)", min_value=30, max_value=365, value=180, step=30, key="chart_slider")

    df = fetch_cached_chart_data(ticker, lookback)

    if not df.empty:
        latest = df.iloc[-1]
        prev_close = df.iloc[-2]["Close"] if len(df) > 1 else latest["Close"]
        price_change = latest["Close"] - prev_close
        pct_change = (price_change / prev_close) * 100

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("최신 종가", f"${latest['Close']:.2f}", f"{pct_change:+.2f}%")
        col2.metric("10 EMA", f"${latest['EMA10']:.2f}")
        col3.metric("20 EMA", f"${latest['EMA20']:.2f}")
        col4.metric("볼린저 상단", f"${latest['BB_UPPER']:.2f}")
        col5.metric("볼린저 하단", f"${latest['BB_LOWER']:.2f}")

        fig = build_interactive_chart(df, ticker)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(f"💡 {ticker} 시세 데이터를 조회할 수 없습니다. Market Data 설정을 확인하세요.")

render_chart_component(current_ticker)

st.markdown("---")

# ------------------------------------------------------------------------------
# 섹션 B: 종합 리서치 리포트 & 4대 도메인별 세부 분석
# ------------------------------------------------------------------------------
task = st.session_state["analysis_task"]
is_running = (task["status"] == "running")

@st.fragment(run_every=2 if is_running else None)
def render_report_component(ticker: str):
    cur_task = st.session_state["analysis_task"]

    if cur_task["status"] == "running":
        elapsed = int(time.time() - cur_task["start_time"])
        st.info(f"⏳ **{cur_task['ticker']}** 4대 애널리스트 및 리스크 관리팀 심층 분석 진행 중... (경과 시간: {elapsed}초)\n\n"
                "👉 분석 중에도 상단 차트를 자유롭게 조작하실 수 있습니다.")
        return

    if cur_task["status"] == "error":
        st.error(f"❌ 분석 오류: {cur_task['error_msg']}")
        return

    report_text = cur_task.get("report_content", "")
    target_path = cur_task.get("report_path")

    if not report_text and target_path and os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                report_text = f.read()
        except Exception:
            pass

    if report_text:
        parsed = parse_full_report_statefully(report_text, fallback_ticker=ticker)

        # 1. 헤더: 컨센서스 배지 & 리포트 TXT 다운로드 버튼
        head_l, head_r = st.columns([1.5, 1])
        with head_l:
            st.subheader("📑 AI 멀티 에이전트 종합 리서치 요약")
        with head_r:
            today_str = datetime.date.today().strftime("%Y%m%d")
            st.download_button(
                label="📥 리포트 전문 (.txt) 다운로드",
                data=parsed["cleaned_full"],
                file_name=f"{ticker}_AI_Research_Report_{today_str}.txt",
                mime="text/plain",
                use_container_width=True
            )

        dec = parsed["decision"]
        bias_lbl = parsed["bias_label"]
        pill_class = "pill-hold"
        
        # 배지 색상 매핑
        if any(w in dec for w in ["BUY", "OVERWEIGHT", "BULLISH"]):
            pill_class = "pill-buy"
        elif any(w in dec for w in ["SELL", "UNDERWEIGHT", "BEARISH"]):
            pill_class = "pill-sell"

        display_badge_text = f"{dec} ({bias_lbl})" if bias_lbl else dec

        # 2. 요약 + 레이더 차트
        r_col1, r_col2 = st.columns([1.2, 0.8])
        with r_col1:
            st.markdown(
                f"""
                <div class="decision-container">
                    <span class="decision-label">MULTI-AGENT CONSENSUS</span>
                    <span class="decision-pill {pill_class}">{display_badge_text}</span>
                </div>
                """,
                unsafe_allow_html=True
            )
            # 종합 관점 및 시장 레짐 서술
            st.markdown(
                f"""
                <div class="strategy-card">
                    {parsed['final_strategy']}
                </div>
                """,
                unsafe_allow_html=True
            )

        with r_col2:
            st.markdown("<div style='text-align: center; font-size: 13px; color: #888; margin-bottom: 4px;'><b>4대 도메인 신호 밸런스 레이더</b></div>", unsafe_allow_html=True)
            radar_fig = create_radar_chart(parsed["scores"], ticker)
            st.plotly_chart(radar_fig, use_container_width=True)

        st.markdown("---")

        # 3. 도메인별 2x2 카드 (잘림 없는 전체 텍스트 렌더링)
        st.markdown("### 🔍 4대 도메인별 세부 분석 및 관측 데이터")

        d_col1, d_col2 = st.columns(2)

        # 기술적 분석 카드
        with d_col1:
            tech = parsed["domains"]["Technical"]
            with st.expander("📈 기술적 분석 (Technical Analysis)", expanded=True):
                st.markdown(
                    f'<div class="score-badge">Bull Score: 📈 <b>{tech["bull"]}</b> / Bear: 📉 <b>{tech["bear"]}</b></div>',
                    unsafe_allow_html=True
                )
                st.markdown(tech["text"])

        # 뉴스 & 매크로 분석 카드
        with d_col2:
            news = parsed["domains"]["News"]
            with st.expander("📰 뉴스 및 매크로 분석 (Macro & News)", expanded=True):
                st.markdown(
                    f'<div class="score-badge">Bull Score: 📈 <b>{news["bull"]}</b> / Bear: 📉 <b>{news["bear"]}</b></div>',
                    unsafe_allow_html=True
                )
                st.markdown(news["text"])

        d_col3, d_col4 = st.columns(2)

        # 소셜 심리 분석 카드
        with d_col3:
            sent = parsed["domains"]["Sentiment"]
            with st.expander("💬 소셜 심리 분석 (Social Sentiment)", expanded=True):
                st.markdown(
                    f'<div class="score-badge">Bull Score: 📈 <b>{sent["bull"]}</b> / Bear: 📉 <b>{sent["bear"]}</b></div>',
                    unsafe_allow_html=True
                )
                st.markdown(sent["text"])

        # 기업 펀더멘털 분석 카드
        with d_col4:
            fund = parsed["domains"]["Fundamental"]
            with st.expander("🏢 기업 펀더멘털 분석 (Fundamental Analysis)", expanded=True):
                st.markdown(
                    f'<div class="score-badge">Bull Score: 📈 <b>{fund["bull"]}</b> / Bear: 📉 <b>{fund["bear"]}</b></div>',
                    unsafe_allow_html=True
                )
                st.markdown(fund["text"])

        # 4. 하단 고정 법적 면책 고지 배너 (Regulatory Disclaimer)
        st.markdown(
            """
            <div class="disclaimer-banner">
                ⚠️ <b>법적 고지 (Regulatory Disclaimer)</b><br>
                본 대시보드가 제공하는 분석 요약, 통계 지표 및 에이전트 리포트는 공개 시장 데이터를 바탕으로 알고리즘이 자동 생성한 정량 참고 자료입니다. 
                어떠한 경우에도 금융투자상품의 매매 권유나 개별 투자 자문을 제공하지 않으며, 특정 수익률이나 원금 보전을 보장하지 않습니다. 
                모든 투자 결정과 그에 따른 책임은 투자자 본인에게 있습니다.
            </div>
            """,
            unsafe_allow_html=True
        )

    else:
        st.info("👈 좌측 사이드바에서 티커를 입력하고 **[🚀 AI 심층 분석 실행]** 버튼을 누르면 새로운 분석 리포트가 생성됩니다.")

render_report_component(current_ticker)