import os
import glob
import re
import json
import datetime
import threading
import time
import socket
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import streamlit as st
import plotly.graph_objects as go
import pandas as pd

# [핵심] 외부 통신 타임아웃 강제
socket.setdefaulttimeout(3.0)

from market_data import MarketDataProvider
from chart_builder import build_interactive_chart
from tradingagents.graph.trading_graph import TradingAgentsGraph

from ticker_resolver import resolve_stock_input
from report_formatter import convert_scientific_numbers_kr

# ==============================================================================
# 1. 페이지 설정
# ==============================================================================
st.set_page_config(
    page_title="HEYstock | Quantitative Research Desk",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==============================================================================
# 2. 계정 및 신청 DB 관리 (JSON 기반 경량 영구 저장소)
# ==============================================================================
USERS_DB_PATH = os.path.join(os.getcwd(), "users_db.json")
REQUESTS_DB_PATH = os.path.join(os.getcwd(), "requests_db.json")

def load_json(path: str, default_data):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default_data

def save_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

DEFAULT_USERS = {
    "admin": {"pw": "admin1234", "role": "admin", "name": "수석 리서처", "phone": "010-0000-0000"},
    "user1": {"pw": "1234", "role": "user", "name": "김투자", "phone": "010-1234-5678"},
    "user2": {"pw": "1234", "role": "user", "name": "이성장", "phone": "010-9876-5432"}
}
if not os.path.exists(USERS_DB_PATH):
    save_json(USERS_DB_PATH, DEFAULT_USERS)

def get_users():
    return load_json(USERS_DB_PATH, DEFAULT_USERS)

def get_requests():
    return load_json(REQUESTS_DB_PATH, {})

def save_user_request(user_id: str, ticker: str, disp_name: str):
    # [핵심] 유효하지 않거나 데이터가 없는 종목 원천 차단
    if not is_valid_ticker_symbol(ticker):
        return False, f"'{disp_name}({ticker})'은(는) 유효하지 않거나 시세 데이터를 가져올 수 없어 신청할 수 없습니다."

    reqs = get_requests()
    if user_id not in reqs:
        reqs[user_id] = []
    
    current_list = reqs[user_id]
    if any(item["ticker"] == ticker for item in current_list):
        return False, "이미 신청 목록에 존재하는 종목입니다."
    if len(current_list) >= 3:
        return False, "1인당 주간 신청은 최대 3종목까지 가능합니다."
    
    current_list.append({
        "ticker": ticker,
        "name": disp_name,
        "requested_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    reqs[user_id] = current_list
    save_json(REQUESTS_DB_PATH, reqs)
    return True, f"'{disp_name}' 종목이 이번 주 브리핑 신청 목록에 등록되었습니다."

def remove_user_request(user_id: str, ticker: str):
    reqs = get_requests()
    if user_id in reqs:
        reqs[user_id] = [item for item in reqs[user_id] if item["ticker"] != ticker]
        save_json(REQUESTS_DB_PATH, reqs)


# ==============================================================================
# 3. 세션 상태 초기화
# ==============================================================================
DEFAULTS = {
    "auth_user": None,
    "active_ticker": "080220.KQ",
    "active_display_name": "제주반도체",
    "search_query_kr": "제주반도체",
    "search_query_us": "TSLA",
    "is_us_mode": False,
    "analysis_task": {
        "status": "idle",
        "ticker": "",
        "display_name": "",
        "report_content": "",
        "report_path": None,
        "error_msg": "",
        "start_time": 0,
        "just_finished": False,
    },
    "batch_task": {
        "status": "idle",
        "total": 0,
        "current_idx": 0,
        "current_stock": "",
        "logs": []
    }
}
for _k, _v in DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v.copy() if isinstance(_v, (dict, list)) else _v


def sanitize_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if t.endswith((".KS", ".KQ")):
        return t
    return t.replace('.', '-').replace('/', '-')


def normalize_input(raw_input: str) -> tuple[str, str]:
    clean_val = raw_input.strip()
    paren_m = re.match(r"^([^\(]+)\s*\(([^\)]+)\)$", clean_val)
    if paren_m:
        clean_val = paren_m.group(1).strip()
    try:
        resolved = resolve_stock_input(clean_val)
        return resolved["agent_ticker"], resolved.get("corp_name", clean_val)
    except Exception:
        clean = sanitize_ticker(clean_val)
        return clean, clean_val


def get_safe_stock_label(ticker: str, disp_name: str | None = None) -> str:
    if not disp_name or disp_name == ticker:
        _, disp_name = normalize_input(ticker)
    label = f"{disp_name}({ticker})" if (disp_name and disp_name != ticker) else ticker
    return re.sub(r'[\\/*?:"<>|]', "", label).strip()


# ==============================================================================
# 4. 국내 및 해외 마스터 사전 & 검색기
# ==============================================================================
COMMON_ALIASES_KR = {
    "삼전": "삼성전자", "삼전우": "삼성전자우", "하닉": "SK하이닉스",
    "현차": "현대차", "카뱅": "카카오뱅크", "에코": "에코프로",
    "알테": "알테오젠", "삼바": "삼성바이오로직스", "포홀": "POSCO홀딩스",
    "이노": "SK이노베이션", "엔씨": "엔씨소프트"
}

@st.cache_data(ttl=3600, show_spinner=False)
def get_krx_master_list() -> list[dict]:
    master_path = os.path.join(os.getcwd(), "krx_master.json")
    if os.path.exists(master_path):
        try:
            with open(master_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            items = []
            if isinstance(raw, dict) and "by_name" in raw:
                for name, info in raw["by_name"].items():
                    if isinstance(info, dict):
                        c_str = str(info.get("code") or info.get("ticker") or "").strip().zfill(6)
                        m_str = str(info.get("market") or "").strip()
                    else:
                        c_str = str(info).strip().zfill(6)
                        m_str = ""
                    if not m_str:
                        m_str = "코스닥" if c_str.startswith(("08", "24", "19", "09", "27", "06", "35", "40")) else "코스피"
                    if c_str and c_str != "000000":
                        items.append({"name": str(name).strip(), "code": c_str, "market": m_str})
                if items:
                    return items
        except Exception:
            pass

    fallback = [
        ("삼성전자", "005930", "코스피"), ("삼성전자우", "005935", "코스피"),
        ("SK하이닉스", "000660", "코스피"), ("LG에너지솔루션", "373220", "코스피"),
        ("현대차", "005380", "코스피"), ("기아", "000270", "코스피"),
        ("제주반도체", "080220", "코스닥"), ("알테오젠", "196170", "코스닥"),
        ("한국항공우주", "047810", "코스피"), ("에코프로비엠", "247540", "코스닥")
    ]
    return [{"name": s[0], "code": s[1], "market": s[2]} for s in fallback]


def find_matched_stocks_kr(query: str, limit: int = 5) -> list[dict]:
    raw_q = str(query).strip()
    if not raw_q:
        return []
    q = COMMON_ALIASES_KR.get(raw_q.lower(), raw_q).lower()
    stocks = get_krx_master_list()
    exact = [s for s in stocks if s["name"].lower() == q or s["code"] == q]
    prefix = [s for s in stocks if (s["name"].lower().startswith(q) or s["code"].startswith(q)) and s not in exact]
    substr = [s for s in stocks if (q in s["name"].lower() or q in s["code"]) and s not in exact and s not in prefix]
    return (exact + prefix + substr)[:limit]


US_POPULAR_STOCKS = [
    {"name": "테슬라", "code": "TSLA", "market": "NASDAQ"},
    {"name": "애플", "code": "AAPL", "market": "NASDAQ"},
    {"name": "엔비디아", "code": "NVDA", "market": "NASDAQ"},
    {"name": "마이크로소프트", "code": "MSFT", "market": "NASDAQ"},
    {"name": "알파벳A(구글)", "code": "GOOGL", "market": "NASDAQ"},
    {"name": "아마존", "code": "AMZN", "market": "NASDAQ"},
    {"name": "메타", "code": "META", "market": "NASDAQ"},
    {"name": "브로드컴", "code": "AVGO", "market": "NASDAQ"},
    {"name": "TSMC", "code": "TSM", "market": "NYSE"},
    {"name": "팔란티어", "code": "PLTR", "market": "NYSE"},
    {"name": "아이온큐", "code": "IONQ", "market": "NYSE"},
    {"name": "코인베이스", "code": "COIN", "market": "NASDAQ"},
    {"name": "AMD", "code": "AMD", "market": "NASDAQ"},
    {"name": "슈퍼마이크로컴퓨터", "code": "SMCI", "market": "NASDAQ"},
    {"name": "넷플릭스", "code": "NFLX", "market": "NASDAQ"},
    {"name": "일라이릴리", "code": "LLY", "market": "NYSE"},
    {"name": "퀄컴", "code": "QCOM", "market": "NASDAQ"},
    {"name": "인텔", "code": "INTC", "market": "NASDAQ"},
    {"name": "스타벅스", "code": "SBUX", "market": "NASDAQ"},
    {"name": "월트디즈니", "code": "DIS", "market": "NYSE"},
    {"name": "보잉", "code": "BA", "market": "NYSE"},
    {"name": "Invesco QQQ (나스닥100)", "code": "QQQ", "market": "NASDAQ"},
    {"name": "SPDR S&P500", "code": "SPY", "market": "NYSE"},
]

US_ALIASES = {
    "테슬라": "TSLA", "애플": "AAPL", "엔비디아": "NVDA", "마소": "MSFT", "마이크로소프트": "MSFT",
    "구글": "GOOGL", "알파벳": "GOOGL", "아마존": "AMZN", "메타": "META", "팔란티어": "PLTR",
    "아이온큐": "IONQ", "코인베이스": "COIN", "넷플릭스": "NFLX", "넷플": "NFLX", "릴리": "LLY",
    "나스닥": "QQQ", "큐큐큐": "QQQ", "스파이": "SPY"
}

def find_matched_stocks_us(query: str, limit: int = 5) -> list[dict]:
    raw_q = str(query).strip()
    if not raw_q:
        return US_POPULAR_STOCKS[:limit]
    
    q_mapped = US_ALIASES.get(raw_q.lower(), raw_q).upper()
    q_lower = raw_q.lower()

    exact = [s for s in US_POPULAR_STOCKS if s["code"] == q_mapped or s["name"].lower() == q_lower]
    prefix = [s for s in US_POPULAR_STOCKS if (s["code"].startswith(q_mapped) or s["name"].lower().startswith(q_lower)) and s not in exact]
    substr = [s for s in US_POPULAR_STOCKS if (q_mapped in s["code"] or q_lower in s["name"].lower()) and s not in exact and s not in prefix]

    return (exact + prefix + substr)[:limit]


# ==============================================================================
# 5. 테마 스타일
# ==============================================================================
TOKENS = dict(
    bg="#0b0e14", surface="#12161f", surface_hi="#1b2230", card_bg="#12161f",
    input_bg="#161b26", border="rgba(255,255,255,0.12)", text="#f1f5f9",
    text_soft="#94a3b8", text_mute="#64748b", accent="#0d9488",
    accent_soft="rgba(13,148,136,0.15)", shadow="0 6px 20px rgba(0,0,0,0.45)",
    plotly="plotly_dark", grid="rgba(255,255,255,0.08)",
    tag_bg="#152a2a", tag_border="rgba(45, 212, 191, 0.38)", tag_text="#5eead4",
    bull_border="rgba(16,185,129,0.35)", bull_bg="rgba(16,185,129,0.06)", bull_text="#34d399",
    neutral_border="rgba(59,130,246,0.35)", neutral_bg="rgba(59,130,246,0.06)", neutral_text="#60a5fa",
    bear_border="rgba(239,68,68,0.35)", bear_bg="rgba(239,68,68,0.06)", bear_text="#f87171",
)

st.markdown(
    f"""
<style>
:root {{
  --bb-bg: {TOKENS['bg']}; --bb-surface: {TOKENS['surface']}; --bb-card-bg: {TOKENS['card_bg']};
  --bb-border: {TOKENS['border']}; --bb-text: {TOKENS['text']}; --bb-text-soft: {TOKENS['text_soft']};
  --bb-text-mute: {TOKENS['text_mute']}; --bb-accent: {TOKENS['accent']}; --bb-shadow: {TOKENS['shadow']};
  --sc-tag-bg: {TOKENS['tag_bg']}; --sc-tag-border: {TOKENS['tag_border']}; --sc-tag-text: {TOKENS['tag_text']};
  --sc-bull-border: {TOKENS['bull_border']}; --sc-bull-bg: {TOKENS['bull_bg']}; --sc-bull-text: {TOKENS['bull_text']};
  --sc-neu-border: {TOKENS['neutral_border']}; --sc-neu-bg: {TOKENS['neutral_bg']}; --sc-neu-text: {TOKENS['neutral_text']};
  --sc-bear-border: {TOKENS['bear_border']}; --sc-bear-bg: {TOKENS['bear_bg']}; --sc-bear-text: {TOKENS['bear_text']};
}}
.stApp, [data-testid="stAppViewContainer"], section.main {{ background-color: var(--bb-bg) !important; color: var(--bb-text) !important; }}
.bb-hero {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; padding: 16px 20px; margin-bottom: 14px; border-radius: 8px; border: 1px solid var(--bb-border); background-color: var(--bb-card-bg); box-shadow: var(--bb-shadow); }}
.bb-hero h1 {{ font-size: 20px; margin: 0; font-weight: 700; }}
.bb-hero .bb-sub {{ font-size: 12.5px; color: var(--bb-text-soft); margin-top: 4px; }}
.bb-chip {{ font-size: 11px; font-weight: 600; padding: 4px 10px; border-radius: 4px; background: {TOKENS['surface_hi']}; color: var(--bb-text-soft); border: 1px solid var(--bb-border); font-family: ui-monospace, monospace; }}
.decision-container {{ display: inline-flex; align-items: center; gap: 10px; background-color: var(--bb-card-bg); padding: 6px 14px; border-radius: 6px; border: 1px solid var(--bb-border); margin-bottom: 12px; }}
.decision-label {{ font-size: 11px; font-weight: 700; color: var(--bb-text-mute); letter-spacing: .06em; text-transform: uppercase; }}
.decision-pill {{ font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 4px; }}
.pill-hold {{ background: rgba(245,158,11,.15); color: #fbbf24; border: 1px solid rgba(245,158,11,.3); }}
.pill-buy  {{ background: rgba(16,185,129,.15); color: #34d399; border: 1px solid rgba(16,185,129,.3); }}
.pill-sell {{ background: rgba(239,68,68,.15);  color: #f87171; border: 1px solid rgba(239,68,68,.3); }}
.pulse-tag-group {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 14px; }}
.pulse-tag {{ display: inline-flex; align-items: center; font-size: 11.5px; font-weight: 600; padding: 4px 10px; border-radius: 6px; background-color: var(--sc-tag-bg) !important; color: var(--sc-tag-text) !important; border: 1px solid var(--sc-tag-border) !important; font-family: ui-monospace, monospace; }}
.scenario-box {{ border-radius: 8px; padding: 15px; margin-bottom: 12px; min-height: 200px; display: flex; flex-direction: column; justify-content: flex-start; box-shadow: var(--bb-shadow); }}
.sc-bull {{ border: 1px solid var(--sc-bull-border); background-color: var(--sc-bull-bg); }}
.sc-neu  {{ border: 1px solid var(--sc-neu-border); background-color: var(--sc-neu-bg); }}
.sc-bear {{ border: 1px solid var(--sc-bear-border); background-color: var(--sc-bear-bg); }}
.sc-title {{ font-size: 13px; font-weight: 700; margin-bottom: 8px; text-transform: uppercase; }}
.sc-bull .sc-title {{ color: var(--sc-bull-text); }}
.sc-neu .sc-title  {{ color: var(--sc-neu-text); }}
.sc-bear .sc-title {{ color: var(--sc-bear-text); }}
.sc-body {{ font-size: 12.5px; line-height: 1.7; color: var(--bb-text); opacity: .95; white-space: pre-wrap; }}
.strategy-card {{ background-color: var(--bb-card-bg); border: 1px solid var(--bb-border); border-radius: 8px; padding: 16px 18px; font-size: 13px; line-height: 1.75; color: var(--bb-text); margin-bottom: 14px; box-shadow: var(--bb-shadow); }}
.strategy-card b {{ color: var(--bb-text-soft); font-size: 11.5px; text-transform: uppercase; display: block; margin-bottom: 6px; }}
.desk-block {{ background-color: var(--bb-surface); border: 1px solid var(--bb-border); border-radius: 6px; padding: 12px 14px; margin-bottom: 10px; font-size: 12.5px; line-height: 1.65; }}
.desk-block strong {{ color: var(--bb-accent); }}
</style>
""",
    unsafe_allow_html=True,
)


# ==============================================================================
# 6. 차트 데이터 수신 및 [핵심] 유효성 검증 엔진
# ==============================================================================
def _fetch_data_worker(clean_ticker: str, days: int) -> pd.DataFrame:
    if clean_ticker.endswith((".KS", ".KQ")):
        try:
            import FinanceDataReader as fdr
            code = clean_ticker.split('.')[0]
            start_date = (datetime.date.today() - datetime.timedelta(days=days + 60)).strftime("%Y-%m-%d")
            df = fdr.DataReader(code, start=start_date)
            if df is not None and not df.empty and len(df) > 5:
                df["EMA10"] = df["Close"].ewm(span=10, adjust=False).mean()
                df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
                mid = df["Close"].rolling(20).mean()
                std = df["Close"].rolling(20).std()
                df["BB_UPPER"] = mid + (2 * std)
                df["BB_LOWER"] = mid - (2 * std)
                return df.tail(days)
        except Exception:
            pass

    try:
        provider = MarketDataProvider()
        df = provider.fetch_candlestick_data(clean_ticker, days=days)
        if df is not None and not df.empty:
            return df
    except Exception:
        pass

    try:
        import yfinance as yf
        df = yf.download(clean_ticker, period=f"{days+60}d", progress=False)
        if df is not None and not df.empty and len(df) > 5:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df["EMA10"] = df["Close"].ewm(span=10, adjust=False).mean()
            df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
            mid = df["Close"].rolling(20).mean()
            std = df["Close"].rolling(20).std()
            df["BB_UPPER"] = mid + (2 * std)
            df["BB_LOWER"] = mid - (2 * std)
            return df.tail(days)
    except Exception:
        pass

    return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_cached_chart_data(ticker: str, days: int) -> pd.DataFrame:
    clean_ticker = sanitize_ticker(ticker)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_fetch_data_worker, clean_ticker, days)
        try:
            return future.result(timeout=2.5)
        except (FutureTimeoutError, Exception):
            return pd.DataFrame()


@st.cache_data(ttl=1800, show_spinner=False)
def is_valid_ticker_symbol(ticker: str) -> bool:
    """티커의 실제 존재 여부 및 시세 데이터 수신 가능 여부 정밀 검증"""
    if not ticker or len(str(ticker).strip()) < 1:
        return False
    clean_sym = sanitize_ticker(ticker)

    # 1. 국내 주식
    if clean_sym.endswith((".KS", ".KQ")):
        code = clean_sym.split(".")[0]
        master = get_krx_master_list()
        if any(s["code"] == code for s in master):
            return True
        df = fetch_cached_chart_data(clean_sym, days=10)
        return df is not None and not df.empty

    # 2. 해외 주식 (대표 리스트 매칭)
    if any(s["code"] == clean_sym for s in US_POPULAR_STOCKS):
        return True

    # 3. 기타 해외 티커 (실제 데이터 수신 검증)
    df = fetch_cached_chart_data(clean_sym, days=10)
    return df is not None and not df.empty


def _execute_single_stock_analysis(ticker: str, disp_name: str, date_str: str) -> tuple[str, str]:
    clean_sym = sanitize_ticker(ticker)
    try:
        from tradingagents.default_config import DEFAULT_CONFIG
        graph = TradingAgentsGraph(config=DEFAULT_CONFIG.copy())
    except Exception:
        graph = TradingAgentsGraph()

    result = graph.propagate(clean_sym, date_str)
    extracted_text = ""
    final_state = result[0] if (isinstance(result, tuple) and len(result) > 0) else result

    EXCLUDE_KEYS = {"company_of_interest", "asset_type", "instrument_context", "trade_date", "sender"}
    if isinstance(final_state, dict):
        parts = [f"### {k}\n{v}" for k, v in final_state.items() if k not in EXCLUDE_KEYS and isinstance(v, str) and v.strip()]
        extracted_text = "\n\n".join(parts)
    elif isinstance(final_state, str):
        extracted_text = final_state
        for meta_k in EXCLUDE_KEYS:
            extracted_text = re.sub(rf'###\s*{meta_k}\s*\n[^\n#]+(\n\n)?', '', extracted_text).strip()

    results_dir = os.path.join(os.getcwd(), "results")
    os.makedirs(results_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    stock_label = get_safe_stock_label(clean_sym, disp_name)
    saved_file_path = os.path.join(results_dir, f"[{stock_label}]_{timestamp}_report.txt")

    full_content = extracted_text if extracted_text else "보고서 데이터가 비어 있습니다."
    with open(saved_file_path, "w", encoding="utf-8") as f:
        f.write(full_content)

    return saved_file_path, full_content


def _run_admin_analysis_worker(task_dict: dict, ticker: str, disp_name: str, date_str: str):
    try:
        path, content = _execute_single_stock_analysis(ticker, disp_name, date_str)
        task_dict["report_path"] = path
        task_dict["report_content"] = content
        task_dict["status"] = "complete"
        task_dict["just_finished"] = True
    except Exception as e:
        task_dict["status"] = "error"
        task_dict["error_msg"] = str(e)


def _run_batch_worker(batch_dict: dict, unique_stocks: list[dict], date_str: str):
    batch_dict["status"] = "running"
    batch_dict["total"] = len(unique_stocks)
    batch_dict["logs"] = []

    for idx, item in enumerate(unique_stocks):
        batch_dict["current_idx"] = idx + 1
        batch_dict["current_stock"] = f"{item['name']} ({item['ticker']})"
        try:
            p, _ = _execute_single_stock_analysis(item["ticker"], item["name"], date_str)
            batch_dict["logs"].append(f"✅ [{idx+1}/{len(unique_stocks)}] {item['name']} 산출 완료")
        except Exception as e:
            batch_dict["logs"].append(f"❌ [{idx+1}/{len(unique_stocks)}] {item['name']} 실패: {e}")
        time.sleep(1)

    batch_dict["status"] = "complete"


# ==============================================================================
# 7. 파서 엔진
# ==============================================================================
def extract_clean_tags(raw_line: str) -> list[str]:
    if not raw_line:
        return []
    cleaned_line = re.sub(r'[*_`\[\]⚡]', '', raw_line)
    chunks = re.findall(r'#\s*([^#\n,]+)', cleaned_line)
    return [f"#{c.strip().strip(' -·|/,')}" for c in chunks if c.strip() and c.strip() not in {"-", "·", "|", "/"}]


def format_scenario_text(raw_text: str) -> str:
    if not raw_text:
        return "관측 조건 대기 중"
    lines = []
    for line in raw_text.splitlines():
        l = line.strip()
        if not l:
            continue
        if l.startswith(("-", "•", "*")):
            l = l.lstrip("-•* ").strip()
        l = re.sub(r'^(?:[①-⑩]|\d+[\.\)])\s*', '', l)
        if l:
            lines.append(f"• {l}")
    return "\n".join(lines) if lines else raw_text.strip()


def extract_section_by_keywords(text: str, start_keywords: list[str]) -> str:
    start_pos = -1
    for kw in start_keywords:
        m = re.search(kw, text, re.IGNORECASE)
        if m:
            start_pos = m.start()
            break
    if start_pos == -1:
        return ""
    sub = text[start_pos:]
    boundary_pat = r'(?:\n={5,}|\n#{1,4}\s*(?:\[|📈|🏢|💬|🌍|Multi-Agent|Strategic|Executive)|(?:\n\[(?:Technical|Social|Macro|Fundamentals|Multi-Agent)\s*Report\]))'
    m_end = re.search(boundary_pat, sub[30:], re.IGNORECASE)
    return sub[:30 + m_end.start()].strip() if m_end else sub.strip()


def parse_full_report_statefully(raw_text: str, fallback_ticker: str = "UNKNOWN") -> dict:
    if not raw_text:
        return {
            "ticker": fallback_ticker, "decision": "NEUTRAL", "bias_label": "신호 균형",
            "executive_pulse": [], "risk_synthesis": "",
            "scenarios": {"bull": "", "neutral": "", "bear": ""},
            "investment_thesis": "", "final_strategy": "",
            "scores": {"Fundamental": 50, "Technical": 50, "Sentiment": 50, "News": 50},
            "domains": {}, "cleaned_full": "",
        }

    raw_text = convert_scientific_numbers_kr(raw_text)
    exec_pulse = []
    exec_m = re.search(r'(?:>\s*)?(?:⚡\s*)?\*\*Executive Pulse\*\*:\s*([^\n]+)', raw_text)
    if exec_m:
        exec_pulse = extract_clean_tags(exec_m.group(1))

    decision = "NEUTRAL"
    bias_label = "신호 균형 및 관망"
    cons_m = (
        re.search(r'MULTI-AGENT CONSENSUS:\s*\*\*?([^\*\n]+)\*\*?', raw_text, re.IGNORECASE) or
        re.search(r'AI 종합 컨센서스:\s*\*\*?([^\*\n]+)\*\*?', raw_text, re.IGNORECASE) or
        re.search(r'종합 판정\s*[:：]\s*\*\*?([^\*\n]+)\*\*?', raw_text, re.IGNORECASE)
    )
    if cons_m:
        raw_decision_str = cons_m.group(1).strip()
        decision = raw_decision_str
        upper_d = raw_decision_str.upper()
        if any(w in upper_d for w in ["BEAR", "SELL", "UNDERWEIGHT", "CAUTION"]):
            bias_label = "하방 리스크 경계"
        elif any(w in upper_d for w in ["BULL", "BUY", "OVERWEIGHT"]):
            bias_label = "상승 모멘텀 우위"
        else:
            bias_label = "신호 균형 및 관망"

    scenarios = {"bull": "", "neutral": "", "bear": ""}
    bull_m = re.search(r'1\.\s*\*\*Bullish Extension[^\*]*\*\*:\s*(.*?)(?=\n\s*2\.|\Z)', raw_text, re.S)
    neu_m = re.search(r'2\.\s*\*\*Neutral Consolidation[^\*]*\*\*:\s*(.*?)(?=\n\s*3\.|\Z)', raw_text, re.S)
    bear_m = re.search(r'3\.\s*\*\*Downside Invalidation[^\*]*\*\*:\s*(.*?)(?=\n\s*\*\*Investment Thesis|\n\s*====|\Z)', raw_text, re.S)
    if bull_m: scenarios["bull"] = format_scenario_text(bull_m.group(1).strip())
    if neu_m: scenarios["neutral"] = format_scenario_text(neu_m.group(1).strip())
    if bear_m: scenarios["bear"] = format_scenario_text(bear_m.group(1).strip())

    thesis_m = re.search(r'\*\*Investment Thesis\*\*[^\:]*:\s*(.*?)(?=\n\s*====|\Z)', raw_text, re.S)
    investment_thesis = thesis_m.group(1).strip() if thesis_m else ""
    risk_synth_m = re.search(r'\*\*Risk & Market Synthesis\*\*:\s*(.*?)(?=\n\s*\*\*Strategic Scenario|\n\s*1\.|\Z)', raw_text, re.S)
    risk_synthesis = risk_synth_m.group(1).strip() if risk_synth_m else ""

    def parse_domain_block(keywords: list[str], default_bull: int):
        sec_text = extract_section_by_keywords(raw_text, keywords)
        if not sec_text:
            return {"bull": default_bull, "bear": 100 - default_bull, "tags": [], "findings": "세부 데이터 분석 중", "debate": ""}
        bull, bear = default_bull, 100 - default_bull
        s_m = re.search(r'Bull\s*Score.*?(\d+).*?Bear\s*Score.*?(\d+)', sec_text, re.I) or re.search(r'Bull\s*\*\*?(\d+)점?\*\*?\s*vs\s*Bear\s*\*\*?(\d+)점?', sec_text, re.I)
        if s_m:
            try: bull, bear = int(s_m.group(1)), int(s_m.group(2))
            except Exception: pass
        tag_m = re.search(r'(?:Quick\s*Pulse|태그)[^\n:]*[:：]\s*([^\n]+)', sec_text, re.I)
        tags = extract_clean_tags(tag_m.group(1)) if tag_m else []
        find_m = re.search(r'(?:\*\*Analyst Findings\*\*|현장 데이터[^\n:]*?)[:：\*\s]+(.*?)(?=(?:\*\*Debate Summary\*\*|격돌하는 시각|데스크 판정|\*\*Domain Score\*\*|###|####|\Z))', sec_text, re.DOTALL)
        findings = find_m.group(1).strip() if find_m else ""
        deb_m = re.search(r'(?:\*\*Debate Summary\*\*|격돌하는 시각[^\n:]*?)[:：\*\s]+(.*?)(?=(?:\*\*Domain Score\*\*|데스크 판정|\*\*Analyst Findings\*\*|###|####|\Z))', sec_text, re.DOTALL)
        debate = deb_m.group(1).strip() if deb_m else ""
        if not findings:
            findings = re.sub(r'^[#*=\-\s]+', '', sec_text, flags=re.MULTILINE).strip()[:500]
        return {"bull": bull, "bear": bear, "tags": tags, "findings": findings if findings else "관측치 분석 완료.", "debate": debate}

    domains = {
        "Technical": parse_domain_block([r'\[Technical Analysis Report\]', r'###\s*market_report', r'차트·수급'], 50),
        "Fundamental": parse_domain_block([r'\[Fundamentals Report\]', r'###\s*fundamentals_report', r'기업·실적'], 50),
        "Sentiment": parse_domain_block([r'\[Social Sentiment Report\]', r'###\s*sentiment_report', r'여론·심리'], 50),
        "News": parse_domain_block([r'\[Macro & News Report\]', r'###\s*news_report', r'거시·외풍'], 50),
    }
    scores = {k: v["bull"] for k, v in domains.items()}
    return {
        "ticker": fallback_ticker, "decision": decision, "bias_label": bias_label,
        "executive_pulse": exec_pulse, "risk_synthesis": risk_synthesis,
        "scenarios": scenarios, "investment_thesis": investment_thesis,
        "final_strategy": investment_thesis if investment_thesis else risk_synthesis,
        "scores": scores, "domains": domains, "cleaned_full": raw_text,
    }


def create_radar_chart(scores: dict, ticker: str) -> go.Figure:
    categories = ["차트/수급", "기업실적", "거시환경", "투자심리"]
    values = [scores.get("Technical", 50), scores.get("Fundamental", 50), scores.get("News", 50), scores.get("Sentiment", 50)]
    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(r=values + [values[0]], theta=categories + [categories[0]], fill='toself', fillcolor='rgba(13, 148, 136, 0.25)', line=dict(color=TOKENS["accent"], width=1.5), name=ticker))
    fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(color=TOKENS["text_mute"], size=8), gridcolor=TOKENS["grid"]), angularaxis=dict(tickfont=dict(size=10, color=TOKENS["text_soft"]), gridcolor=TOKENS["grid"]), bgcolor=TOKENS["surface"]), template=TOKENS["plotly"], paper_bgcolor=TOKENS["bg"], plot_bgcolor=TOKENS["bg"], margin=dict(l=30, r=30, t=20, b=20), height=240, showlegend=False)
    return fig


# ==============================================================================
# 8. 인증 게이트웨이 (로그인 화면)
# ==============================================================================
if not st.session_state["auth_user"]:
    col_l1, col_l2, col_l3 = st.columns([1, 1.2, 1])
    with col_l2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown(
            """
            <div style="padding: 26px; border-radius: 10px; border: 1px solid var(--bb-border); background-color: var(--bb-card-bg); box-shadow: var(--bb-shadow);">
                <div style="display:flex; align-items:center; gap:10px; margin-bottom:14px;">
                    <div style="width:36px; height:36px; border-radius:8px; background:#0d9488; color:#fff; display:flex; align-items:center; justify-content:center; font-weight:800; font-size:16px;">HS</div>
                    <div>
                        <strong style="font-size:17px;">HEYstock Portal</strong>
                        <span style="font-size:11px; color:#64748b; display:block;">Quantitative Research & Weekly Briefing</span>
                    </div>
                </div>
                <div style="font-size:12.5px; color:#94a3b8; margin-bottom:18px;">
                    인증된 계정으로 로그인하여 주간 정량 리포트를 열람하거나 브리핑 포트폴리오를 관리하십시오.
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        with st.form("login_form"):
            in_user = st.text_input("아이디 (ID)", placeholder="admin 또는 user1")
            in_pw = st.text_input("비밀번호 (Password)", type="password", placeholder="비밀번호 입력")
            btn_login = st.form_submit_button("로그인", use_container_width=True, type="primary")

            if btn_login:
                users_map = get_users()
                if in_user in users_map and users_map[in_user]["pw"] == in_pw:
                    u_info = users_map[in_user].copy()
                    u_info["user_id"] = in_user
                    st.session_state["auth_user"] = u_info
                    st.success(f"{u_info['name']}님, 환영합니다.")
                    st.rerun()
                else:
                    st.error("아이디 또는 비밀번호가 일치하지 않습니다.")

        st.caption("• 관리자 테스트 계정: admin / admin1234\n• 유저 테스트 계정: user1 / 1234")
    st.stop()


# ==============================================================================
# 9. 사이드바 (엄격한 종목 검증 체계 반영)
# ==============================================================================
current_user = st.session_state["auth_user"]
is_admin = (current_user["role"] == "admin")

with st.sidebar:
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; justify-content:space-between; padding:2px 0 12px; border-bottom:1px solid var(--bb-border); margin-bottom:12px;">
            <div>
                <strong style="font-size:14px;">{current_user['name']}</strong>
                <span style="font-size:10px; color:{'#5eead4' if is_admin else '#94a3b8'}; display:block;">
                    {'👑 시스템 관리자' if is_admin else '👤 정기 구독 회원'}
                </span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    if st.button("로그아웃", use_container_width=True):
        st.session_state["auth_user"] = None
        st.rerun()

    # ---- 종목 탐색 및 캔들 차트 조회 (국내 / 해외 지원) ----
    with st.expander("종목 탐색 및 캔들 차트 조회", expanded=True):
        prev_us_mode = st.session_state["is_us_mode"]
        is_us_mode = st.toggle("🌐 해외(US) 주식 모드", value=prev_us_mode)
        st.session_state["is_us_mode"] = is_us_mode

        if is_us_mode != prev_us_mode:
            if is_us_mode:
                st.session_state["active_ticker"] = "TSLA"
                st.session_state["active_display_name"] = "테슬라"
                st.session_state["search_query_us"] = "테슬라"
            else:
                st.session_state["active_ticker"] = "080220.KQ"
                st.session_state["active_display_name"] = "제주반도체"
                st.session_state["search_query_kr"] = "제주반도체"
            st.rerun()

        # 1. 국내 주식 검색
        if not is_us_mode:
            current_q = st.session_state.get("search_query_kr", st.session_state.get("active_display_name", "제주반도체"))
            search_query = st.text_input("국내 종목 검색", value=current_q, placeholder="예: 삼전, 하닉, 047810, 카카오")
            st.session_state["search_query_kr"] = search_query

            matched_stocks = find_matched_stocks_kr(search_query, limit=5)
            if matched_stocks:
                st.markdown("<div style='font-size:11px; color:#64748b; font-weight:700; margin:6px 0 4px;'>🔍 추천 종목 선택</div>", unsafe_allow_html=True)
                for idx, item in enumerate(matched_stocks):
                    s_name, s_code, s_market = item["name"], item["code"], item["market"]
                    if st.button(f"🏢 {s_name} ({s_code} · {s_market})", key=f"nav_stock_kr_{idx}_{s_code}", use_container_width=True):
                        target_ticker, disp = normalize_input(f"{s_name} ({s_code})")
                        st.session_state["active_ticker"] = target_ticker
                        st.session_state["active_display_name"] = disp
                        st.session_state["search_query_kr"] = disp
                        st.rerun()
            selected_input = search_query

        # 2. 해외 주식 검색
        else:
            current_q_us = st.session_state.get("search_query_us", st.session_state.get("active_display_name", "TSLA"))
            search_query_us = st.text_input("해외 종목 검색 (이름 또는 티커)", value=current_q_us, placeholder="예: 테슬라, NVDA, 애플, PLTR, QQQ")
            st.session_state["search_query_us"] = search_query_us

            matched_us = find_matched_stocks_us(search_query_us, limit=5)
            if matched_us:
                st.markdown("<div style='font-size:11px; color:#64748b; font-weight:700; margin:6px 0 4px;'>🔍 추천 미국 종목 선택</div>", unsafe_allow_html=True)
                for idx, item in enumerate(matched_us):
                    u_name, u_code, u_market = item["name"], item["code"], item["market"]
                    if st.button(f"🏢 {u_name} ({u_code} · {u_market})", key=f"nav_stock_us_{idx}_{u_code}", use_container_width=True):
                        st.session_state["active_ticker"] = u_code
                        st.session_state["active_display_name"] = u_name
                        st.session_state["search_query_us"] = u_name
                        st.rerun()

            # [핵심] 임의 티커 입력 시 사전 검증 후 진입 허용 (가상/불량 티커 차단)
            raw_upper = search_query_us.strip().upper()
            if raw_upper and not any(item["code"] == raw_upper for item in matched_us):
                if st.button(f"🎯 '{raw_upper}' 티커 직접 조회", key="nav_stock_us_direct", use_container_width=True):
                    with st.spinner(f"'{raw_upper}' 티커 유효성 검증 중..."):
                        if is_valid_ticker_symbol(raw_upper):
                            st.session_state["active_ticker"] = raw_upper
                            st.session_state["active_display_name"] = raw_upper
                            st.session_state["search_query_us"] = raw_upper
                            st.rerun()
                        else:
                            st.error(f"❌ '{raw_upper}'은(는) 존재하지 않거나 시세 데이터를 가져올 수 없는 티커입니다.")

            selected_input = search_query_us

        # [관리자 전용] 단일 정량 분석 실행기
        if is_admin:
            st.markdown("---")
            today_date_str = datetime.date.today().strftime("%Y-%m-%d")
            st.caption(f"📅 기준일: {today_date_str} (단일 종목 테스트)")
            if st.button("단일 정량 분석 실행", type="primary", use_container_width=True):
                agent_ticker, disp_name = normalize_input(selected_input)
                if not is_valid_ticker_symbol(agent_ticker):
                    st.error(f"'{disp_name}'은(는) 유효하지 않은 종목으로 분석을 시작할 수 없습니다.")
                else:
                    st.session_state["active_ticker"] = agent_ticker
                    st.session_state["active_display_name"] = disp_name

                    task = st.session_state["analysis_task"]
                    task.update({
                        "status": "running", "ticker": agent_ticker, "display_name": disp_name,
                        "report_content": "", "report_path": None, "error_msg": "",
                        "start_time": time.time(), "just_finished": False,
                    })
                    threading.Thread(target=_run_admin_analysis_worker, args=(task, agent_ticker, disp_name, today_date_str), daemon=True).start()
                    st.rerun()

    # ---- [유저 전용] 주간 브리핑 포트폴리오 신청 폼 (유효성 검증 연동) ----
    if not is_admin:
        with st.expander("📌 내 주간 브리핑 신청함 (최대 3개)", expanded=True):
            st.caption("매주 월요일 카톡으로 받아볼 관심 종목을 담으세요.")
            cur_ticker = st.session_state["active_ticker"]
            cur_disp = st.session_state["active_display_name"]

            # [핵심] 현재 조회된 종목이 유효하지 않으면 담기 버튼 자체를 비활성화
            is_cur_valid = is_valid_ticker_symbol(cur_ticker)

            if not is_cur_valid:
                st.button(f"🚫 신청 불가 (데이터 없음)\n[{cur_disp} ({cur_ticker})]", disabled=True, use_container_width=True)
                st.caption("⚠️ 해당 종목은 시세 데이터가 없거나 유효하지 않아 신청할 수 없습니다.")
            else:
                if st.button(f"➕ 현재 조회 종목 담기\n[{cur_disp} ({cur_ticker})]", use_container_width=True):
                    ok, msg = save_user_request(current_user["user_id"], cur_ticker, cur_disp)
                    if ok: st.success(msg)
                    else: st.warning(msg)
                    st.rerun()

            user_reqs = get_requests().get(current_user["user_id"], [])
            if user_reqs:
                st.markdown("<div style='font-size:11px; color:#64748b; font-weight:700; margin-top:10px;'>현재 담은 종목:</div>", unsafe_allow_html=True)
                for req_item in user_reqs:
                    r_col1, r_col2 = st.columns([3, 1])
                    r_col1.markdown(f"• **{req_item['name']}** <span style='font-size:10px; color:#64748b;'>({req_item['ticker']})</span>", unsafe_allow_html=True)
                    if r_col2.button("삭제", key=f"del_req_{req_item['ticker']}"):
                        remove_user_request(current_user["user_id"], req_item["ticker"])
                        st.rerun()
            else:
                st.info("아직 담긴 종목이 없습니다. 유효한 종목을 선택한 후 추가하세요.")

    # ---- [보관된 리포트 열람] ----
    with st.expander("보관된 리포트 열람실", expanded=True):
        all_report_files = glob.glob("results/*.txt") + glob.glob("stock_db/**/*.txt", recursive=True)
        valid_files = sorted(list(set(f for f in all_report_files if os.path.isfile(f))), key=os.path.getmtime, reverse=True)

        filter_query = st.text_input("리포트 필터", placeholder="예: 한국항공우주, 테슬라, MSFT", key="report_search_input").strip().lower()
        filtered_files = [p for p in valid_files if not filter_query or filter_query in os.path.basename(p).lower()]

        report_options = {"-- 최근 결과 보기 --": None}
        for path in filtered_files:
            name = os.path.basename(path)
            saved_at = datetime.datetime.fromtimestamp(os.path.getmtime(path)).strftime("%m/%d %H:%M")
            report_options[f"{name} ({saved_at})"] = path

        selected_report_name = st.selectbox("리포트 선택", list(report_options.keys()))
        st.caption(f"열람 가능 리포트: 총 {len(valid_files)}건")

    if selected_report_name and report_options.get(selected_report_name):
        sel_path = report_options[selected_report_name]
        st.session_state["analysis_task"]["report_path"] = sel_path
        st.session_state["analysis_task"]["status"] = "complete"
        try:
            with open(sel_path, "r", encoding="utf-8") as f:
                st.session_state["analysis_task"]["report_content"] = f.read()
        except Exception:
            pass
        base_name = os.path.basename(sel_path)
        t_match = re.search(r'\(([-A-Za-z0-9\.]+)\)', base_name) or re.search(r'\]\s*([0-9A-Za-z\.\-]+)_', base_name) or re.search(r'\[([0-9A-Za-z\.\-]+)\]', base_name)
        if t_match:
            agent_sym, d_name = normalize_input(t_match.group(1))
            st.session_state["active_ticker"] = agent_sym
            st.session_state["active_display_name"] = d_name


# ==============================================================================
# 10. 관리자 전용: 고객 신청 종목 집계 & 수동 일괄 배치 산출 콕핏
# ==============================================================================
if is_admin:
    all_requests = get_requests()
    users_db = get_users()
    
    unique_stocks_dict = {}
    for uid, req_list in all_requests.items():
        user_name = users_db.get(uid, {}).get("name", uid)
        user_phone = users_db.get(uid, {}).get("phone", "미등록")
        for req in req_list:
            t = req["ticker"]
            if t not in unique_stocks_dict:
                unique_stocks_dict[t] = {
                    "ticker": t,
                    "name": req["name"],
                    "requesters": [f"{user_name} ({user_phone})"]
                }
            else:
                unique_stocks_dict[t]["requesters"].append(f"{user_name} ({user_phone})")
    
    unique_stocks_list = list(unique_stocks_dict.values())

    with st.expander("👑 [관리자 전용] 고객 신청 종목 종합 및 수동 일괄 산출 콕핏", expanded=False):
        b_col1, b_col2 = st.columns([1.6, 1])
        with b_col1:
            st.markdown(f"**총 신청 종목**: {len(unique_stocks_list)}건 (국내/해외 통합 중복 제거 완료)")
            if unique_stocks_list:
                req_table_data = []
                for s in unique_stocks_list:
                    req_table_data.append({
                        "종목명": s["name"],
                        "티커": s["ticker"],
                        "신청 고객 수": len(s["requesters"]),
                        "신청자 명단": ", ".join(s["requesters"])
                    })
                st.dataframe(pd.DataFrame(req_table_data), use_container_width=True, hide_index=True)
            else:
                st.info("현재 고객이 신청한 종목이 없습니다.")

        with b_col2:
            st.markdown("**수동 일괄 배치 컨트롤러**")
            st.caption("토요일 자동화 오류 대응 또는 사전 강제 산출용")
            batch_btn = st.button("🚀 신청 종목 전체 일괄 산출 시작", type="primary", use_container_width=True, disabled=(len(unique_stocks_list) == 0 or st.session_state["batch_task"]["status"] == "running"))
            
            if batch_btn:
                today_d = datetime.date.today().strftime("%Y-%m-%d")
                b_task = st.session_state["batch_task"]
                threading.Thread(target=_run_batch_worker, args=(b_task, unique_stocks_list, today_d), daemon=True).start()
                st.rerun()

        cur_batch = st.session_state["batch_task"]
        if cur_batch["status"] == "running":
            pct = cur_batch["current_idx"] / max(cur_batch["total"], 1)
            st.progress(pct)
            st.info(f"🔄 일괄 산출 진행 중 ({cur_batch['current_idx']}/{cur_batch['total']}): {cur_batch['current_stock']}")
            time.sleep(1)
            st.rerun()
        elif cur_batch["status"] == "complete":
            st.success(f"🎉 신청 종목 {cur_batch['total']}건에 대한 리포트 산출이 모두 완료되었습니다.")
            with st.expander("배치 실행 로그", expanded=False):
                for l in cur_batch["logs"]:
                    st.write(l)


# ==============================================================================
# 11. 메인 뷰어 (차트 + 3대 시나리오 리포트)
# ==============================================================================
current_ticker = st.session_state["active_ticker"]
current_display_name = st.session_state.get("active_display_name", current_ticker)
_task = st.session_state["analysis_task"]
status_chip = {"running": "PROCESSING", "complete": "READY", "error": "ERROR"}.get(_task["status"], "IDLE")

st.markdown(
    f"""
<div class="bb-hero">
  <div>
    <h1>{current_display_name} ({current_ticker}) | Strategic Intelligence & Consensus Desk</h1>
    <div class="bb-sub">정량 데이터 기반 멀티 에이전트 주간 브리핑 뷰어</div>
  </div>
  <div style="display:flex; gap:6px; align-items:center;">
    <span class="bb-chip">접속 권한: {'관리자 (Admin)' if is_admin else '회원 (Member)'}</span>
    <span class="bb-chip">{datetime.date.today():%Y-%m-%d}</span>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# ---- 섹션 A: 시세 차트 ----
c_head, c_slider = st.columns([1.6, 1])
with c_head:
    st.markdown("#### Market Price & Technical Structure")
with c_slider:
    lookback = st.slider("조회 범위 (일)", min_value=30, max_value=365, value=180, step=30, key="chart_slider")

df = fetch_cached_chart_data(current_ticker, lookback)

if not df.empty:
    latest = df.iloc[-1]
    prev_close = df.iloc[-2]["Close"] if len(df) > 1 else latest["Close"]
    pct_change = ((latest["Close"] - prev_close) / prev_close) * 100

    is_kr = current_ticker.endswith((".KS", ".KQ"))
    c_fmt = f"{int(round(latest['Close'])):,}원" if is_kr else f"${latest['Close']:.2f}"
    e10_fmt = f"{int(round(latest['EMA10'])):,}원" if is_kr else f"${latest['EMA10']:.2f}"
    e20_fmt = f"{int(round(latest['EMA20'])):,}원" if is_kr else f"${latest['EMA20']:.2f}"
    bu_fmt = f"{int(round(latest['BB_UPPER'])):,}원" if is_kr else f"${latest['BB_UPPER']:.2f}"
    bl_fmt = f"{int(round(latest['BB_LOWER'])):,}원" if is_kr else f"${latest['BB_LOWER']:.2f}"

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Close", c_fmt, f"{pct_change:+.2f}%")
    col2.metric("10 EMA", e10_fmt)
    col3.metric("20 EMA", e20_fmt)
    col4.metric("Bollinger Upper", bu_fmt)
    col5.metric("Bollinger Lower", bl_fmt)

    fig = build_interactive_chart(df, current_ticker)
    try:
        fig.update_layout(template=TOKENS["plotly"], paper_bgcolor=TOKENS["bg"], plot_bgcolor=TOKENS["bg"], font=dict(color=TOKENS["text"]))
        fig.update_xaxes(gridcolor=TOKENS["grid"], tickfont=dict(color=TOKENS["text_soft"]))
        fig.update_yaxes(gridcolor=TOKENS["grid"], tickfont=dict(color=TOKENS["text_soft"]))
    except Exception:
        pass
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info(f"{current_display_name} ({current_ticker}) 시장 데이터를 수신할 수 없습니다.")

st.markdown("---")

# ---- 섹션 B: 리포트 뷰어 (실시간 타이머 / 다운로드) ----
cur_task = st.session_state["analysis_task"]

if cur_task["status"] == "running":
    elapsed = int(time.time() - cur_task["start_time"])
    mins, secs = divmod(elapsed, 60)
    disp = cur_task.get("display_name", cur_task["ticker"])
    st.markdown(
        f"""
        <div style="border-radius:8px; padding:18px 20px; border:1px solid var(--bb-border); background-color:var(--bb-card-bg); margin-bottom:16px;">
            <div style="display:flex; align-items:center; justify-content:space-between;">
                <span style="font-size:14px; font-weight:700; color:#5eead4;">⏳ [분석 진행 중] {disp} ({cur_task['ticker']})</span>
                <span style="font-family:ui-monospace, monospace; font-size:13px; font-weight:700; color:#fbbf24; background:rgba(245,158,11,0.15); padding:4px 10px; border-radius:4px; border:1px solid rgba(245,158,11,0.3);">
                    ⏱ 경과 시간: {mins:02d}분 {secs:02d}초
                </span>
            </div>
            <div style="font-size:12.5px; color:var(--bb-text-soft); margin-top:8px; line-height:1.6;">
                • 4대 도메인(차트, 실적, 심리, 거시) 데이터 수집 및 에이전트 간 리스크 대립 토론 진행 중<br>
                • 완료 즉시 새로고침 없이 화면이 자동 전환됩니다.
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )
    time.sleep(1)
    st.rerun()

elif cur_task["status"] == "error":
    st.error(f"오류 발생: {cur_task['error_msg']}")

else:
    report_text = cur_task.get("report_content", "")
    target_path = cur_task.get("report_path")
    if not report_text and target_path and os.path.exists(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                report_text = f.read()
        except Exception: pass

    if not report_text:
        st.info("좌측 [보관된 리포트 열람실]에서 리포트를 선택하여 주간 정량 분석 내용을 확인하십시오.")
    else:
        parsed = parse_full_report_statefully(report_text, fallback_ticker=current_ticker)
        safe_dl_label = get_safe_stock_label(current_ticker, current_display_name)
        
        dl_content = parsed["cleaned_full"]
        for meta_k in ["company_of_interest", "asset_type", "instrument_context", "trade_date", "sender"]:
            dl_content = re.sub(rf'###\s*{meta_k}\s*\n[^\n#]+(\n\n)?', '', dl_content).strip()

        h_col1, h_col2 = st.columns([1.6, 1])
        with h_col1:
            st.subheader("Multi-Agent Consensus & Scenario Map")
        with h_col2:
            st.download_button(
                label="📥 전체 리포트 다운로드 (.txt)",
                data=dl_content,
                file_name=f"[{safe_dl_label}]_{datetime.date.today():%Y%m%d}_Report.txt",
                mime="text/plain",
                use_container_width=True,
            )

        if parsed["executive_pulse"]:
            tag_spans = "".join([f'<span class="pulse-tag">{tag}</span>' for tag in parsed["executive_pulse"]])
            st.markdown(f'<div class="pulse-tag-group"><span class="pulse-tag-lead">EXECUTIVE PULSE</span>{tag_spans}</div>', unsafe_allow_html=True)

        dec = parsed["decision"]
        pill_class = "pill-hold"
        upper_dec = dec.upper()
        if any(w in upper_dec for w in ["BUY", "OVERWEIGHT", "BULL"]): pill_class = "pill-buy"
        elif any(w in upper_dec for w in ["SELL", "UNDERWEIGHT", "BEAR", "CAUTION"]): pill_class = "pill-sell"

        r_col1, r_col2 = st.columns([1.2, 0.8])
        with r_col1:
            st.markdown(
                f"""
                <div class="decision-container">
                    <span class="decision-label">MULTI-AGENT CONSENSUS</span>
                    <span class="decision-pill {pill_class}">{dec} ({parsed['bias_label']})</span>
                </div>
                """,
                unsafe_allow_html=True
            )
            if parsed["risk_synthesis"]:
                st.markdown(f'<div class="strategy-card"><b>Risk & Market Synthesis</b>{parsed["risk_synthesis"]}</div>', unsafe_allow_html=True)

        with r_col2:
            st.markdown("<div style='font-size:11px; color:#64748b; text-transform:uppercase; margin-bottom:4px;'>Domain Balance Radar</div>", unsafe_allow_html=True)
            st.plotly_chart(create_radar_chart(parsed["scores"], current_ticker), use_container_width=True)

        sc = parsed["scenarios"]
        if sc["bull"] or sc["neutral"] or sc["bear"]:
            st.markdown("#### Strategic Scenario Map")
            sc_col1, sc_col2, sc_col3 = st.columns(3)
            with sc_col1:
                st.markdown(f'<div class="scenario-box sc-bull"><div class="sc-title">[Bullish Extension] 상방 확장</div><div class="sc-body">{sc["bull"]}</div></div>', unsafe_allow_html=True)
            with sc_col2:
                st.markdown(f'<div class="scenario-box sc-neu"><div class="sc-title">[Neutral Consolidation] 박스권 및 횡보</div><div class="sc-body">{sc["neutral"]}</div></div>', unsafe_allow_html=True)
            with sc_col3:
                st.markdown(f'<div class="scenario-box sc-bear"><div class="sc-title">[Downside Invalidation] 하방 무효화</div><div class="sc-body">{sc["bear"]}</div></div>', unsafe_allow_html=True)

        if parsed["investment_thesis"]:
            st.markdown(f'<div class="strategy-card" style="border-left: 3px solid #0d9488;"><b>Quantitative Investment Thesis</b>{parsed["investment_thesis"]}</div>', unsafe_allow_html=True)

        st.markdown("---")
        st.markdown("### Domain Analysis & Observational Data")
        domain_cards = [
            ("Technical", "📈 차트 및 수급 분석 (Technical Structure)"),
            ("Fundamental", "🏢 기업 가치 및 재무 분석 (Fundamental Valuation)"),
            ("Sentiment", "💬 투자 심리 및 여론 분석 (Market Sentiment)"),
            ("News", "🌍 거시 경제 및 지정학 분석 (Macro & World Affairs)"),
        ]
        for row in (domain_cards[:2], domain_cards[2:]):
            cols = st.columns(2)
            for col, (key, label) in zip(cols, row):
                data = parsed["domains"][key]
                with col:
                    with st.expander(label, expanded=True):
                        if data.get("tags"):
                            dtags = "".join([f'<span class="pulse-tag">{t}</span>' for t in data["tags"]])
                            st.markdown(f'<div style="margin-bottom:8px;">{dtags}</div>', unsafe_allow_html=True)
                        st.progress(min(max(data["bull"], 0), 100) / 100)
                        st.caption(f"Bull {data['bull']}% | Bear {data['bear']}%")
                        st.markdown(f'<div class="desk-block"><strong>📌 핵심 관측 팩트</strong><br>{data["findings"]}</div>', unsafe_allow_html=True)
                        if data.get("debate"):
                            st.markdown(f'<div class="desk-block"><strong>⚔️ 격돌하는 시각</strong><br>{data["debate"]}</div>', unsafe_allow_html=True)

st.markdown(
    '<div style="display:flex; justify-content:space-between; margin-top:32px; padding:12px 0 4px; border-top:1px solid rgba(255,255,255,0.12); color:#64748b; font-size:11px; font-family:monospace;">'
    '<span>[SYSTEM] Quantitative Connection Monitored</span><span>HEYstock Research Platform</span></div>',
    unsafe_allow_html=True,
)