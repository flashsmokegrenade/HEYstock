import os
import re
import time
import datetime
from database import get_unique_tickers_for_batch, save_batch_report
from report_formatter import generate_kakao_report_card

# TradingAgentsGraph 임포트
try:
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    from tradingagents.default_config import DEFAULT_CONFIG
except ImportError:
    TradingAgentsGraph = None
    DEFAULT_CONFIG = None


def extract_analysis_metrics(raw_text: str, ticker: str, market: str) -> dict:
    """
    에이전트 원문 리포트에서 카톡 카드 생성용 점수, 해시태그, 가격, 요약 문장 정밀 추출
    """
    clean_text = raw_text.replace(',', '')

    # 1. 도메인별 Bull 점수 추출
    def get_score(sec_keyword: str) -> int:
        pattern = rf"{sec_keyword}.*?Bull\s*Score\s*[:：]?\s*(?:📈\s*)?(\d+)"
        match = re.search(pattern, clean_text, re.IGNORECASE | re.DOTALL)
        if match:
            return int(match.group(1))
        match_alt = re.search(r'Bull\s*Score\s*[:：]?\s*(\d+)', clean_text, re.IGNORECASE)
        return int(match_alt.group(1)) if match_alt else 50

    f_score = get_score("Fundamental")
    t_score = get_score("Technical")
    s_score = get_score("Sentiment")
    m_score = get_score("Macro|News")

    # 2. 현재가 추출
    price_match = re.search(r'종가[^\d\n]*([0-9]+(?:\.[0-9]+)?)', clean_text)
    current_price = float(price_match.group(1)) if price_match else 100.0

    # 3. 지지선 / 저항선 추출 (동일 라인 한정 [^\d\n] 적용 및 이상치 방어)
    res_match = re.search(r'(?:저항선|볼린저\s*(?:밴드\s*)?상단)[^\d\n]*([0-9]+(?:\.[0-9]+)?)', clean_text)
    resistance_price = float(res_match.group(1)) if res_match else round(current_price * 1.05, 2)

    sup_match = re.search(r'(?:지지선|볼린저\s*(?:밴드\s*)?하단|50\s*SMA|10\s*EMA)[^\d\n]*([0-9]+(?:\.[0-9]+)?)', clean_text)
    support_price = float(sup_match.group(1)) if sup_match else round(current_price * 0.95, 2)

    # 비정상 수치(현재가의 50% 미만 또는 200% 초과) 필터링 방어
    if resistance_price < current_price * 0.7 or resistance_price > current_price * 1.5:
        resistance_price = round(current_price * 1.05, 2 if market == "US" else 0)
    if support_price < current_price * 0.7 or support_price > current_price * 1.5:
        support_price = round(current_price * 0.95, 2 if market == "US" else 0)

    if support_price > resistance_price:
        support_price, resistance_price = resistance_price, support_price

    # 4. Quick Pulse에서 실제 해시태그(#...) 정밀 추출 (re.DOTALL 적용)
    def get_tags(domain_name: str, fallback: str) -> str:
        pattern = rf'###\s*{domain_name}.*?Quick\s*Pulse\*\*:\s*([^\n]+)'
        match = re.search(pattern, raw_text, re.IGNORECASE | re.DOTALL)
        if match:
            words = match.group(1).split()
            tags = [w.strip() for w in words if w.startswith('#')]
            if tags:
                return " ".join(tags[:3])
        return fallback

    # 5. 1줄 요약 추출
    def get_summary_line(domain_name: str, fallback: str) -> str:
        pattern = rf'###\s*{domain_name}.*?\*\*Analyst Findings\*\*:\s*([^\n]+)'
        match = re.search(pattern, raw_text, re.IGNORECASE | re.DOTALL)
        if match:
            full_line = match.group(1).strip()
            sentences = re.split(r'(?<=[가-힣a-zA-Z다요음임])\.\s+', full_line)
            if sentences:
                res = sentences[0].strip()
                return res if res.endswith(".") else f"{res}."
        return fallback

    corp_name = "삼성전자" if ticker == "005930" else ticker

    return {
        "ticker": ticker,
        "corp_name": corp_name,
        "currency": "KRW" if market == "KR" else "USD",
        "current_price": current_price,
        "fundamental_score": f_score,
        "fundamental_tags": get_tags("Fundamental", "#기초체력확인 #재무안정성"),
        "fundamental_summary": get_summary_line("Fundamental", "안정적인 현금흐름과 재무 기초체력이 유지되고 있습니다."),
        "technical_score": t_score,
        "technical_tags": get_tags("Technical", "#추세관찰 #변동성체크"),
        "technical_summary": get_summary_line("Technical", "단기 및 중기 이동평균선 상단에서 추세를 형성 중입니다."),
        "sentiment_score": s_score,
        "sentiment_tags": get_tags("Sentiment", "#심리탐색 #소셜반응"),
        "sentiment_summary": get_summary_line("Sentiment", "소매 투자자의 관심과 매수 우위 심리가 확인됩니다."),
        "macro_score": m_score,
        "macro_tags": get_tags("News", "#거시환경 #금리영향"),
        "macro_summary": get_summary_line("News", "시장 금리 변동성 및 거시 지표 추이를 관측 중입니다."),
        "resistance_price": resistance_price,
        "support_price": support_price,
    }


def run_weekend_batch(target_date_str: str = None, limit: int = None, test_tickers: list = None):
    """
    주말 정기 배치 작업 실행
    """
    if not target_date_str:
        target_date_str = datetime.date.today().strftime("%Y-%m-%d")

    print("==================================================")
    print(f"🚀 [HEYstock] 주말 정기 배치 가동 (기준일: {target_date_str})")
    print("==================================================")

    targets = get_unique_tickers_for_batch()
    if not targets:
        print("[INFO] 등록된 활성 구독 종목이 없습니다. 배치를 종료합니다.")
        return

    if test_tickers:
        targets = [t for t in targets if t["ticker"].upper() in [x.upper() for x in test_tickers]]
    elif limit:
        targets = targets[:limit]

    print(f"[INFO] 이번 배치 분석 대상: 총 {len(targets)}개 종목 {[t['ticker'] for t in targets]}\n")

    if TradingAgentsGraph:
        graph = TradingAgentsGraph(config=DEFAULT_CONFIG.copy()) if DEFAULT_CONFIG else TradingAgentsGraph()
    else:
        print("[WARN] TradingAgentsGraph 모듈을 찾을 수 없습니다. 시뮬레이션 모드로 진행합니다.")
        graph = None

    results_dir = os.path.join(os.getcwd(), "results")
    os.makedirs(results_dir, exist_ok=True)

    success_count = 0
    fail_count = 0

    for idx, item in enumerate(targets, 1):
        ticker = item["ticker"]
        market = item["market"]

        # 국내 주식 접미사 자동 부착
        agent_ticker = ticker
        if market == "KR" and not ticker.endswith((".KS", ".KQ")):
            agent_ticker = f"{ticker}.KS"

        print(f"[{idx}/{len(targets)}] {ticker} (수집 심볼: {agent_ticker}) 분석 중...")

        try:
            full_report_text = ""

            if graph:
                result = graph.propagate(agent_ticker, target_date_str)
                final_state = result[0] if isinstance(result, tuple) and len(result) > 0 else result

                if isinstance(final_state, dict):
                    parts = [f"### {k}\n{v}" for k, v in final_state.items() if isinstance(v, str) and v.strip()]
                    full_report_text = "\n\n".join(parts)
                elif isinstance(final_state, str):
                    full_report_text = final_state
            else:
                full_report_text = f"### Technical Analysis\n종가 72000 저항선 75000 지지선 70000\nBull Score: 60"

            # 원본 상세 텍스트 저장
            file_name = f"[{ticker}]_{target_date_str.replace('-', '')}_batch_report.txt"
            file_path = os.path.join(results_dir, file_name)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(full_report_text)

            # 카톡용 카드 텍스트 생성 (해시태그 + 메타포 포함)
            metrics = extract_analysis_metrics(full_report_text, ticker, market)
            kakao_card = generate_kakao_report_card(metrics)

            total_score = round((metrics["fundamental_score"] + metrics["technical_score"] + 
                                metrics["sentiment_score"] + metrics["macro_score"]) / 4)
            consensus = "BULLISH_LEANING" if total_score >= 60 else ("BEARISH_LEANING" if total_score <= 40 else "NEUTRAL")

            report_id = save_batch_report(
                ticker=ticker,
                batch_date=target_date_str,
                total_score=total_score,
                consensus=consensus,
                kakao_card_text=kakao_card,
                full_report_path=file_path
            )

            print(f"  -> ✅ 저장 완료 (Report ID: {report_id} | 종합점수: {total_score}점)")
            success_count += 1

        except Exception as e:
            print(f"  -> ❌ [{ticker}] 분석 중 오류 발생: {e}")
            fail_count += 1

        time.sleep(1)

    print("\n==================================================")
    print(f"🏁 주말 배치 완료: 성공 {success_count}건 / 실패 {fail_count}건")
    print("==================================================")


if __name__ == "__main__":
    run_weekend_batch(test_tickers=["005930", "NVDA"])