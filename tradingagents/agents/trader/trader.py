"""Trader: synthesizes the Research Manager's investment plan into an objective market regime and execution scenario analysis."""

from __future__ import annotations

import functools
import re

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import TraderProposal, render_trader_proposal
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def _sanitize_trader_output(plan_text: str) -> str:
    """법적 리스크 방지: 직접 매매 명령(Buy/Sell/Hold)을 객관적 정량 편향(Quantitative Bias)으로 자동 정제."""
    if not plan_text:
        return plan_text

    # 1. 헤더 정제
    cleaned = plan_text.replace(
        "### Trader's Initial Strategy & Summary",
        "### Market Execution & Technical Summary",
    )
    cleaned = cleaned.replace(
        "Trader's Initial Strategy & Summary",
        "Market Execution & Technical Summary",
    )

    # 2. 직접 매매 액션(Initial Action) -> 정량적 기술 편향(Quantitative Bias)으로 치환
    cleaned = re.sub(
        r"\*\*Initial Action\*\*:\s*Buy\b",
        "**Quantitative Bias**: 상방 모멘텀 (Bullish Momentum)",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\*\*Initial Action\*\*:\s*Sell\b",
        "**Quantitative Bias**: 하방 리스크 (Downside Caution)",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\*\*Initial Action\*\*:\s*Hold\b",
        "**Quantitative Bias**: 신호 균형 및 관망 (Neutral Balance)",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\*\*Initial Action\*\*:", "**Quantitative Bias**:", cleaned)

    return cleaned


def create_trader(llm):
    structured_llm = bind_structured(llm, TraderProposal, "Trader")

    def trader_node(state, name):
        company_name = state["company_of_interest"]
        instrument_context = get_instrument_context_from_state(state)
        investment_plan = state["investment_plan"]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a Market Execution & Quantitative Regime Analyst. "
                    "Your role is to objectively assess market momentum, volatility regime, and statistical risk-reward balance "
                    "based on the analysts' reports and the research plan.\n\n"
                    "STRICT COMPLIANCE RULES (자본시장법 준수 및 정량 리서치 원칙):\n"
                    "1. DO NOT provide direct trade advice, execution orders, or personal mandates. "
                    "NEVER tell the user to 'Buy', 'Sell', or 'Hold'. Never use imperative trading commands.\n"
                    "2. NEVER specify explicit portfolio allocation percentages (e.g., do NOT say 'reduce by 30-50%' or 'exit position').\n"
                    "3. NEVER recommend options, futures, put spreads, covered calls, or any derivatives.\n"
                    "4. NEVER cite cherry-picked historical returns or specific alpha figures (e.g., TSLA +4.0%).\n"
                    "5. Frame all price levels strictly as 'Key Technical Observation Levels (지지/저항 분기점)' "
                    "rather than personal stop-loss, profit-taking, or entry triggers.\n"
                    "6. Formulate your execution bias purely as an objective 'Quantitative Bias (정량적 편향)' "
                    "(e.g., 상방 모멘텀, 하방 리스크, 신호 균형 및 관망) reflecting indicator alignment, NOT as an investment decision."
                    + get_language_instruction()
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Based on a comprehensive analysis by a team of analysts, here is an objective research "
                    f"synthesis for {company_name}. {instrument_context} This plan incorporates "
                    f"insights from current technical market trends, macroeconomic indicators, and "
                    f"social media sentiment. Use this synthesis as a foundation for formulating objective "
                    f"execution scenarios and evaluating key price and indicator thresholds.\n\n"
                    f"Proposed Research Synthesis: {investment_plan}\n\n"
                    f"Synthesize these insights into an objective technical execution scenario analysis."
                ),
            },
        ]

        raw_trader_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            messages,
            render_trader_proposal,
            "Trader",
        )

        # 법적 준수를 위한 출력 문자열 사후 정제
        trader_plan = _sanitize_trader_output(raw_trader_plan)

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")