"""Sentiment analyst — multi-source sentiment analysis for a target ticker.

Previously named ``social_media_analyst``. Renamed and redesigned because
the old version had a prompt that demanded social-media analysis but the
only tool available was Yahoo Finance news.

The redesigned agent pre-fetches two complementary data sources before
the LLM is invoked and injects them into the prompt as structured blocks:

  1. News headlines     — Yahoo Finance (institutional framing)
  2. StockTwits messages — retail-trader posts indexed by cashtag, with
                         user-labeled Bullish/Bearish sentiment tags

The agent does not use tool-calling; the data is in the prompt from
turn 0. Output uses the structured-output pattern, ensuring deterministic 
scoring and formatting.
"""

from datetime import datetime, timedelta

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.schemas import DomainReport, render_domain_report
from tradingagents.agents.utils.agent_utils import (
    get_instrument_context_from_state,
    get_language_instruction,
    get_news,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)
from tradingagents.dataflows.stocktwits import fetch_stocktwits_messages


def _seven_days_back(trade_date: str) -> str:
    return (datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")


def create_sentiment_analyst(llm):
    """Create a sentiment analyst node for the trading graph.

    Pre-fetches news + StockTwits data, injects them into the
    prompt as structured blocks, and produces a deterministic sentiment
    report via structured output.
    """
    structured_llm = bind_structured(llm, DomainReport, "Sentiment Analyst")

    def sentiment_analyst_node(state):
        ticker = state["company_of_interest"]
        end_date = state["trade_date"]
        start_date = _seven_days_back(end_date)
        instrument_context = get_instrument_context_from_state(state)

        # Pre-fetch sources (News + StockTwits / KR News RSS)
        news_block = get_news.func(ticker, start_date, end_date)

        # [국내 vs 해외 센티멘트 데이터 소스 자동 분기]
        is_kr = ticker.endswith((".KS", ".KQ")) or (len(ticker) == 6 and ticker.isdigit())

        if is_kr:
            try:
                from kr_news_rss import get_kr_stock_news
                kr_news = get_kr_stock_news(ticker, limit=10)
                if kr_news:
                    lines = [f"- [{item['press']}] {item['title']}" for item in kr_news]
                    stocktwits_block = (
                        "[참고: 국내 종목으로 StockTwits 대신 실시간 국내 주요 언론 헤드라인을 분석 소스로 제공합니다]\n"
                        + "\n".join(lines)
                    )
                else:
                    stocktwits_block = "<국내 뉴스 수집 데이터 없음>"
            except Exception as e:
                stocktwits_block = f"<국내 뉴스 RSS 수집 오류: {e}>"
        else:
            # 미국/해외 주식: 기존 StockTwits 소셜 데이터 유지
            stocktwits_block = fetch_stocktwits_messages(ticker, limit=30)

        system_message = _build_system_message(
            ticker=ticker,
            start_date=start_date,
            end_date=end_date,
            news_block=news_block,
            stocktwits_block=stocktwits_block,
        )

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a helpful AI assistant, collaborating with other assistants."
                    " If you or any other assistant has the FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** or deliverable,"
                    " prefix your response with FINAL TRANSACTION PROPOSAL: **BUY/HOLD/SELL** so the team knows to stop."
                    " Today's date is {current_date}; treat it as 'now' for all analysis and tool-call date ranges. {instrument_context}"
                    "\n{system_message}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(current_date=end_date)
        prompt = prompt.partial(instrument_context=instrument_context)

        formatted_messages = prompt.format_messages(messages=state["messages"])

        report_text = invoke_structured_or_freetext(
            structured_llm,
            llm,
            formatted_messages,
            lambda r: render_domain_report("Sentiment", r),
            "Sentiment Analyst",
        )

        return {
            "messages": [AIMessage(content=report_text)],
            "sentiment_report": report_text,
        }

    return sentiment_analyst_node


def _build_system_message(
    *,
    ticker: str,
    start_date: str,
    end_date: str,
    news_block: str,
    stocktwits_block: str,
) -> str:
    """Assemble the sentiment-analyst system message with structured data blocks."""
    return f"""You are a financial market sentiment analyst. Your task is to produce a comprehensive sentiment report for {ticker} covering the period from {start_date} to {end_date}, drawing on two complementary data sources that have already been collected for you.

## Data sources (pre-fetched, in this prompt)

### News headlines — Yahoo Finance, past 7 days
Institutional framing. Fact-driven, slower-moving signal.

<start_of_news>
{news_block}
<end_of_news>

### StockTwits messages — retail-trader social platform indexed by cashtag
Fast-moving signal. Each message carries a user-labeled sentiment tag (Bullish / Bearish / no-label) plus the message body.

<start_of_stocktwits>
{stocktwits_block}
<end_of_stocktwits>

## How to analyze this data (best practices)

1. **Read the StockTwits Bullish/Bearish ratio as a leading retail-sentiment signal.** A 70/30 bullish/bearish split is moderately bullish; ≥90/10 may indicate over-extension and contrarian risk; 50/50 is uncertainty. Sample size matters — base rates on the actual message count, not percentages alone.

2. **Look for cross-source divergences.** If news framing is bearish but StockTwits is overwhelmingly bullish, that mismatch is itself a signal.

3. **Distinguish opinion from event.** A news headline is an event; a StockTwits post is opinion. Both should be weighted differently in your conclusions.

4. **Identify recurring narrative themes.** What topic keeps coming up across sources? That's the dominant narrative driving current sentiment.

5. **Be honest about data limits.** If StockTwits returned only a handful of messages, flag this explicitly.

6. **Identify catalysts and risks** that emerge across sources.

## Output fields (DomainReport)

Fill the following fields to output a structured domain report:
- **analyst_findings**: Key objective data, metrics, and facts summarized from the sources. 3-4 sentences.
- **debate_summary**: Summary of internal arguments or differing perspectives between Bullish and Bearish viewpoints regarding this sentiment data.
- **bull_score**: A numeric integer score from 0 to 100 representing bullish intensity based on sentiment.
- **bear_score**: A numeric integer score from 0 to 100 representing bearish intensity based on sentiment.

{get_language_instruction()}"""


# ---------------------------------------------------------------------------
# Backwards-compatibility shim
# ---------------------------------------------------------------------------
def create_social_media_analyst(llm):
    """Deprecated alias for :func:`create_sentiment_analyst`."""
    import warnings
    warnings.warn(
        "create_social_media_analyst is deprecated and will be removed in a "
        "future version. Use create_sentiment_analyst instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return create_sentiment_analyst(llm)