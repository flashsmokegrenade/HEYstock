"""Pydantic schemas used by agents that produce structured output (Scenario Map & Hashtag Pulse)."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

_NULLISH_FLOAT = {"", "none", "n/a", "na", "null", "nil", "-", "tbd", "unknown"}

def _coerce_optional_float(value):
    if isinstance(value, str) and value.strip().lower() in _NULLISH_FLOAT:
        return None
    return value

# ---------------------------------------------------------------------------
# Market Bias Rating Enum (Global Standard Quantitative Market Bias)
# ---------------------------------------------------------------------------

class MarketBiasRating(str, Enum):
    BULLISH_LEANING = "BULLISH LEANING (Positive Momentum Bias)"
    BALANCED = "BALANCED (Neutral & Mixed Signals)"
    BEARISH_LEANING = "BEARISH LEANING (Downside Risk Caution)"

# Backward compatibility alias
PortfolioRating = MarketBiasRating

class TraderAction(str, Enum):
    BUY = "Buy"
    HOLD = "Hold"
    SELL = "Sell"

# ---------------------------------------------------------------------------
# 1~4. 4 Domain Analysts Common Schema
# ---------------------------------------------------------------------------

class DomainReport(BaseModel):
    """Structured report produced by the 4 Domain Analysts."""
    
    hashtags: list[str] = Field(
        default_factory=list,
        description="2-3 punchy, high-signal hashtags capturing the core analytical takeaway (e.g. ['#단기조정경계', '#중기추세유효', '#볼린저하단지지']).",
    )
    analyst_findings: str = Field(
        description="Key objective data, metrics, and facts summarized by the analyst. 4-6 sentences.",
    )
    debate_summary: str = Field(
        description="Summary of the arguments between the Bullish and Bearish researchers regarding these findings.",
    )
    bull_score: int = Field(
        ge=0,
        le=100,
        description="Bullish intensity score from 0 to 100.",
    )
    bear_score: int = Field(
        ge=0,
        le=100,
        description="Bearish intensity score from 0 to 100. (Usually 100 - bull_score)",
    )

    @field_validator("hashtags", mode="before")
    @classmethod
    def clean_hashtags(cls, v):
        if isinstance(v, str):
            v = [t.strip() for t in v.replace(",", " ").split() if t.strip()]
        if isinstance(v, list):
            return [f"#{item.lstrip('#')}" for item in v if isinstance(item, str) and item.strip()]
        return []

    @model_validator(mode="after")
    def normalize_scores_to_hundred(self):
        """Automatically normalizes scores to sum to 100%."""
        total = self.bull_score + self.bear_score
        if total != 100 and total > 0:
            self.bull_score = round((self.bull_score / total) * 100)
            self.bear_score = 100 - self.bull_score
        elif total == 0:
            self.bull_score = 50
            self.bear_score = 50
        return self

def render_domain_report(domain_name: str, report: DomainReport) -> str:
    """Render a DomainReport to markdown format with visual hashtag pulse."""
    total = report.bull_score + report.bear_score
    bull = report.bull_score
    bear = report.bear_score
    
    if total != 100 and total > 0:
        bull = round((bull / total) * 100)
        bear = 100 - bull
    elif total == 0:
        bull, bear = 50, 50

    tags_display = " ".join(report.hashtags) if report.hashtags else ""
    header_line = f"### {domain_name} Analysis"
    if tags_display:
        header_line += f"\n> ⚡ **Quick Pulse**: {tags_display}"

    return "\n".join([
        header_line,
        f"**Analyst Findings**: {report.analyst_findings}",
        "",
        f"**Debate Summary**: {report.debate_summary}",
        "",
        f"**Domain Score**: [Bull Score: 📈 {bull} / Bear Score: 📉 {bear}]",
        "---"
    ])

# ---------------------------------------------------------------------------
# 5. Trader's Initial Strategy (Trader)
# ---------------------------------------------------------------------------

class TraderProposal(BaseModel):
    """Structured transaction proposal produced by the Trader."""

    action: TraderAction = Field(
        description="The technical positioning bias. Exactly one of Buy / Hold / Sell.",
    )
    reasoning: str = Field(
        description=(
            "The synthesis of the 4 Domain Bull/Bear scores and technical momentum scenarios. "
            "Frame as objective market observations. DO NOT provide actionable financial advice or personal trade commands."
        ),
    )
    entry_price: float | None = Field(
        default=None,
        description="Optional technical reference price level in the instrument's quote currency.",
    )
    stop_loss: float | None = Field(
        default=None,
        description="Optional technical support/invalidation level in the instrument's quote currency.",
    )

    @field_validator("entry_price", "stop_loss", mode="before")
    @classmethod
    def _nullish_float_to_none(cls, v):
        return _coerce_optional_float(v)

def render_trader_proposal(proposal: TraderProposal) -> str:
    """Render TraderProposal as the 5th section: Trader's Initial Strategy & Summary."""
    parts = [
        "### Trader's Initial Strategy & Summary",
        f"**Initial Action**: {proposal.action.value}",
        "",
        f"**Score Synthesis & Rationale**: {proposal.reasoning}",
    ]
    if proposal.entry_price is not None:
        parts.extend(["", f"**Reference Level**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Invalidation Level**: {proposal.stop_loss}"])
    
    parts.append("---")
    return "\n".join(parts)

# ---------------------------------------------------------------------------
# 6. Final Consensus & Risk Synthesis (Scenario-Based Map with Hashtags)
# ---------------------------------------------------------------------------

class PortfolioDecision(BaseModel):
    """Structured output produced by the Portfolio Manager with Scenario Mapping & Hashtag Pulse."""

    hashtags: list[str] = Field(
        default_factory=list,
        description="3-4 ultra-short, punchy hashtags summarizing the entire market regime and key focus (e.g. ['#신호혼재', '#10EMA회복주시', '#장기금리부담', '#변동성유의']).",
    )
    rating: MarketBiasRating = Field(
        description=(
            "The synthesized quantitative market bias based strictly on indicator weight. "
            "Select exactly one of:\n"
            "- 'BULLISH LEANING (Positive Momentum Bias)': Positive fundamental/technical skew\n"
            "- 'BALANCED (Neutral & Mixed Signals)': Mixed signals, requiring observational patience\n"
            "- 'BEARISH LEANING (Downside Risk Caution)': Downside momentum or valuation pressure"
        ),
    )
    risk_evaluation: str = Field(
        description=(
            "Objective quantitative synthesis contrasting technical momentum against fundamental/macro risks. "
            "STRICT COMPLIANCE: NO actionable trade advice, NO commands, NO derivatives."
        ),
    )
    bullish_scenario: str = Field(
        description=(
            "Detailed conditions and observation thresholds for the upside expansion scenario (Bullish Extension). "
            "Focus on key technical breakout triggers and fundamental tailwinds to monitor."
        ),
    )
    neutral_scenario: str = Field(
        description=(
            "Detailed conditions and observation thresholds for the sideways/consolidation scenario (Neutral Consolidation). "
            "Focus on mean-reversion levels, moving average supports, and range-bound indicators."
        ),
    )
    bearish_scenario: str = Field(
        description=(
            "Detailed conditions and observation thresholds for the downside risk scenario (Downside Invalidation). "
            "Focus on trend breakdown triggers, support failures, and macroeconomic pressure points."
        ),
    )
    investment_thesis: str = Field(
        description=(
            "Detailed quantitative reasoning anchored in domain scores and risk debate. "
            "STRICT COMPLIANCE: DO NOT use investment recommendation language (Overweight, Buy, Hold). "
            "Use objective market regime terms. NO past performance citations."
        ),
    )

    @field_validator("hashtags", mode="before")
    @classmethod
    def clean_hashtags(cls, v):
        if isinstance(v, str):
            v = [t.strip() for t in v.replace(",", " ").split() if t.strip()]
        if isinstance(v, list):
            return [f"#{item.lstrip('#')}" for item in v if isinstance(item, str) and item.strip()]
        return []

    @field_validator("rating", mode="before")
    @classmethod
    def normalize_legacy_ratings(cls, v):
        """Automatically maps legacy ratings to new market bias definitions."""
        if isinstance(v, str):
            v_upper = v.upper()
            if any(k in v_upper for k in ["OVERWEIGHT", "BUY", "BULLISH"]):
                return MarketBiasRating.BULLISH_LEANING
            elif any(k in v_upper for k in ["UNDERWEIGHT", "SELL", "BEARISH", "CAUTION"]):
                return MarketBiasRating.BEARISH_LEANING
            elif any(k in v_upper for k in ["HOLD", "NEUTRAL", "BALANCED"]):
                return MarketBiasRating.BALANCED
        return v

def render_pm_decision(decision: PortfolioDecision) -> str:
    """Render a PortfolioDecision with Scenario Mapping and Hashtag Pulse."""
    rating_val = decision.rating.value
    tags_str = " ".join(decision.hashtags) if decision.hashtags else ""
    
    parts = ["### Integrated Market Perspectives"]
    if tags_str:
        parts.append(f"> ⚡ **Executive Pulse**: {tags_str}\n")
        
    parts.extend([
        f"**Risk & Market Synthesis**: {decision.risk_evaluation}",
        "",
        "**Strategic Scenario Map (시나리오 맵)**:",
        f"1. **Bullish Extension Scenario (상방 확장)**: {decision.bullish_scenario}",
        f"2. **Neutral Consolidation Scenario (횡보 및 박스권)**: {decision.neutral_scenario}",
        f"3. **Downside Invalidation Scenario (하방 리스크)**: {decision.bearish_scenario}",
        "",
        f"**Investment Thesis** {'[' + tags_str + ']' if tags_str else ''}:",
        f"{decision.investment_thesis}",
        "",
        "==================================================",
        f"MULTI-AGENT CONSENSUS: **{rating_val}**",
        "=================================================="
    ])
    return "\n".join(parts)

# ---------------------------------------------------------------------------
# Research Manager
# ---------------------------------------------------------------------------

class ResearchPlan(BaseModel):
    """Structured investment plan produced by the Research Manager."""

    recommendation: MarketBiasRating = Field(
        description="The market consensus bias. Exactly one of BULLISH LEANING / BALANCED / BEARISH LEANING.",
    )
    rationale: str = Field(
        description="Conversational summary of key points from both sides of the debate. DO NOT cite specific past returns.",
    )
    strategic_actions: str = Field(
        description="Objective technical and fundamental observation levels to monitor. NO actionable advice or percentage allocations.",
    )

def render_research_plan(plan: ResearchPlan) -> str:
    """Render a ResearchPlan to markdown for downstream consumption."""
    return "\n".join([
        f"**Market Bias**: {plan.recommendation.value}",
        "",
        f"**Rationale**: {plan.rationale}",
        "",
        f"**Key Thresholds to Monitor**: {plan.strategic_actions}",
    ])