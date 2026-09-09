"""Trader: synthesizes the Research Manager's investment plan into an objective market regime and execution scenario analysis."""

from __future__ import annotations

import functools

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
                    "You are a Market Execution & Technical Regime Analyst. "
                    "Your role is to objectively assess market momentum, liquidity conditions, and risk-reward scenarios "
                    "based on the analysts' reports and the research plan.\n\n"
                    "STRICT COMPLIANCE RULES:\n"
                    "1. DO NOT provide direct actionable trade advice or personal orders to the user. "
                    "NEVER specify explicit portfolio allocation percentages (e.g., do NOT say 'reduce by 30-50%' or 'exit position immediately').\n"
                    "2. NEVER recommend options, futures, put spreads, covered calls, or any derivatives.\n"
                    "3. NEVER cite cherry-picked historical returns or specific alpha figures (e.g., TSLA +4.0%).\n"
                    "4. Frame all price levels as 'Key Technical Scenarios & Support/Resistance Levels to Observe' "
                    "rather than personal stop-loss or trade triggers.\n"
                    "5. Synthesize your final action/stance purely as an analytical assessment of current market momentum "
                    "and risk-reward skew, not as an investment mandate."
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

        trader_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            messages,
            render_trader_proposal,
            "Trader",
        )

        return {
            "messages": [AIMessage(content=trader_plan)],
            "trader_investment_plan": trader_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")