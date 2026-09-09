"""Portfolio Manager: Synthesizes risk debate and domain findings into a structured Scenario Map, Hashtag Pulse, and Consensus."""

from __future__ import annotations

from tradingagents.agents.schemas import PortfolioDecision, render_pm_decision
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_portfolio_manager(llm):
    structured_llm = bind_structured(llm, PortfolioDecision, "Portfolio Manager")

    def portfolio_manager_node(state) -> dict:
        company_name = state.get("company_of_interest", "")
        instrument_context = get_instrument_context_from_state(state)

        market_report = state.get("market_report", "")
        sentiment_report = state.get("sentiment_report", "")
        news_report = state.get("news_report", "")
        fundamentals_report = state.get("fundamentals_report", "")

        trader_plan = state.get("trader_investment_plan", "")
        investment_plan = state.get("investment_plan", "")

        risk_debate_state = state.get("risk_debate_state", {})
        risk_history = risk_debate_state.get("history", "")

        prompt = f"""You are the Lead Portfolio Manager and Chief Risk Synthesizer for {company_name}.
Your mission is to evaluate the adversarial debate between the Aggressive, Conservative, and Neutral Risk Analysts, and synthesize the findings into an institutional-grade **Strategic Scenario Map** with an ultra-short **Hashtag Pulse**.

{instrument_context}

---
### INPUT DATA SNAPSHOTS:
- Technical Findings: {market_report[:600]}
- Sentiment Findings: {sentiment_report[:500]}
- Macro & News Findings: {news_report[:500]}
- Fundamental Findings: {fundamentals_report[:500]}
- Trader's Proposal: {trader_plan}
- Research Manager Consensus Plan: {investment_plan}

---
### RISK DEBATE CONTEXT (Aggressive vs. Conservative vs. Neutral):
{risk_history}

---
### STRICT OUTPUT & GOVERNANCE REQUIREMENTS:
1. **HASHTAG PULSE REQUIREMENT (MANDATORY)**:
   - Provide 3-4 ultra-short, highly intuitive hashtags in the 'hashtags' field (e.g. ['#단기모멘텀약화', '#10EMA회복주시', '#밸류에이션부담', '#200SMA지지']).
   - Busy institutional readers should understand the entire market regime within 3 seconds just by reading these hashtags.
2. **SCENARIO MAPPING REQUIREMENT**:
   - **Bullish Extension Scenario**: Specific breakout triggers (e.g., EMA/SMA holds, resistance breaks), underlying growth momentum tailwinds, and continuation criteria.
   - **Neutral Consolidation Scenario**: Mean-reversion boundaries, Bollinger band/moving average ranges, and waiting criteria for directional clarity.
   - **Downside Invalidation Scenario**: Key support breakdown triggers, macroeconomic/multiple compression factors, and structural failure levels.
3. **COMPLIANCE CONSTRAINTS (SEC Rule 206(4)-1)**:
   - NO broker ratings ('Overweight', 'Underweight', 'Buy', 'Sell').
   - NO actionable trade commands or portfolio percentage allocations (e.g., 'trim 30%', 'allocate 10%').
   - NO derivatives (options, futures, straddles, covered calls).
   - NO cherry-picked past performance numbers.
4. **OBJECTIVE MARKET BIAS SCALE**: Select strictly one rating:
   - 'BULLISH LEANING (Positive Momentum Bias)'
   - 'BALANCED (Neutral & Mixed Signals)'
   - 'BEARISH LEANING (Downside Risk Caution)'

Synthesize all analyst findings objectively and provide the structured Scenario Map and Hashtags.""" + get_language_instruction()

        decision = invoke_structured_or_freetext(
            structured_llm,
            llm,
            prompt,
            render_pm_decision,
            "Portfolio Manager",
        )

        if isinstance(decision, PortfolioDecision):
            rendered_report = render_pm_decision(decision)
        else:
            rendered_report = str(decision)

        new_risk_debate_state = {
            **risk_debate_state,
            "judge_decision": rendered_report,
        }

        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": rendered_report,
            "portfolio_decision": decision,
        }

    return portfolio_manager_node