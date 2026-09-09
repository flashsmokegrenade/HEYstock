# TradingAgents/graph/trading_graph.py

import json
import logging
import os
import sys
import contextlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yfinance as yf
from langgraph.prebuilt import ToolNode

# ================= [yfinance 시스템 에러 로그 화면 출력 완벽 차단] =================
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
# ===================================================================================

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_balance_sheet,
    get_cashflow,
    get_fundamentals,
    get_global_news,
    get_income_statement,
    get_indicators,
    get_insider_transactions,
    get_macro_indicators,
    get_news,
    get_prediction_markets,
    get_stock_data,
    get_verified_market_snapshot,
    resolve_instrument_identity,
)
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.reporting import write_report_tree

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .propagation import Propagator
from .reflection import Reflector
from .setup import GraphSetup
from .signal_processing import SignalProcessor

logger = logging.getLogger(__name__)


def _coerce_max_retries(value):
    """Validate an ``llm_max_retries`` value to a non-negative int."""
    if isinstance(value, bool):
        raise ValueError(f"llm_max_retries must be an integer, not a boolean: {value!r}")
    try:
        n = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"llm_max_retries must be an integer, got {value!r}") from exc
    if n < 0:
        raise ValueError(f"llm_max_retries must be >= 0, got {n}")
    return n


def _sanitize_compliance_text(text: str) -> str:
    """
    글로벌(영문/국문) 규정 준수 가드레일 (SEC Rule 206(4)-1 & Investment Advisers Act):
    1. 과거 성과/알파 인용 차단 (Past Performance Cherry-picking)
    2. 계좌 자산 비율(%), 분수(1/3, 1/2) 및 변칙 매매 지시 차단 (선진입, 청산 등)
    3. 파생상품(옵션) 언급 차단 (No Derivatives)
    4. 명령문 및 트리거를 객관적 모니터링 기준선으로 치환
    5. 레거시 헤더 강제 치환
    """
    if not text or not isinstance(text, str):
        return text

    # 1. 과거 특정 추천 성과 및 수익률/알파 인용 전면 차단
    text = re.sub(r'(?:past|historical|prior|과거|직전|이전).*?(?:return|gain|alpha|수익|알파|overweight|buy|sell|call).*?[\+\-]?\d+(?:\.\d+)?%?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'[\+\-]?\d+(?:\.\d+)?%\s*(?:alpha|gain|return|profit|알파|초과\s*수익)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'alpha\s*vs\s*SPY.*?([,\n\)]|\Z)', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\+?nan%', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\([A-Z]{1,5}\s*(?:case|example|사례).*?\)', '', text, flags=re.IGNORECASE)

    # 2. 계좌 포지션 비율(%), 분수(1/3, 1/2) 및 매매 행동 지시어 차단
    action_keywords = r'(?:선진입|진입|청산|정리|담아|감산|매도|축소|손절|현금화|감축|이익실현|추가|테스트|익절|비중|할당|매수)'
    ratio_pattern = r'(?:\d+~\d+%|\d+%\s*to\s*\d+%|\d+%|\d+/\d+\s*~\s*\d+/\d+|\d+/\d+)'
    
    text = re.sub(rf'{ratio_pattern}\s*(?:부근\s*)?{action_keywords}', '단계적 리스크 노출 조절', text)
    text = re.sub(rf'{action_keywords}\s*(?:시\s*)?{ratio_pattern}', '단계적 리스크 노출 조절', text)
    text = re.sub(rf'목표\s*포지션의\s*{ratio_pattern}', '일부 분할 관측', text)
    text = re.sub(rf'보유분\s*{ratio_pattern}\s*이익실현', '모멘텀 과열 여부 확인', text)
    text = re.sub(r'(?:잔여\s*)?(?:대부분\s*정리|\d+~\d+%\s*청산)', '추세 이탈 경계 관측', text)

    # 영문 비율 지시어 차단
    text = re.sub(r'\b(?:trim|reduce|cut|sell|take profit on|allocate|add)\s*(?:\d+~\d+%|\d+%\s*to\s*\d+%|\d+%)\b', 'monitor exposure thresholds', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(?:\d+~\d+%|\d+%\s*to\s*\d+%|\d+%)\s*(?:allocation|reduction|cut|trim|profit-taking)\b', 'exposure observation', text, flags=re.IGNORECASE)

    # 3. 파생상품(옵션/헤지) 언급 차단
    derivatives_pattern = r'\b(put spread|call spread|covered call|protective put|straddle|options? hedge|puts? and calls?|풋스프레드|커버드콜|풋옵션|콜옵션|스프레드|옵션\s*헤지)\b'
    text = re.sub(derivatives_pattern, 'risk management scenario', text, flags=re.IGNORECASE)

    # 4. 행동 트리거(Trigger) -> 관측 기준선(Observation Threshold) 전환
    text = re.sub(r'\b(?:buy|sell|stop-loss|trim)\s*triggers?\b', 'key observation thresholds', text, flags=re.IGNORECASE)
    text = re.sub(r'\b(?:감축|증액|매수|손절|익절|축소)\s*트리거\b', '주요 관측 기준선(Observation Threshold)', text)
    text = re.sub(r'즉시\s*(?:풀사이즈\s*)?금지', '단계적 시장 확인 구간', text)
    text = re.sub(r'추격\s*매수\s*금지', '추격 진입 주의 구간 관측', text)

    # 5. 레거시 헤더 강제 치환
    text = re.sub(r'###\s*Final Execution & Conclusion', '### Integrated Market Perspectives', text, flags=re.IGNORECASE)
    text = re.sub(r'\*\*Executive Summary\*\*\s*[:：]', '**Key Observation Points:**', text, flags=re.IGNORECASE)
    text = re.sub(r'FINAL TRANSACTION PROPOSAL\s*[:：]', 'MULTI-AGENT CONSENSUS:', text, flags=re.IGNORECASE)
    text = re.sub(r'최종\s*(?:투자의견|결정)\s*[:：]', '종합 분석 관점:', text, flags=re.IGNORECASE)

    return text


class TradingAgentsGraph:
    """Main class that orchestrates the trading agents framework."""

    def __init__(
        self,
        selected_analysts=("market", "social", "news", "fundamentals"),
        debug=False,
        config: dict[str, Any] = None,
        callbacks: list | None = None,
    ):
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []

        set_config(self.config)

        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        llm_kwargs = self._get_provider_kwargs()

        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()

        self.memory_log = TradingMemoryLog(self.config)
        self.tool_nodes = self._create_tool_nodes()

        self.conditional_logic = ConditionalLogic(
            max_debate_rounds=self.config["max_debate_rounds"],
            max_risk_discuss_rounds=self.config["max_risk_discuss_rounds"],
        )
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
        )

        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 100),
        )
        self.reflector = Reflector(self.quick_thinking_llm)
        self.signal_processor = SignalProcessor(self.quick_thinking_llm)

        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}

        self.selected_analysts = tuple(selected_analysts)
        self.workflow = self.graph_setup.setup_graph(selected_analysts)
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None

    def _get_provider_kwargs(self) -> dict[str, Any]:
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()

        if provider == "google":
            thinking_level = self.config.get("google_thinking_level")
            if thinking_level:
                kwargs["thinking_level"] = thinking_level
        elif provider == "openai":
            reasoning_effort = self.config.get("openai_reasoning_effort")
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
        elif provider == "anthropic":
            effort = self.config.get("anthropic_effort")
            if effort:
                kwargs["effort"] = effort

        temperature = self.config.get("temperature")
        if temperature is not None and temperature != "":
            kwargs["temperature"] = float(temperature)

        max_retries = self.config.get("llm_max_retries")
        if max_retries is not None and max_retries != "":
            kwargs["max_retries"] = _coerce_max_retries(max_retries)

        return kwargs

    def _create_tool_nodes(self) -> dict[str, ToolNode]:
        return {
            "market": ToolNode([get_stock_data, get_indicators, get_verified_market_snapshot]),
            "social": ToolNode([get_news]),
            "news": ToolNode([get_news, get_global_news, get_insider_transactions, get_macro_indicators, get_prediction_markets]),
            "fundamentals": ToolNode([get_fundamentals, get_balance_sheet, get_cashflow, get_income_statement]),
        }

    def _resolve_benchmark(self, ticker: str) -> str:
        explicit = self.config.get("benchmark_ticker")
        if explicit:
            return explicit
        benchmark_map = self.config.get("benchmark_map", {})
        ticker_upper = ticker.upper()
        for suffix, benchmark in benchmark_map.items():
            if suffix and ticker_upper.endswith(suffix.upper()):
                return benchmark
        return benchmark_map.get("", "SPY")

    def _fetch_returns(
        self, ticker: str, trade_date: str, holding_days: int = 5,
        benchmark: str = "SPY",
    ) -> tuple[float | None, float | None, int | None]:
        from tradingagents.dataflows.symbol_utils import normalize_symbol

        try:
            start = datetime.strptime(trade_date, "%Y-%m-%d")
            end = start + timedelta(days=holding_days + 7)
            end_str = end.strftime("%Y-%m-%d")

            with open(os.devnull, 'w') as devnull:
                with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                    stock = yf.Ticker(normalize_symbol(ticker)).history(start=trade_date, end=end_str)
                    bench = yf.Ticker(benchmark).history(start=trade_date, end=end_str)

            if len(stock) < 2 or len(bench) < 2:
                return None, None, None

            actual_days = min(holding_days, len(stock) - 1, len(bench) - 1)
            raw = float((stock["Close"].iloc[actual_days] - stock["Close"].iloc[0]) / stock["Close"].iloc[0])
            bench_ret = float((bench["Close"].iloc[actual_days] - bench["Close"].iloc[0]) / bench["Close"].iloc[0])
            alpha = raw - bench_ret
            return raw, alpha, actual_days
        except Exception as e:
            logger.warning("Could not resolve outcome for %s on %s vs %s: %s", ticker, trade_date, benchmark, e)
            return None, None, None

    def _resolve_pending_entries(self, ticker: str) -> None:
        pending = [e for e in self.memory_log.get_pending_entries() if e["ticker"] == ticker]
        if not pending:
            return

        benchmark = self._resolve_benchmark(ticker)
        updates = []
        for entry in pending:
            raw, alpha, days = self._fetch_returns(ticker, entry["date"], benchmark=benchmark)
            if raw is None:
                continue
            reflection = self.reflector.reflect_on_final_decision(
                final_decision=entry.get("decision", ""),
                raw_return=raw,
                alpha_return=alpha,
                benchmark_name=benchmark,
            )
            updates.append({
                "ticker": ticker,
                "trade_date": entry["date"],
                "raw_return": raw,
                "alpha_return": alpha,
                "holding_days": days,
                "reflection": reflection,
            })

        if updates:
            self.memory_log.batch_update_with_outcomes(updates)

    def resolve_instrument_context(self, ticker: str, asset_type: str = "stock") -> str:
        identity = resolve_instrument_identity(ticker)
        return build_instrument_context(ticker, asset_type, identity)

    def _run_signature(self, asset_type: str) -> str:
        return "|".join([
            "analysts=" + ",".join(self.selected_analysts),
            f"debate={self.config['max_debate_rounds']}",
            f"risk={self.config['max_risk_discuss_rounds']}",
            f"asset={asset_type}",
        ])

    def propagate(self, company_name, trade_date, asset_type: str = "stock"):
        self.ticker = company_name.split('\n')[0].strip()

        self._resolve_pending_entries(self.ticker)

        if self.config.get("checkpoint_enabled"):
            self._checkpointer_ctx = get_checkpointer(self.config["data_cache_dir"], self.ticker)
            saver = self._checkpointer_ctx.__enter__()
            self.graph = self.workflow.compile(checkpointer=saver)

            step = checkpoint_step(
                self.config["data_cache_dir"], self.ticker, str(trade_date),
                self._run_signature(asset_type),
            )
            if step is not None:
                logger.info("Resuming from step %d for %s on %s", step, self.ticker, trade_date)
            else:
                logger.info("Starting fresh for %s on %s", self.ticker, trade_date)

        try:
            return self._run_graph(self.ticker, trade_date, asset_type=asset_type)
        finally:
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()

    def save_reports(self, final_state, ticker, save_path=None) -> Path:
        if save_path is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = (Path(self.config["results_dir"]) / "reports" / f"{safe_ticker_component(ticker)}_{stamp}")
        return write_report_tree(final_state, ticker, save_path)

    def _run_graph(self, company_name, trade_date, asset_type: str = "stock"):
        """Execute the graph and write the resulting state to disk and memory log."""
        pure_company = company_name.split('\n')[0].strip()

        # ==============================================================================
        # [컴플라이언스 핵심] 과거 추천 수익률/알파 인용 원천 차단 (SEC Rule 206(4)-1)
        # memory_log에서 과거 수익률 주입을 배제하여 LLM의 체리피킹 인용을 원천 차단합니다.
        # ==============================================================================
        past_context = ""

        instrument_context = self.resolve_instrument_context(pure_company, asset_type)

        init_agent_state = self.propagator.create_initial_state(
            pure_company,
            trade_date,
            asset_type=asset_type,
            past_context=past_context,
            instrument_context=instrument_context,
        )
        args = self.propagator.get_graph_args()

        if self.config.get("checkpoint_enabled"):
            tid = thread_id(pure_company, str(trade_date), self._run_signature(asset_type))
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid

        # 안정적인 그래프 일괄 실행
        print("\n🔄 에이전트들이 데이터 수집, 토론 및 리스크 검증을 진행 중입니다... (약 1~2분 소요)")
        final_state = self.graph.invoke(init_agent_state, **args)

        self.curr_state = final_state

        # ================= [컴플라이언스 후처리 및 안전망] =================
        try:
            report_keys = ["market_report", "sentiment_report", "news_report", "fundamentals_report", "final_trade_decision"]
            for r_key in report_keys:
                content = final_state.get(r_key, "")
                if content and isinstance(content, str):
                    content = _sanitize_compliance_text(content)

                    # 구버전 환각 데이터 필터링
                    if "2023" in content:
                        lines = content.split('\n')
                        clean_lines = [l for l in lines if not any(x in l for x in ["2023", "AAPL", "MSFT", "GOOG"])]
                        content = '\n'.join(clean_lines)

                    # 최종 결론 최하단 법적 면책 조항 강제 추가 (글로벌 표준 영문/국문 병기)
                    if r_key == "final_trade_decision" and "Disclaimer" not in content:
                        disclaimer_text = (
                            "\n\n==================================================\n"
                            "[Disclaimer / 법적 고지]\n"
                            "This report is an automated quantitative research summary synthesized by AI multi-agents "
                            "based on publicly available market data. It does NOT constitute financial advice, investment recommendations, "
                            "or an endorsement to buy or sell securities. All investment decisions and associated risks rest solely with the user.\n\n"
                            "본 보고서는 AI 멀티 에이전트 시스템이 공시 데이터 및 기술 지표를 바탕으로 자동 생성한 정량적 관측 요약본이며, "
                            "금융투자상품의 매수/매도를 권유하거나 투자 자문을 제공하지 않습니다. 모든 투자 판단과 책임은 투자자 본인에게 있습니다.\n"
                            "=================================================="
                        )
                        content = content.strip() + disclaimer_text

                    final_state[r_key] = content
        except Exception as filter_error:
            logger.warning("보고서 필터링 과정에서 예외 발생: %s", filter_error)

        # ================= [리포트 터미널 출력 헤더 동기화] =================
        report_titles = {
            "market_report": "Technical Analysis Report",
            "sentiment_report": "Social Sentiment Report",
            "news_report": "Macro & News Report",
            "fundamentals_report": "Fundamentals Report",
            "final_trade_decision": "Multi-Agent Consensus & Risk Synthesis"
        }
        for r_key, title_name in report_titles.items():
            clean_content = final_state.get(r_key, "")
            if clean_content and isinstance(clean_content, str):
                sys.stdout.write(f"\n{'='*50}\n[{title_name}]\n{'='*50}\n{clean_content.strip()}\n")
                sys.stdout.flush()

        # ================= [디스크에 데이터 기록] =================
        self._log_state(trade_date, final_state)

        if final_state.get("final_trade_decision"):
            self.memory_log.store_decision(
                ticker=pure_company,
                trade_date=trade_date,
                final_trade_decision=final_state["final_trade_decision"],
            )

        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(
                self.config["data_cache_dir"], pure_company, str(trade_date),
                self._run_signature(asset_type),
            )

        return final_state, self.process_signal(final_state.get("final_trade_decision", ""))

    def _log_state(self, trade_date, final_state):
        self.log_states_dict[str(trade_date)] = {
            "company_of_interest": final_state.get("company_of_interest", ""),
            "trade_date": final_state.get("trade_date", str(trade_date)),
            "market_report": final_state.get("market_report", ""),
            "sentiment_report": final_state.get("sentiment_report", ""),
            "news_report": final_state.get("news_report", ""),
            "fundamentals_report": final_state.get("fundamentals_report", ""),
            "investment_debate_state": {
                "bull_history": final_state.get("investment_debate_state", {}).get("bull_history", []),
                "bear_history": final_state.get("investment_debate_state", {}).get("bear_history", []),
                "history": final_state.get("investment_debate_state", {}).get("history", []),
                "current_response": final_state.get("investment_debate_state", {}).get("current_response", ""),
                "judge_decision": final_state.get("investment_debate_state", {}).get("judge_decision", ""),
            },
            "trader_investment_decision": final_state.get("trader_investment_plan", ""),
            "risk_debate_state": {
                "aggressive_history": final_state.get("risk_debate_state", {}).get("aggressive_history", []),
                "conservative_history": final_state.get("risk_debate_state", {}).get("conservative_history", []),
                "neutral_history": final_state.get("risk_debate_state", {}).get("neutral_history", []),
                "history": final_state.get("risk_debate_state", {}).get("history", []),
                "judge_decision": final_state.get("risk_debate_state", {}).get("judge_decision", ""),
            },
            "investment_plan": final_state.get("investment_plan", ""),
            "final_trade_decision": final_state.get("final_trade_decision", ""),
        }

        safe_ticker = safe_ticker_component(self.ticker)
        directory = Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_states_log_{trade_date}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_states_dict[str(trade_date)], f, indent=4)

    def process_signal(self, full_signal):
        return self.signal_processor.process_signal(full_signal)