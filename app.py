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
# 1. 페이지 설정
# ==============================================================================
st.set_page_config(
    page_title="HEYstock | Quantitative Research Desk",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==============================================================================
# 2. 전역 상태 (다크 모드 영구 고정 & 제미나이 사이드바 레일)
# ==============================================================================
DEFAULTS = {
    "active_ticker": "GOOG",
    "recent_tickers": ["GOOG", "AAPL", "NVDA", "TSLA", "MSFT", "AMZN"],
    "sidebar_collapsed": False,
    "analysis_task": {
        "status": "idle",
        "ticker": "",
        "report_content": "",
        "report_path": None,
        "error_msg": "",
        "start_time": 0,
    },
}
for _k, _v in DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v.copy() if isinstance(_v, dict) else _v


def remember_ticker(ticker: str) -> None:
    """최근 분석한 6개 종목 코드를 세션에 보존."""
    normalized = ticker.strip().upper()
    if not normalized:
        return
    recent = [item for item in st.session_state.get("recent_tickers", []) if item != normalized]
    st.session_state["recent_tickers"] = [normalized, *recent][:6]


# ==============================================================================
# 3. 테마 토큰 및 제미나이 스타일 레일 애니메이션 CSS
# ==============================================================================
TOKENS = dict(
    bg="#0b0e14",
    surface="#12161f",
    surface_hi="#1b2230",
    card_bg="#12161f",
    input_bg="#161b26",
    border="rgba(255,255,255,0.12)",
    text="#f1f5f9",
    text_soft="#94a3b8",
    text_mute="#64748b",
    accent="#0d9488",
    accent_soft="rgba(13,148,136,0.15)",
    shadow="0 6px 20px rgba(0,0,0,0.45)",
    plotly="plotly_dark",
    grid="rgba(255,255,255,0.08)",
    tag_bg="#152a2a",
    tag_border="rgba(45, 212, 191, 0.38)",
    tag_text="#5eead4",
    bull_border="rgba(16,185,129,0.35)",
    bull_bg="rgba(16,185,129,0.06)",
    bull_text="#34d399",
    neutral_border="rgba(59,130,246,0.35)",
    neutral_bg="rgba(59,130,246,0.06)",
    neutral_text="#60a5fa",
    bear_border="rgba(239,68,68,0.35)",
    bear_bg="rgba(239,68,68,0.06)",
    bear_text="#f87171",
)

SIDEBAR_WIDTH = "78px" if st.session_state["sidebar_collapsed"] else "320px"

st.markdown(
    f"""
<style>
:root {{
  --bb-bg: {TOKENS['bg']};
  --bb-surface: {TOKENS['surface']};
  --bb-surface-hi: {TOKENS['surface_hi']};
  --bb-card-bg: {TOKENS['card_bg']};
  --bb-input-bg: {TOKENS['input_bg']};
  --bb-border: {TOKENS['border']};
  --bb-text: {TOKENS['text']};
  --bb-text-soft: {TOKENS['text_soft']};
  --bb-text-mute: {TOKENS['text_mute']};
  --bb-accent: {TOKENS['accent']};
  --bb-accent-soft: {TOKENS['accent_soft']};
  --bb-shadow: {TOKENS['shadow']};

  --sc-tag-bg: {TOKENS['tag_bg']};
  --sc-tag-border: {TOKENS['tag_border']};
  --sc-tag-text: {TOKENS['tag_text']};

  --sc-bull-border: {TOKENS['bull_border']};
  --sc-bull-bg: {TOKENS['bull_bg']};
  --sc-bull-text: {TOKENS['bull_text']};
  --sc-neu-border: {TOKENS['neutral_border']};
  --sc-neu-bg: {TOKENS['neutral_bg']};
  --sc-neu-text: {TOKENS['neutral_text']};
  --sc-bear-border: {TOKENS['bear_border']};
  --sc-bear-bg: {TOKENS['bear_bg']};
  --sc-bear-text: {TOKENS['bear_text']};
}}

html, body, [class*="css"] {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
}}

/* 전체 배경 및 텍스트 기본값 */
.stApp,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > .main,
section.main,
[data-testid="stMainBlockContainer"],
.block-container,
[data-testid="stHeader"],
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div:first-child,
[data-testid="stSidebarContent"] {{
  background-color: var(--bb-bg) !important;
  color: var(--bb-text) !important;
}}

/* Streamlit 기본 접기/펼치기 제어 비활성화 */
[data-testid="stSidebarCollapsedControl"],
[data-testid="stSidebarCollapseButton"] {{
  display: none !important;
}}

/* -------------------------------------------------------------------------- */
/* 제미나이 스타일 사이드바 레일 및 부드러운 애니메이션                       */
/* -------------------------------------------------------------------------- */
[data-testid="stSidebar"] {{
  width: {SIDEBAR_WIDTH} !important;
  min-width: {SIDEBAR_WIDTH} !important;
  max-width: {SIDEBAR_WIDTH} !important;
  border-right: 1px solid var(--bb-border) !important;
  transition: width 0.32s cubic-bezier(0.2, 0.8, 0.2, 1),
              min-width 0.32s cubic-bezier(0.2, 0.8, 0.2, 1),
              max-width 0.32s cubic-bezier(0.2, 0.8, 0.2, 1) !important;
  overflow-x: hidden !important;
}}

[data-testid="stSidebarContent"] {{
  width: {SIDEBAR_WIDTH} !important;
  min-width: {SIDEBAR_WIDTH} !important;
  max-width: {SIDEBAR_WIDTH} !important;
  padding: {"12px 8px !important" if st.session_state["sidebar_collapsed"] else "16px 14px !important"};
  transition: width 0.32s cubic-bezier(0.2, 0.8, 0.2, 1),
              padding 0.25s ease !important;
  overflow-x: hidden !important;
}}

section.main {{
  transition: margin-left 0.32s cubic-bezier(0.2, 0.8, 0.2, 1),
              width 0.32s cubic-bezier(0.2, 0.8, 0.2, 1) !important;
}}

/* 제미나이 캡슐형 팝업 토글 버튼 */
.gemini-pill-btn button {{
  border-radius: 20px !important;
  padding: 5px 12px !important;
  background-color: var(--bb-card-bg) !important;
  border: 1px solid var(--bb-border) !important;
  box-shadow: var(--bb-shadow) !important;
  font-weight: 600 !important;
  font-size: 11px !important;
  letter-spacing: .02em !important;
}}

.rail-btn button {{
  border-radius: 8px !important;
  padding: 8px 4px !important;
  background-color: var(--bb-surface) !important;
  border: 1px solid var(--bb-border) !important;
  font-size: 11px !important;
  font-weight: 700 !important;
  margin-bottom: 6px !important;
  transition: transform 0.15s ease, background-color 0.15s ease !important;
}}
.rail-btn button:hover {{
  transform: translateY(-1px) !important;
  background-color: var(--bb-surface-hi) !important;
  border-color: var(--bb-accent) !important;
}}

/* -------------------------------------------------------------------------- */
/* 접기 메뉴 (Expander) 다크 고정                                             */
/* -------------------------------------------------------------------------- */
[data-testid="stExpander"] {{
  background-color: var(--bb-card-bg) !important;
  border: 1px solid var(--bb-border) !important;
  border-radius: 8px !important;
  overflow: hidden !important;
  margin-bottom: 10px !important;
}}

[data-testid="stExpander"] details {{
  background-color: transparent !important;
}}

[data-testid="stExpander"] summary {{
  background-color: var(--bb-surface) !important;
  color: var(--bb-text) !important;
  border-bottom: 1px solid var(--bb-border) !important;
  padding: 10px 14px !important;
  font-weight: 600 !important;
  font-size: 12.5px !important;
}}

[data-testid="stExpander"] summary:hover {{
  background-color: var(--bb-surface-hi) !important;
}}

[data-testid="stExpander"] summary * {{
  color: var(--bb-text) !important;
  fill: var(--bb-text) !important;
}}

/* 드롭다운 (Selectbox) 및 입력 컨트롤 */
[data-baseweb="select"] {{
  background-color: var(--bb-input-bg) !important;
  border-radius: 6px !important;
}}

[data-baseweb="select"] > div {{
  background-color: var(--bb-input-bg) !important;
  color: var(--bb-text) !important;
  border: 1px solid var(--bb-border) !important;
}}

[data-baseweb="select"] * {{
  color: var(--bb-text) !important;
  fill: var(--bb-text) !important;
}}

[data-baseweb="popover"],
[data-baseweb="menu"],
[role="listbox"] {{
  background-color: var(--bb-card-bg) !important;
  color: var(--bb-text) !important;
  border: 1px solid var(--bb-border) !important;
}}

[data-baseweb="menu"] li,
[role="option"] {{
  background-color: var(--bb-card-bg) !important;
  color: var(--bb-text) !important;
}}

[data-baseweb="menu"] li:hover,
[role="option"]:hover {{
  background-color: var(--bb-surface-hi) !important;
}}

[data-testid="stTextInput"] input,
[data-testid="stDateInput"] input,
[data-testid="stNumberInput"] input {{
  background-color: var(--bb-input-bg) !important;
  color: var(--bb-text) !important;
  border: 1px solid var(--bb-border) !important;
  border-radius: 6px !important;
}}

input::placeholder,
[data-testid="stTextInput"] input::placeholder {{
  color: var(--bb-text-mute) !important;
  opacity: 1 !important;
}}

/* 버튼 기본 스타일 */
.stButton > button {{
  background-color: var(--bb-card-bg) !important;
  color: var(--bb-text) !important;
  border: 1px solid var(--bb-border) !important;
  border-radius: 6px !important;
  font-size: 11.5px !important;
  font-weight: 600 !important;
  white-space: nowrap !important;
  padding: 6px 4px !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
}}

.stButton > button:hover {{
  background-color: var(--bb-surface-hi) !important;
  border-color: var(--bb-accent) !important;
}}

.stButton > button[kind="primary"] {{
  background-color: var(--bb-accent) !important;
  color: #ffffff !important;
  border-color: var(--bb-accent) !important;
}}

/* 브랜드 헤더 */
.bb-brand {{
  display: flex; align-items: center; gap: 10px;
  padding: 2px 0 14px; border-bottom: 1px solid var(--bb-border); margin-bottom: 12px;
}}
.bb-logo-icon {{
  width: 30px; height: 30px; border-radius: 6px;
  background: var(--bb-accent); color: #ffffff;
  display: flex; align-items: center; justify-content: center;
  font-family: ui-monospace, SFMono-Regular, monospace; font-size: 13px; font-weight: 800;
}}
.bb-brand strong {{ font-size: 14.5px; letter-spacing: -0.02em; display: block; }}
.bb-brand span {{ font-size: 10px; color: var(--bb-text-mute); text-transform: uppercase; letter-spacing: .08em; display: block; }}

/* 상단 히어로 배너 */
.bb-hero {{
  display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
  padding: 14px 18px; margin-bottom: 12px; border-radius: 8px;
  border: 1px solid var(--bb-border); background-color: var(--bb-card-bg);
  box-shadow: var(--bb-shadow);
}}
.bb-hero h1 {{ font-size: 19px; margin: 0; font-weight: 700; }}
.bb-hero .bb-sub {{ font-size: 12px; color: var(--bb-text-soft); margin-top: 2px; }}
.bb-chip {{
  font-size: 11px; font-weight: 600; padding: 4px 9px; border-radius: 4px;
  background: var(--bb-surface-hi); color: var(--bb-text-soft); border: 1px solid var(--bb-border);
  font-family: ui-monospace, monospace;
}}

/* 메트릭 카드 */
[data-testid="stMetric"] {{
  background-color: var(--bb-card-bg) !important;
  border: 1px solid var(--bb-border) !important;
  border-radius: 8px !important;
  padding: 12px 14px !important;
  box-shadow: var(--bb-shadow);
}}
[data-testid="stMetricLabel"] * {{ color: var(--bb-text-soft) !important; font-size: 11px !important; text-transform: uppercase; }}
[data-testid="stMetricValue"] * {{ color: var(--bb-text) !important; font-family: ui-monospace, SFMono-Regular, monospace; }}

/* 의사결정 배지 */
.decision-container {{
  display: inline-flex; align-items: center; gap: 10px;
  background-color: var(--bb-card-bg); padding: 5px 12px; border-radius: 6px;
  border: 1px solid var(--bb-border); margin-bottom: 12px; box-shadow: var(--bb-shadow);
}}
.decision-label {{ font-size: 11px; font-weight: 600; color: var(--bb-text-mute); letter-spacing: .06em; text-transform: uppercase; }}
.decision-pill {{ font-size: 12px; font-weight: 700; padding: 3px 10px; border-radius: 4px; }}
.pill-hold {{ background: rgba(245,158,11,.15); color: #fbbf24; border: 1px solid rgba(245,158,11,.3); }}
.pill-buy  {{ background: rgba(16,185,129,.15); color: #34d399; border: 1px solid rgba(16,185,129,.3); }}
.pill-sell {{ background: rgba(239,68,68,.15);  color: #f87171; border: 1px solid rgba(239,68,68,.3); }}

/* 3초 퀵 펄스 해시태그 칩 */
.pulse-tag-group {{
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 14px;
}}
.pulse-tag {{
  display: inline-flex; align-items: center; font-size: 12px; font-weight: 600;
  padding: 5px 12px; border-radius: 6px;
  background-color: var(--sc-tag-bg) !important;
  color: var(--sc-tag-text) !important;
  border: 1px solid var(--sc-tag-border) !important;
  font-family: ui-monospace, SFMono-Regular, monospace;
  letter-spacing: -0.01em;
  box-shadow: 0 1px 3px rgba(0,0,0,0.12);
}}
.pulse-tag-lead {{
  font-size: 11px; font-weight: 700; color: var(--bb-text-soft); text-transform: uppercase;
  margin-right: 2px; letter-spacing: .06em;
}}

/* 3분할 시나리오 맵 박스 */
.scenario-box {{
  border-radius: 8px; padding: 15px; margin-bottom: 12px; min-height: 190px;
  display: flex; flex-direction: column; justify-content: flex-start;
  box-shadow: var(--bb-shadow);
}}
.sc-bull {{ border: 1px solid var(--sc-bull-border); background-color: var(--sc-bull-bg); }}
.sc-neu  {{ border: 1px solid var(--sc-neu-border); background-color: var(--sc-neu-bg); }}
.sc-bear {{ border: 1px solid var(--sc-bear-border); background-color: var(--sc-bear-bg); }}
.sc-title {{ font-size: 12.5px; font-weight: 700; margin-bottom: 6px; text-transform: uppercase; }}
.sc-bull .sc-title {{ color: var(--sc-bull-text); }}
.sc-neu .sc-title  {{ color: var(--sc-neu-text); }}
.sc-bear .sc-title {{ color: var(--sc-bear-text); }}
.sc-body {{ font-size: 13px; line-height: 1.65; color: var(--bb-text); opacity: .95; white-space: pre-wrap; }}

/* 카드 및 아레나 */
.strategy-card {{
  background-color: var(--bb-card-bg); border: 1px solid var(--bb-border);
  border-radius: 8px; padding: 15px 18px; font-size: 13.5px; line-height: 1.7; color: var(--bb-text);
  margin-bottom: 14px; box-shadow: var(--bb-shadow);
}}
.strategy-card b {{ color: var(--bb-text-soft); font-size: 11px; text-transform: uppercase; display: block; margin-bottom: 4px; }}
.arena-card {{
  background-color: var(--bb-card-bg); border: 1px solid var(--bb-border);
  border-radius: 6px; padding: 12px 15px; margin-bottom: 8px; font-size: 13px; line-height: 1.65;
}}
.arena-speaker {{ font-size: 11px; font-weight: 700; text-transform: uppercase; margin-bottom: 4px; font-family: ui-monospace, monospace; }}
.score-badge {{
  font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 4px;
  background-color: var(--bb-surface-hi); color: var(--bb-text-soft);
  border: 1px solid var(--bb-border); display: inline-block; margin: 4px 0 8px;
  font-family: ui-monospace, monospace;
}}

/* 세부 분석 내부 글씨 크기 가드레일 */
[data-testid="stExpander"] h1,
[data-testid="stExpander"] h2,
[data-testid="stExpander"] h3,
[data-testid="stExpander"] h4 {{
  font-size: 13.5px !important;
  font-weight: 600 !important;
  margin: 10px 0 4px !important;
  line-height: 1.4 !important;
  color: var(--bb-text) !important;
}}
[data-testid="stExpander"] p, [data-testid="stExpander"] div {{
  font-size: 13px !important;
  line-height: 1.68 !important;
}}

.bb-running {{
  border-radius: 8px; padding: 14px 16px; border: 1px solid var(--bb-border);
  color: var(--bb-text); background-color: var(--bb-card-bg); font-size: 13px;
}}
.bb-empty {{
  text-align: center; padding: 40px 20px; border-radius: 8px;
  border: 1px dashed var(--bb-border); background-color: var(--bb-card-bg);
  color: var(--bb-text-soft); font-size: 13px;
}}
.disclaimer-banner {{
  margin-top: 28px; padding: 12px 16px; background-color: var(--bb-card-bg);
  border: 1px solid var(--bb-border); border-radius: 6px;
  font-size: 11.5px; color: var(--bb-text-mute); line-height: 1.6;
}}
.bb-footer {{
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  margin-top: 32px; padding: 12px 0 4px; border-top: 1px solid var(--bb-border);
  color: var(--bb-text-mute); font-size: 11px; font-family: ui-monospace, monospace;
}}
</style>
""",
    unsafe_allow_html=True,
)


# ==============================================================================
# 4. 데이터 캐싱
# ==============================================================================
@st.cache_data(ttl=300, show_spinner=False)
def fetch_cached_chart_data(ticker: str, days: int) -> pd.DataFrame:
    try:
        provider = MarketDataProvider()
        return provider.fetch_candlestick_data(ticker, days=days)
    except Exception:
        return pd.DataFrame()


# ==============================================================================
# 5. 비동기 백그라운드 분석 워커
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
            f"**/*{ticker}*.*",
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
# 6. 해시태그 정밀 정제 헬퍼 함수
# ==============================================================================
def extract_clean_tags(raw_line: str) -> list[str]:
    if not raw_line:
        return []
    cleaned_line = re.sub(r'[*_`\[\]⚡]', '', raw_line)
    chunks = re.findall(r'#\s*([^#\n,]+)', cleaned_line)
    final_tags = []
    for c in chunks:
        val = c.strip().strip(" -·|/,")
        if not val or val in {"-", "·", "|", "/"}:
            continue
        final_tags.append(f"#{val}")
    if not final_tags:
        for w in cleaned_line.replace(',', ' ').split():
            w = w.strip().lstrip('#').strip(" -·|/,")
            if w:
                final_tags.append(f"#{w}")
    return final_tags


# ==============================================================================
# 7. 상태 기반 섹션 및 시나리오/펄스 파서
# ==============================================================================
def parse_full_report_statefully(raw_text: str, fallback_ticker: str = "UNKNOWN") -> dict:
    if not raw_text:
        return {
            "ticker": fallback_ticker,
            "decision": "NEUTRAL",
            "bias_label": "신호 혼재 및 관망",
            "executive_pulse": [],
            "risk_synthesis": "",
            "scenarios": {"bull": "", "neutral": "", "bear": ""},
            "investment_thesis": "",
            "final_strategy": "리포트 데이터가 존재하지 않습니다.",
            "scores": {"Fundamental": 50, "Technical": 50, "Sentiment": 50, "News": 50},
            "domains": {},
            "arena_debate": [],
            "cleaned_full": "",
        }

    section_patterns = [
        (re.compile(r'^(?:#+\s*)?(?:past_context|instrument_context|trade_date|sender|company_of_interest|asset_type)\b', re.I), "ignore"),
        (re.compile(r'^(?:#+\s*)?(?:technical\s*(?:analysis)?(?:\s*analysis)?|market_report)\b', re.I), "technical"),
        (re.compile(r'^(?:#+\s*)?(?:fundamental\s*(?:analysis)?(?:\s*analysis)?)\b', re.I), "fundamental"),
        (re.compile(r'^(?:#+\s*)?(?:news\s*(?:analysis)?(?:\s*analysis)?)\b', re.I), "news"),
        (re.compile(r'^(?:#+\s*)?(?:sentiment\s*(?:analysis)?(?:\s*analysis)?)\b', re.I), "sentiment"),
        (re.compile(r'^(?:#+\s*)?(?:integrated\s*market\s*perspectives|multi-agent\s*consensus|final_trade_decision|final\s*execution|최종\s*종합|investment_plan)\b', re.I), "final_strategy"),
        (re.compile(r'^(?:#+\s*)?(?:trader_investment_plan|trader(?:\'s)?\s*(?:initial\s*)?strategy)\b', re.I), "trader_plan"),
    ]

    sections = {
        "technical": [], "fundamental": [], "news": [], "sentiment": [],
        "final_strategy": [], "trader_plan": [], "general": [],
    }

    current_sec = "general"
    for line in raw_text.splitlines():
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

    strategy_parts = []
    if sec_texts["final_strategy"]:
        strategy_parts.append(sec_texts["final_strategy"])
    if sec_texts["trader_plan"]:
        strategy_parts.append(f"### Trader Perspective\n{sec_texts['trader_plan']}")
    if not strategy_parts and sec_texts["general"]:
        strategy_parts.append(sec_texts["general"])

    combined_strategy = "\n\n".join(strategy_parts).strip()

    exec_pulse = []
    exec_pulse_m = re.search(r'(?:>\s*)?(?:⚡\s*)?\*\*Executive Pulse\*\*:\s*([^\n]+)', raw_text)
    if exec_pulse_m:
        exec_pulse = extract_clean_tags(exec_pulse_m.group(1))

    scenarios = {"bull": "", "neutral": "", "bear": ""}
    bull_m = re.search(r'1\.\s*\*\*Bullish Extension[^\*]*\*\*:\s*(.*?)(?=\n\s*2\.|\Z)', combined_strategy, re.S)
    neu_m = re.search(r'2\.\s*\*\*Neutral Consolidation[^\*]*\*\*:\s*(.*?)(?=\n\s*3\.|\Z)', combined_strategy, re.S)
    bear_m = re.search(r'3\.\s*\*\*Downside Invalidation[^\*]*\*\*:\s*(.*?)(?=\n\s*\*\*Investment Thesis|\n\s*====|\Z)', combined_strategy, re.S)

    if bull_m:
        scenarios["bull"] = bull_m.group(1).strip()
    if neu_m:
        scenarios["neutral"] = neu_m.group(1).strip()
    if bear_m:
        scenarios["bear"] = bear_m.group(1).strip()

    risk_synth_m = re.search(r'\*\*Risk & Market Synthesis\*\*:\s*(.*?)(?=\n\s*\*\*Strategic Scenario Map|\n\s*1\.|\Z)', combined_strategy, re.S)
    risk_synthesis = risk_synth_m.group(1).strip() if risk_synth_m else ""

    thesis_m = re.search(r'\*\*Investment Thesis\*\*[^\:]*:\s*(.*?)(?=\n\s*====|\Z)', combined_strategy, re.S)
    investment_thesis = thesis_m.group(1).strip() if thesis_m else ""

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
                bias_label = "상승 모멘텀 우세"
            elif any(w in decision for w in ["BEARISH", "SELL", "UNDERWEIGHT"]):
                bias_label = "하방 리스크 경계"
            else:
                bias_label = "신호 혼재 및 균형"
    else:
        dec_m = (
            re.search(r'FINAL TRANSACTION PROPOSAL:\s*\*\*?([A-Za-z_ ]+)\*\*?', raw_text, re.IGNORECASE) or
            re.search(r'Recommendation\s*[:：]\s*\*\*?([A-Za-z_ ]+)\*\*?', raw_text, re.IGNORECASE) or
            re.search(r'최종\s*(?:투자의견|결정)\s*[:：]\s*\*\*?([A-Za-z_ ]+)\*\*?', raw_text, re.IGNORECASE) or
            re.search(r'\b(BUY|HOLD|SELL|UNDERWEIGHT|OVERWEIGHT)\b', raw_text)
        )
        if dec_m:
            decision = dec_m.group(1).upper().strip()
            if any(w in decision for w in ["BUY", "OVERWEIGHT"]):
                bias_label = "상승 모멘텀 우세"
            elif any(w in decision for w in ["SELL", "UNDERWEIGHT"]):
                bias_label = "하방 리스크 경계"

    def build_domain_info(sec_key, default_bull):
        d_text = sec_texts.get(sec_key, "")
        bull = default_bull
        bear = 100 - default_bull
        tags = []

        if d_text:
            tag_m = re.search(r'(?:>\s*)?(?:⚡\s*)?\*\*Quick Pulse\*\*:\s*([^\n]+)', d_text)
            if tag_m:
                tags = extract_clean_tags(tag_m.group(1))

            s_m = (
                re.search(r'Bull\s*Score\s*[:：]?\s*(?:📈\s*)?(\d+)\s*/\s*Bear\s*Score\s*[:：]?\s*(?:📉\s*)?(\d+)', d_text, re.I) or
                re.search(r'Bull\s*Score\s*[:：]?\s*(?:📈\s*)?(\d+)', d_text, re.I) or
                re.search(r'Bull\s*[:：]?\s*(\d+)\s*/\s*Bear\s*[:：]?\s*(\d+)', d_text, re.I)
            )
            if s_m:
                try:
                    bull = int(s_m.group(1))
                    bear = int(s_m.group(2)) if len(s_m.groups()) > 1 and s_m.group(2) else 100 - bull
                except Exception:
                    pass

        cleaned_body = d_text
        cleaned_body = re.sub(r'^###\s*.*Analysis\s*\n?', '', cleaned_body, flags=re.MULTILINE)
        cleaned_body = re.sub(r'(?:>\s*)?(?:⚡\s*)?\*\*Quick Pulse\*\*:[^\n]*\n?', '', cleaned_body)
        cleaned_body = re.sub(r'\*\*Domain Score\*\*:[^\n]*\n?', '', cleaned_body, flags=re.IGNORECASE)
        cleaned_body = re.sub(r'^\s*---\s*$', '', cleaned_body, flags=re.MULTILINE)
        cleaned_body = re.sub(r'^\s*(?:news|sentiment|market|fundamental|technical)_report\s*$', '', cleaned_body, flags=re.MULTILINE | re.IGNORECASE)
        cleaned_body = cleaned_body.strip()

        return {
            "text": cleaned_body if cleaned_body else "세부 관측 데이터가 작성되었습니다.",
            "bull": bull,
            "bear": bear,
            "tags": tags,
        }

    domains = {
        "Technical": build_domain_info("technical", 50),
        "News": build_domain_info("news", 50),
        "Sentiment": build_domain_info("sentiment", 50),
        "Fundamental": build_domain_info("fundamental", 50),
    }

    scores = {k: v["bull"] for k, v in domains.items()}

    arena_turns = []
    speaker_matches = re.finditer(r'(Aggressive|Conservative|Neutral)\s*Analyst\s*[:：]\s*(.*?)(?=(?:Aggressive|Conservative|Neutral)\s*Analyst\s*[:：]|\Z)', raw_text, re.S | re.I)
    for m in speaker_matches:
        spk = m.group(1).capitalize()
        content = m.group(2).strip()
        if content:
            arena_turns.append({"speaker": spk, "text": content})

    clean_download_blocks = [
        f"=== {fallback_ticker} MULTI-AGENT RESEARCH & CONSENSUS REPORT ===",
        f"Date: {datetime.date.today()}",
        f"Multi-Agent Consensus: {decision} ({bias_label})",
    ]
    if exec_pulse:
        clean_download_blocks.append(f"Executive Pulse: {' '.join(exec_pulse)}\n")
    if combined_strategy:
        clean_download_blocks.append(f"--- [INTEGRATED MARKET PERSPECTIVES & SCENARIOS] ---\n{combined_strategy}\n")
    for d_name, d_val in domains.items():
        clean_download_blocks.append(f"--- [{d_name.upper()} ANALYSIS (Bull: {d_val['bull']}% / Bear: {d_val['bear']}%\n{d_val['text']}\n")

    clean_download_blocks.append(
        "--- [REGULATORY NOTICE & COMPLIANCE DISCLAIMER] ---\n"
        "This report is an automated quantitative research summary synthesized by AI multi-agents "
        "based on publicly available market data. It does NOT constitute financial advice or trade recommendations.\n"
        "본 보고서는 AI 멀티 에이전트 시스템이 공시 데이터 및 기술 지표를 바탕으로 자동 생성한 "
        "정량적 관측 요약본이며, 금융투자상품의 매수/매도를 권유하거나 투자 자문을 제공하지 않습니다. "
        "모든 투자 판단과 책임은 투자자 본인에게 있습니다."
    )

    return {
        "ticker": fallback_ticker,
        "decision": decision,
        "bias_label": bias_label,
        "executive_pulse": exec_pulse,
        "risk_synthesis": risk_synthesis,
        "scenarios": scenarios,
        "investment_thesis": investment_thesis,
        "final_strategy": combined_strategy,
        "scores": scores,
        "domains": domains,
        "arena_debate": arena_turns,
        "cleaned_full": "\n".join(clean_download_blocks),
    }


# ==============================================================================
# 8. 레이더 차트
# ==============================================================================
def create_radar_chart(scores: dict, ticker: str) -> go.Figure:
    categories = ["Fundamental", "Technical", "Macro/News", "Sentiment"]
    values = [
        scores.get("Fundamental", 50),
        scores.get("Technical", 50),
        scores.get("News", 50),
        scores.get("Sentiment", 50),
    ]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]],
        theta=categories + [categories[0]],
        fill='toself',
        fillcolor='rgba(13, 148, 136, 0.25)',
        line=dict(color=TOKENS["accent"], width=1.5),
        name=ticker,
    ))

    fig.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                tickfont=dict(color=TOKENS["text_mute"], size=8),
                gridcolor=TOKENS["grid"],
            ),
            angularaxis=dict(
                tickfont=dict(size=10, color=TOKENS["text_soft"]),
                gridcolor=TOKENS["grid"],
            ),
            bgcolor=TOKENS["surface"],
        ),
        template=TOKENS["plotly"],
        paper_bgcolor=TOKENS["bg"],
        plot_bgcolor=TOKENS["bg"],
        margin=dict(l=30, r=30, t=20, b=20),
        height=240,
        showlegend=False,
    )
    return fig


# ==============================================================================
# 9. 사이드바 (제미나이 스타일 접힘 레일 & 확장 패널)
# ==============================================================================
with st.sidebar:
    if st.session_state["sidebar_collapsed"]:
        # ----------------------------------------------------------------------
        # [접힘 상태] 제미나이 얇은 아이콘 레일 바 (너비 78px)
        # ----------------------------------------------------------------------
        st.markdown(
            """
            <div style="display:flex; flex-direction:column; align-items:center; gap:8px; margin-bottom:12px;">
                <div class="bb-logo-icon" style="width:34px; height:34px; font-size:14px;">HS</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown('<div class="gemini-pill-btn">', unsafe_allow_html=True)
        if st.button("◨ 열기", key="rail_open_btn", use_container_width=True, help="사이드바 펼치기"):
            st.session_state["sidebar_collapsed"] = False
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div style="height:1px; background:var(--bb-border); margin:12px 2px;"></div>', unsafe_allow_html=True)

        # 레일 퀵 액션 버튼
        st.markdown('<div class="rail-btn">', unsafe_allow_html=True)
        if st.button("▶", key="rail_run_now", use_container_width=True, help=f"[{st.session_state['active_ticker']}] 즉시 분석 실행"):
            task = st.session_state["analysis_task"]
            cur_sym = st.session_state["active_ticker"]
            task.update({
                "status": "running", "ticker": cur_sym, "report_content": "",
                "report_path": None, "error_msg": "", "start_time": time.time(),
            })
            threading.Thread(
                target=_run_analysis_worker,
                args=(task, cur_sym, datetime.date.today().strftime("%Y-%m-%d")),
                daemon=True,
            ).start()
            st.rerun()

        if st.button("📂", key="rail_open_repo", use_container_width=True, help="리포트 보관함 열기"):
            st.session_state["sidebar_collapsed"] = False
            st.rerun()

        if st.button("⚙", key="rail_open_spec", use_container_width=True, help="시스템 스펙 확인"):
            st.session_state["sidebar_collapsed"] = False
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

        st.markdown('<div style="height:1px; background:var(--bb-border); margin:12px 2px;"></div>', unsafe_allow_html=True)

        # 레일 최근 조회 종목
        st.markdown('<div class="rail-btn">', unsafe_allow_html=True)
        recent_rail = st.session_state.get("recent_tickers", [])[:4]
        for sym in recent_rail:
            display_sym = sym[:4]
            if st.button(display_sym, key=f"rail_sym_{sym}", use_container_width=True, help=f"{sym} 선택"):
                st.session_state["active_ticker"] = sym
                remember_ticker(sym)
                st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    else:
        # ----------------------------------------------------------------------
        # [펼침 상태] 전체 컨트롤 패널 (너비 320px)
        # ----------------------------------------------------------------------
        s_col1, s_col2 = st.columns([0.65, 0.35])
        with s_col1:
            st.markdown(
                """
                <div class="bb-brand">
                    <div class="bb-logo-icon">HS</div>
                    <div>
                        <strong>HEYstock</strong>
                        <span>Research Desk</span>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with s_col2:
            st.markdown('<div class="gemini-pill-btn">', unsafe_allow_html=True)
            if st.button("◨ 닫기", key="gemini_close_btn", help="사이드바 접기"):
                st.session_state["sidebar_collapsed"] = True
                st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        with st.expander("분석 실행 매개변수", expanded=True):
            sidebar_ticker = st.text_input("분석 종목 티커", value=st.session_state["active_ticker"]).upper().strip()

            recent = st.session_state.get("recent_tickers", [])[:6]
            st.markdown(
                '<div style="font-size:11px; color:var(--bb-text-mute); text-transform:uppercase; margin:8px 0 4px;">최근 조회</div>',
                unsafe_allow_html=True,
            )
            qcols = st.columns(3)
            for i, sym in enumerate(recent):
                if qcols[i % 3].button(sym, key=f"quick_recent_{i}_{sym}", use_container_width=True):
                    st.session_state["active_ticker"] = sym
                    remember_ticker(sym)
                    st.rerun()

            analysis_date = st.date_input("기준 일자", datetime.date.today())
            run_button = st.button("정량 분석 실행", type="primary", use_container_width=True)

        with st.expander("보관된 리포트 목록", expanded=False):
            report_files = (
                glob.glob("stock_db/**/*.txt", recursive=True) +
                glob.glob("stock_db/**/*.md", recursive=True) +
                glob.glob("results/**/*.txt", recursive=True) +
                glob.glob("results/**/*.md", recursive=True)
            )
            report_files = [f for f in set(report_files) if os.path.isfile(f)]

            keyword = st.text_input("리포트 검색", placeholder="티커 또는 파일명").strip().lower()

            report_options = {"-- 새로 생성 또는 직접 입력 종목 보기 --": None}
            for path in sorted(report_files, key=os.path.getmtime, reverse=True):
                name = os.path.basename(path)
                if keyword and keyword not in name.lower():
                    continue
                saved_at = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m/%d %H:%M")
                report_options[f"{name} ({saved_at})"] = path

            selected_report_name = st.selectbox("리포트 선택", list(report_options.keys()))
            st.caption(f"보관 건수: {max(len(report_options) - 1, 0)}건")

        with st.expander("시스템 스펙", expanded=False):
            st.markdown(
                "- 멀티 에이전트 비동기 파이프라인 백그라운드 구동\n"
                "- SEC Rule 206(4)-1 준수 정량 관측 모델\n"
                "- 시나리오 맵 기반 3분할 레짐 분석"
            )

        # 사이드바 이벤트 처리
        if run_button:
            if not sidebar_ticker:
                st.error("티커를 입력하세요.")
            else:
                task = st.session_state["analysis_task"]
                st.session_state["active_ticker"] = sidebar_ticker
                remember_ticker(sidebar_ticker)
                task.update({
                    "status": "running", "ticker": sidebar_ticker, "report_content": "",
                    "report_path": None, "error_msg": "", "start_time": time.time(),
                })
                threading.Thread(
                    target=_run_analysis_worker,
                    args=(task, sidebar_ticker, analysis_date.strftime("%Y-%m-%d")),
                    daemon=True,
                ).start()

        if selected_report_name and report_options.get(selected_report_name):
            sel_path = report_options[selected_report_name]
            st.session_state["analysis_task"]["report_path"] = sel_path
            st.session_state["analysis_task"]["status"] = "complete"
            try:
                with open(sel_path, "r", encoding="utf-8") as f:
                    st.session_state["analysis_task"]["report_content"] = f.read()
            except Exception:
                pass
            base_name = selected_report_name.split(" (")[0]
            t_match = re.search(r'\[(.*?)\]', base_name) or re.search(r'([A-Za-z]+)', base_name)
            if t_match:
                st.session_state["active_ticker"] = t_match.group(1).upper()

current_ticker = st.session_state["active_ticker"]

# ==============================================================================
# 10. 메인 대시보드
# ==============================================================================
_task = st.session_state["analysis_task"]
status_chip = {
    "running": "PROCESSING",
    "complete": "READY",
    "error": "ERROR",
}.get(_task["status"], "IDLE")

st.markdown(
    f"""
<div class="bb-hero">
  <div>
    <h1>{current_ticker} | Strategic Intelligence & Consensus Desk</h1>
    <div class="bb-sub">4대 분석 도메인(기술, 펀더멘털, 거시/뉴스, 심리) 기반의 통합 시나리오 맵</div>
  </div>
  <div style="display:flex; gap:6px; align-items:center;">
    <span class="bb-chip">STATUS: {status_chip}</span>
    <span class="bb-chip">{datetime.date.today():%Y-%m-%d}</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)


# ---- 섹션 A: 시세 차트 ----
@st.fragment
def render_chart_component(ticker: str):
    c_head, c_slider = st.columns([1.6, 1])
    with c_head:
        st.markdown("#### Market Price & Technical Structure")
    with c_slider:
        lookback = st.slider("조회 범위 (일)", min_value=30, max_value=365, value=180, step=30, key="chart_slider")

    df = fetch_cached_chart_data(ticker, lookback)

    if not df.empty:
        latest = df.iloc[-1]
        prev_close = df.iloc[-2]["Close"] if len(df) > 1 else latest["Close"]
        pct_change = ((latest["Close"] - prev_close) / prev_close) * 100

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Close", f"${latest['Close']:.2f}", f"{pct_change:+.2f}%")
        col2.metric("10 EMA", f"${latest['EMA10']:.2f}")
        col3.metric("20 EMA", f"${latest['EMA20']:.2f}")
        col4.metric("Bollinger Upper", f"${latest['BB_UPPER']:.2f}")
        col5.metric("Bollinger Lower", f"${latest['BB_LOWER']:.2f}")

        fig = build_interactive_chart(df, ticker)
        try:
            fig.update_layout(
                template=TOKENS["plotly"],
                paper_bgcolor=TOKENS["bg"],
                plot_bgcolor=TOKENS["bg"],
                font=dict(color=TOKENS["text"]),
            )
            fig.update_xaxes(gridcolor=TOKENS["grid"], tickfont=dict(color=TOKENS["text_soft"]))
            fig.update_yaxes(gridcolor=TOKENS["grid"], tickfont=dict(color=TOKENS["text_soft"]))
        except Exception:
            pass
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(f"{ticker} 시장 데이터를 수신할 수 없습니다. 데이터 연결 상태를 점검하십시오.")


render_chart_component(current_ticker)

st.markdown("---")

# ---- 섹션 B: 리포트 & 시나리오 맵 & 아레나 ----
is_running = (st.session_state["analysis_task"]["status"] == "running")


@st.fragment(run_every=2 if is_running else None)
def render_report_component(ticker: str):
    cur_task = st.session_state["analysis_task"]

    if cur_task["status"] == "running":
        elapsed = int(time.time() - cur_task["start_time"])
        mins, secs = divmod(elapsed, 60)
        st.markdown(
            f"""
<div class="bb-running">
  <strong>[ANALYSIS IN PROGRESS]</strong> {cur_task['ticker']} 에이전트 간 리스크 대립 검증 및 시나리오 맵 합성 중
  (소요 시간: {mins}분 {secs}초)
</div>
""",
            unsafe_allow_html=True,
        )
        return

    if cur_task["status"] == "error":
        st.error(f"시스템 오류: {cur_task['error_msg']}")
        return

    report_text = cur_task.get("report_content", "")
    target_path = cur_task.get("report_path")

    if not report_text and target_path and os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                report_text = f.read()
        except Exception:
            pass

    if not report_text:
        st.markdown(
            """
<div class="bb-empty">
  <strong>NO ACTIVE DOSSIER</strong><br>
  좌측 패널에서 종목 코드를 설정하고 [정량 분석 실행] 버튼을 클릭하십시오.
</div>
""",
            unsafe_allow_html=True,
        )
        return

    parsed = parse_full_report_statefully(report_text, fallback_ticker=ticker)

    head_l, head_r = st.columns([1.6, 1])
    with head_l:
        st.subheader("Multi-Agent Consensus & Scenario Map")
    with head_r:
        st.download_button(
            label="Download Full Report (.txt)",
            data=parsed["cleaned_full"],
            file_name=f"{ticker}_Research_Report_{datetime.date.today():%Y%m%d}.txt",
            mime="text/plain",
            use_container_width=True,
        )

    # 1. 3초 퀵 펄스 (Executive Pulse) 렌더링
    if parsed["executive_pulse"]:
        tag_spans = "".join([f'<span class="pulse-tag">{tag}</span>' for tag in parsed["executive_pulse"]])
        st.markdown(
            f"""
            <div class="pulse-tag-group">
                <span class="pulse-tag-lead">EXECUTIVE PULSE</span>
                {tag_spans}
            </div>
            """,
            unsafe_allow_html=True,
        )

    # 2. 컨센서스 등급
    dec = parsed["decision"]
    pill_class = "pill-hold"
    if any(w in dec for w in ["BUY", "OVERWEIGHT", "BULLISH"]):
        pill_class = "pill-buy"
    elif any(w in dec for w in ["SELL", "UNDERWEIGHT", "BEARISH"]):
        pill_class = "pill-sell"

    badge_text = f"{dec} ({parsed['bias_label']})" if parsed["bias_label"] else dec

    r_col1, r_col2 = st.columns([1.2, 0.8])
    with r_col1:
        st.markdown(
            f"""
            <div class="decision-container">
                <span class="decision-label">MULTI-AGENT CONSENSUS</span>
                <span class="decision-pill {pill_class}">{badge_text}</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if parsed["risk_synthesis"]:
            st.markdown(
                f"""
                <div class="strategy-card">
                    <b>Risk & Market Synthesis</b>
                    {parsed['risk_synthesis']}
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f'<div class="strategy-card">{parsed["final_strategy"]}</div>', unsafe_allow_html=True)

    with r_col2:
        st.markdown(
            "<div style='font-size:11px; color:var(--bb-text-mute); text-transform:uppercase; letter-spacing:.05em; margin-bottom:4px;'>"
            "Domain Balance Radar</div>",
            unsafe_allow_html=True,
        )
        st.plotly_chart(create_radar_chart(parsed["scores"], ticker), use_container_width=True)

    # 3. 3분할 전략 시나리오 맵
    sc = parsed["scenarios"]
    if sc["bull"] or sc["neutral"] or sc["bear"]:
        st.markdown("#### Strategic Scenario Map")
        sc_col1, sc_col2, sc_col3 = st.columns(3)

        with sc_col1:
            st.markdown(
                f"""
                <div class="scenario-box sc-bull">
                    <div class="sc-title">[Bullish Extension] 상방 확장</div>
                    <div class="sc-body">{sc['bull'] if sc['bull'] else '상방 확장 관측선 대기'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with sc_col2:
            st.markdown(
                f"""
                <div class="scenario-box sc-neu">
                    <div class="sc-title">[Neutral Consolidation] 박스권 및 횡보</div>
                    <div class="sc-body">{sc['neutral'] if sc['neutral'] else '박스권 진동 관측선 대기'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        with sc_col3:
            st.markdown(
                f"""
                <div class="scenario-box sc-bear">
                    <div class="sc-title">[Downside Invalidation] 하방 무효화</div>
                    <div class="sc-body">{sc['bear'] if sc['bear'] else '하방 이탈 위험선 대기'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # 4. 정량 투자 논지
    if parsed["investment_thesis"]:
        st.markdown(
            f"""
            <div class="strategy-card" style="border-left: 3px solid var(--bb-accent);">
                <b>Quantitative Investment Thesis</b>
                {parsed['investment_thesis']}
            </div>
            """,
            unsafe_allow_html=True,
        )

    # 5. 리스크 아레나 공방전 내역
    if parsed["arena_debate"]:
        with st.expander("Risk Management Arena (Adversarial Debate Log)", expanded=False):
            tab_all, tab_agg, tab_neu, tab_con = st.tabs(["전체 기록", "Aggressive", "Neutral", "Conservative"])

            with tab_all:
                for turn in parsed["arena_debate"]:
                    spk = turn["speaker"]
                    badge_color = "#f87171" if spk == "Conservative" else ("#34d399" if spk == "Aggressive" else "#60a5fa")
                    st.markdown(
                        f"""
                        <div class="arena-card">
                            <div class="arena-speaker" style="color:{badge_color};">[{spk} Risk Analyst]</div>
                            <div>{turn['text']}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

            with tab_agg:
                agg_list = [t for t in parsed["arena_debate"] if t["speaker"] == "Aggressive"]
                for t in agg_list:
                    st.markdown(f'<div class="arena-card"><div>{t["text"]}</div></div>', unsafe_allow_html=True)
                if not agg_list:
                    st.caption("공격형 분석가의 발언 내역이 없습니다.")

            with tab_neu:
                neu_list = [t for t in parsed["arena_debate"] if t["speaker"] == "Neutral"]
                for t in neu_list:
                    st.markdown(f'<div class="arena-card"><div>{t["text"]}</div></div>', unsafe_allow_html=True)
                if not neu_list:
                    st.caption("중립형 분석가의 발언 내역이 없습니다.")

            with tab_con:
                con_list = [t for t in parsed["arena_debate"] if t["speaker"] == "Conservative"]
                for t in con_list:
                    st.markdown(f'<div class="arena-card"><div>{t["text"]}</div></div>', unsafe_allow_html=True)
                if not con_list:
                    st.caption("보수형 분석가의 발언 내역이 없습니다.")

    st.markdown("---")
    st.markdown("### Domain Analysis & Observational Data")

    cards = [
        ("Technical", "Technical Structure Analysis"),
        ("News", "Macro & World Affairs Analysis"),
        ("Sentiment", "Market Sentiment Analysis"),
        ("Fundamental", "Fundamental Valuation Analysis"),
    ]
    for row in (cards[:2], cards[2:]):
        cols = st.columns(2)
        for col, (key, label) in zip(cols, row):
            data = parsed["domains"][key]
            with col:
                with st.expander(label, expanded=True):
                    if data.get("tags"):
                        dtags = "".join([f'<span class="pulse-tag">{t}</span>' for t in data["tags"]])
                        st.markdown(f'<div style="margin-bottom:8px;">{dtags}</div>', unsafe_allow_html=True)

                    st.progress(min(max(data["bull"], 0), 100) / 100)
                    st.markdown(
                        f'<div class="score-badge">Bull {data["bull"]}% | Bear {data["bear"]}%</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(data["text"])

    st.markdown(
        """
        <div class="disclaimer-banner">
            <strong>Regulatory Notice & Compliance Disclaimer</strong><br>
            본 시스템이 제공하는 분석 결과, 지표 및 시나리오는 공개된 시장 데이터를 바탕으로 알고리즘이 산출한 정량적 연구 참고 자료입니다.
            개별 금융투자상품의 매수/매도를 권유하지 않으며, 특정 수익률이나 원금을 보장하지 않습니다.
            모든 투자 결정 및 운용에 따른 손익 책임은 전적으로 투자자 본인에게 있습니다.
        </div>
        """,
        unsafe_allow_html=True,
    )


render_report_component(current_ticker)

st.markdown(
    '<div class="bb-footer"><span>[SYSTEM] Quantitative Connection Monitored</span><span>HEYstock Research Platform</span></div>',
    unsafe_allow_html=True,
)