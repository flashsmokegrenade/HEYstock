import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

import re
import argparse
from datetime import datetime

from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

# [연동] 종목 입력 변환기 및 리포트 정제 포매터 임포트
from ticker_resolver import resolve_stock_input
from report_formatter import build_readable_report


class DualLogger:
    def __init__(self):
        self.terminal = sys.stdout
        self.log = []

    def write(self, message):
        self.terminal.write(message)
        self.log.append(message)

    def flush(self):
        self.terminal.flush()

    def get_content(self):
        raw_text = "".join(self.log)
        cleaned_text = re.sub(r'\n{3,}', '\n\n', raw_text).strip()
        return cleaned_text


def extract_final_decision(full_log: str) -> str:
    """컴플라이언스 신규 정량 바이어스 태그(MULTI-AGENT CONSENSUS)를 최우선 추출하고 레거시 태그도 호환합니다."""
    match = re.search(r"MULTI-AGENT CONSENSUS:\s*\*\*?([A-Za-z0-9 \(\)\/\-_가-힣]+)\*\*?", full_log, re.IGNORECASE)
    if match:
        val = match.group(1).upper().strip()
        if "BULLISH" in val:
            return "BULLISH_LEANING"
        elif "BEARISH" in val:
            return "BEARISH_LEANING"
        elif "BALANCED" in val or "NEUTRAL" in val or "HOLD" in val:
            return "BALANCED"
        return re.sub(r'[\s/]+', '_', val)

    match = re.search(r"FINAL TRANSACTION PROPOSAL:\s*\*\*?([A-Za-z_]+)\*\*?", full_log, re.IGNORECASE)
    if match:
        return match.group(1).upper().strip()
    
    match = re.search(r"================ (?:최종 결정|종합 분석 요약|CONSENSUS SUMMARY) ================\s*\n\s*(?:최종 투자의견|종합 관점|MULTI-AGENT CONSENSUS)?\s*[:：]?\s*([A-Za-z_ /\(\)가-힣]+)", full_log, re.IGNORECASE)
    if match:
        return match.group(1).upper().strip()
        
    return "BALANCED"


def get_safe_stock_label(ticker: str, corp_name: str | None = None) -> str:
    """한글 사명과 티커를 결합한 안전한 파일명 레이블 생성 (예: 한국항공우주(047810.KS) 또는 AAPL)"""
    if not corp_name or corp_name == ticker:
        try:
            resolved = resolve_stock_input(ticker)
            corp_name = resolved.get("corp_name", ticker)
        except Exception:
            corp_name = ticker

    if corp_name and corp_name != ticker:
        label = f"{corp_name}({ticker})"
    else:
        label = ticker

    # 윈도우 파일명 금지 특수문자 (\ / : * ? " < > |) 제거
    return re.sub(r'[\\/*?:"<>|]', "", label).strip()


def save_report_to_desktop(ticker: str, target_date: str, full_log: str, final_decision: str, corp_name: str | None = None):
    user_profile = os.environ.get("USERPROFILE", os.path.expanduser("~"))

    candidate_paths = [
        os.path.join(user_profile, "OneDrive", "Desktop"),
        os.path.join(user_profile, "OneDrive", "바탕 화면"),
        os.path.join(user_profile, "Desktop"),
        os.path.join(user_profile, "바탕 화면"),
    ]

    desktop_path = None
    for path in candidate_paths:
        if os.path.exists(path):
            desktop_path = path
            break

    if not desktop_path:
        desktop_path = os.path.join(CURRENT_DIR, "desktop_output")

    base_dir = os.path.join(desktop_path, "stock_db")

    # 기존 폴더명 호환 및 컴플라이언스 폴더 지원
    def resolve_folder(candidates, default_name):
        for c in candidates:
            p = os.path.join(base_dir, c)
            if os.path.exists(p):
                return p
        return os.path.join(base_dir, default_name)

    b_dir = resolve_folder(["1_Momentum_Outperformance", "1_Buy_Overweight", "1_Buy_Bullish"], "1_Momentum_Outperformance")
    h_dir = resolve_folder(["2_Neutral_Balance", "2_Hold", "2_Hold_Neutral"], "2_Neutral_Balance")
    s_dir = resolve_folder(["3_Defensive_Caution", "3_Sell_Underweight", "3_Sell_Bearish"], "3_Defensive_Caution")

    folder_map = {
        "BULLISH": b_dir,
        "BALANCED": h_dir,
        "BEARISH": s_dir,
    }

    for path in folder_map.values():
        os.makedirs(path, exist_ok=True)

    dec_upper = final_decision.upper()
    if any(k in dec_upper for k in ["BULLISH", "BUY", "OVERWEIGHT"]):
        target_folder = folder_map["BULLISH"]
        file_tag = "BULLISH_LEANING"
    elif any(k in dec_upper for k in ["BEARISH", "SELL", "UNDERWEIGHT", "CAUTION"]):
        target_folder = folder_map["BEARISH"]
        file_tag = "BEARISH_LEANING"
    else:
        target_folder = folder_map["BALANCED"]
        file_tag = "BALANCED"

    timestamp = datetime.now().strftime("%H%M%S")
    
    # [핵심] 한글 사명이 포함된 안전한 파일명 생성 (예: [2026-10-04] 한국항공우주(047810.KS)_BEARISH_LEANING_115914.txt)
    stock_label = get_safe_stock_label(ticker, corp_name)
    file_name = f"[{target_date}] {stock_label}_{file_tag}_{timestamp}.txt"
    file_path = os.path.join(target_folder, file_name)

    # [가독성 정제 적용] 한국식 통화단위 치환, 불릿포인트 시나리오 맵, 최상단 대시보드 조립
    beautified_report = build_readable_report(full_log, ticker, target_date, final_decision)
    clean_log_for_file = beautified_report.rstrip() + "\n"

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(clean_log_for_file)

    print(f"\n[📁 자동 저장 완료] 리포트가 성공적으로 분류 저장되었습니다:")
    print(f"-> 저장 경로: {file_path}")


def main():
    today_str = datetime.now().strftime("%Y-%m-%d")

    parser = argparse.ArgumentParser(description="TradingAgents Global Research System")
    parser.add_argument("--ticker", type=str, required=True, help="Stock ticker symbol")
    parser.add_argument("--date", type=str, default=today_str, help="Analysis date (YYYY-MM-DD), defaults to today")
    parser.add_argument("--models", type=str, default="gpt-4o-mini", help="LLM model to use")
    parser.add_argument("--rounds", type=int, default=1, help="Number of rounds (Default: 1)")
    parser.add_argument("--lang", type=str, default="en", choices=["ko", "en"], help="Report language: 'ko' (Korean) or 'en' (English)")
    
    args = parser.parse_args()

    # [종목 정규화] 한글 회사명, 순수 숫자 6자리 코드, 미국 티커 자동 매핑
    stock_info = resolve_stock_input(args.ticker)
    target_ticker = stock_info["agent_ticker"]
    corp_name = stock_info.get("corp_name", target_ticker)

    logger = DualLogger()
    original_stdout = sys.stdout
    sys.stdout = logger

    success = False
    final_decision = "BALANCED"

    try:
        print(f"🚀 분석을 시작합니다... [종목: {corp_name} ({target_ticker}) | 기준 날짜: {args.date} | 언어: {args.lang.upper()}]")

        config = DEFAULT_CONFIG.copy()
        
        # 1. 실행 속도 유지
        config["max_debate_rounds"] = args.rounds
        config["max_risk_discuss_rounds"] = args.rounds
        
        # 2. 메모리 로그 의존성 물리적 차단
        config["memory_log_max_entries"] = 0
        if "enable_memory" in config:
            config["enable_memory"] = False
        
        # 3. 글로벌 컴플라이언스(SEC 표준) 엄격 시스템 지침 주입
        target_lang = "fluent, professional Korean" if args.lang == "ko" else "professional Wall Street English"
        
        compliance_instruction = (
            f"\n\n[GLOBAL REGULATORY COMPLIANCE DIRECTIVES (SEC RULE 206(4)-1 & INVESTMENT ADVISERS ACT):\n"
            f"1. REASONING IN ENGLISH: Conduct all internal analyst debates and intermediate data evaluations strictly in English.\n"
            f"2. FINAL REPORT LANGUAGE: The final consensus report MUST be written entirely in {target_lang}.\n"
            f"3. ABSOLUTELY NO ACTIONABLE ADVICE: Never instruct the user what to do with their capital. "
            f"Never specify portfolio allocation percentages. Frame all price levels strictly as objective 'Key Observation Thresholds' for trend monitoring.\n"
            f"4. NO DERIVATIVES: Never mention options, put spreads, call spreads, or covered calls.\n"
            f"5. NO PAST PERFORMANCE CITATIONS: Never cite previous winning trades, historical returns, or specific alpha numbers.\n"
            f"6. MARKET BIAS TERMINOLOGY: Never use broker ratings like 'Overweight' or 'Underweight'. Use strictly 'BULLISH LEANING', 'BALANCED', or 'BEARISH LEANING'.\n"
            f"7. MANDATORY HEADER: Format the final synthesis strictly under '### Integrated Market Perspectives' "
            f"with section '### Key Observation Points' and end with 'MULTI-AGENT CONSENSUS: [BULLISH LEANING | BALANCED | BEARISH LEANING]'.\n"
            f"8. INDEPENDENT SNAPSHOT: Evaluate the instrument strictly and independently based only on the current market data provided.]"
        )
        
        if "system_prompt_suffix" in config:
            config["system_prompt_suffix"] += compliance_instruction
        else:
            config["system_prompt_suffix"] = compliance_instruction

        ta = TradingAgentsGraph(debug=True, config=config)
        ta.propagate(target_ticker, args.date)

        full_text = logger.get_content()
        final_decision = extract_final_decision(full_text)
        
        print("\n================ 종합 분석 요약 ================")
        print(f"MULTI-AGENT CONSENSUS: {final_decision}")
        print("================================================")
        
        success = True

    except Exception as e:
        print(f"\n❌ [오류 발생] 분석 중 문제가 발생했습니다: {e}")

    finally:
        full_text = logger.get_content()
        sys.stdout = original_stdout

        if success:
            # corp_name을 전달하여 파일명에 한글 사명이 포함되도록 저장
            save_report_to_desktop(target_ticker, args.date, full_text, final_decision, corp_name=corp_name)
        else:
            print("\n⚠️ 분석이 정상 완료되지 않아 파일 저장을 건너뜁니다.")


if __name__ == "__main__":
    main()