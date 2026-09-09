"""Research Manager: synthesizes the bull/bear debate into an objective market regime and scenario analysis (English Native Compliance)."""

from __future__ import annotations

from tradingagents.agents.schemas import ResearchPlan, render_research_plan
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_research_manager(llm):
    structured_llm = bind_structured(llm, ResearchPlan, "Research Manager")

    def research_manager_node(state) -> dict:
        instrument_context = get_instrument_context_from_state(state)
        history = state["investment_debate_state"].get("history", "")
        investment_debate_state = state["investment_debate_state"]

        prompt = f"""As the Research Facilitator and Quantitative Debate Synthesizer, your role is to critically evaluate this round of debate and provide an objective synthesis of the market regime, consensus bias, and key observation thresholds in professional English.

{instrument_context}

---

**Observed Market Bias Scale** (Select exactly one based on observed evidence weight):
- **BULLISH LEANING (Positive Momentum Bias)**: Positive fundamental profitability, cash flow, and long-term technical trend indicators outweigh downside risks.
- **BALANCED (Neutral & Mixed Signals)**: Long-term structural support and short-term momentum deceleration (or macro/yield pressure) are genuinely balanced.
- **BEARISH LEANING (Downside Risk Caution)**: Short-term trend breakdown, valuation pressure, macroeconomic tightening, or regulatory/legal risks dominate the data.

Commit to an objective analytical stance based strictly on data weight; use BALANCED only when both sides of the debate are truly equal.

---

**COMPLIANCE CONSTRAINTS (STRICT):**
1. DO NOT provide actionable financial advice, trade orders, or portfolio allocation percentages (e.g., NEVER say "reduce by 30%", "sell now", or "chase buy").
2. Frame all strategic actions and triggers as "Key Price & Indicator Thresholds to Monitor" rather than personal stop-loss or trade triggers.
3. NEVER mention options, futures, put spreads, covered calls, or any derivatives.
4. NEVER cite cherry-picked historical returns or specific alpha numbers (e.g., TSLA +4.0%).
5. NEVER use broker recommendation terms like 'Overweight' or 'Underweight'. Use strictly 'BULLISH LEANING', 'BALANCED', or 'BEARISH LEANING'.

---

**Debate History:**
{history}""" + get_language_instruction()

        investment_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_research_plan,
            "Research Manager",
        )

        new_investment_debate_state = {
            "judge_decision": investment_plan,
            "history": investment_debate_state.get("history", ""),
            "bear_history": investment_debate_state.get("bear_history", ""),
            "bull_history": investment_debate_state.get("bull_history", ""),
            "current_response": investment_plan,
            "count": investment_debate_state["count"],
        }

        return {
            "investment_debate_state": new_investment_debate_state,
            "investment_plan": investment_plan,
        }

    return research_manager_node