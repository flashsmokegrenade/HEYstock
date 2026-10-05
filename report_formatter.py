import os
import re
from datetime import datetime

# ==============================================================================
# 1. 통화 및 지수 표기 변환기
# ==============================================================================
def format_krw_amount(val: float) -> str:
    """지수 표기를 조/억/만 단위의 자연스러운 한국어 통화로 변환"""
    is_negative = val < 0
    abs_val = abs(val)

    if abs_val >= 1e12:
        trillion = int(abs_val // 1e12)
        remainder = abs_val % 1e12
        hundred_million = int(round(remainder / 1e8))
        res = f"{trillion:,}조 {hundred_million:,}억 원" if hundred_million > 0 else f"{trillion:,}조 원"
    elif abs_val >= 1e8:
        hundred_million = int(round(abs_val / 1e8))
        res = f"{hundred_million:,}억 원"
    elif abs_val >= 1e4:
        ten_thousand = int(round(abs_val / 1e4))
        res = f"{ten_thousand:,}만 원"
    else:
        res = f"{int(round(abs_val)):,}원"

    return f"-{res}" if is_negative else res


def convert_scientific_numbers_kr(text: str) -> str:
    """텍스트 내 모든 지수 표기를 한국식 통화 단위로 정규화 치환"""
    def _replacer(m):
        raw_val = m.group(1)
        try:
            return format_krw_amount(float(raw_val))
        except ValueError:
            return m.group(0)

    pattern = r"([+-]?[0-9]+(?:\.[0-9]+)?[eE][+-]?[0-9]+)\s*(?:원)?"
    return re.sub(pattern, _replacer, text)


def format_currency_price(price: float, currency: str) -> str:
    """통화별 자릿수 맞춤 표기"""
    if str(currency).upper() in ["KRW", "원"]:
        return f"{int(round(price)):,}원"
    return f"${price:,.2f}"


# ==============================================================================
# 2. 문장 및 시나리오 파서
# ==============================================================================
def clean_article_sentences(raw_text: str) -> list[str]:
    """긴 줄글을 문장 단위 불릿으로 분리"""
    raw_text = re.sub(r"[*_`]", "", raw_text).strip()
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw_text) if len(s.strip()) > 3]
    return sentences if sentences else [raw_text]


def build_scenario_article_block(raw_scenario_text: str) -> str:
    """3대 전략 시나리오를 계층화된 속보 형태로 파싱"""
    if not raw_scenario_text:
        return "* 등록된 전략 시나리오 관측 데이터가 없습니다."

    sections = re.split(r"(?=\d+\.\s+\*\*[A-Za-z\s]+(?:Scenario|시나리오))", raw_scenario_text)
    blocks = []

    scenario_meta = {
        "1": ("🐂 [시나리오 1] 상방 확장 (Bullish Extension)", "돌파 안착 시 랠리 확장 궤도 진입"),
        "2": ("⚖️ [시나리오 2] 박스권 횡보 (Neutral Consolidation)", "지지선 방어 속 기간 조정 및 모멘텀 냉각 장세"),
        "3": ("🐻 [시나리오 3] 하방 리스크 (Downside Invalidation)", "주요 이평선 이탈 시 스윙 추세 훼손 및 위험 관리 발동"),
    }

    keywords = ["트리거", "조건", "확인", "촉매", "요인", "경계", "기준", "가정", "범위", "포인트", "진행", "연장"]

    for idx, sec in enumerate(sections, 1):
        sec = sec.strip()
        if not sec:
            continue

        str_idx = str(idx)
        header_title, default_lead = scenario_meta.get(
            str_idx,
            (f"⚡ [시나리오 {idx}] 마켓 전략 관측", "핵심 분기 레벨 추적")
        )

        title_m = re.match(r"\d+\.\s+\*\*(.*?)\*\*:(.*)", sec, re.DOTALL)
        body = title_m.group(2).strip() if title_m else sec

        for kw in keywords:
            body = re.sub(rf"[\(\[]([^\(\)\[\]]*?{kw}[^\(\)\[\]]*?)[\)\]]", r"\n* **[\1]**:", body)

        for num in ["①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"]:
            body = body.replace(num, f"\n  - {num}")

        lines = []
        for line in body.splitlines():
            l_str = line.strip()
            if not l_str:
                continue
            if l_str.startswith("* **[") or l_str.startswith("  -") or l_str.startswith("- "):
                if l_str.startswith("- ") and not l_str.startswith("  -"):
                    lines.append(f"  {l_str}")
                else:
                    lines.append(l_str)
            else:
                lines.append(f"* {l_str}")

        content_body = "\n".join(lines) if lines else f"* {body}"
        blocks.append(f"#### {header_title}\n> \"{default_lead}\"\n{content_body}")

    return "\n\n".join(blocks) if blocks else f"```\n{raw_scenario_text.strip()}\n```"


def format_domain_news_desk(
    domain_name: str,
    raw_block: str,
    bull_score: str,
    bear_score: str,
    quick_tags: str,
) -> str:
    """도메인별 관측 팩트와 찬반 토론을 누락 없이 기사체 블록으로 가공"""
    findings_m = re.search(r"\*\*Analyst Findings\*\*:(.*?)(?=\*\*Debate Summary|\Z)", raw_block, re.DOTALL)
    debate_m = re.search(r"\*\*Debate Summary\*\*:(.*?)(?=\*\*Domain Score|\Z)", raw_block, re.DOTALL)

    findings_text = findings_m.group(1).strip() if findings_m else ""
    debate_text = debate_m.group(1).strip() if debate_m else ""

    if not findings_text and not debate_text:
        findings_text = raw_block.strip() if raw_block.strip() else "세부 분석 데이터 취합 완료."

    tag_list = [t.strip().lstrip("#") for t in quick_tags.split("#") if t.strip() and t.strip() != "-"]
    sub_headline = f"\"{' / '.join(tag_list[:2])} 속 공방전 전개\"" if tag_list else f"\"{domain_name} 정량 데이터 및 핵심 지표 관측\""

    findings_sentences = clean_article_sentences(findings_text)
    findings_bullets = "\n".join([f"  - {s}" for s in findings_sentences])

    debate_lines = []
    if debate_text:
        bull_part = re.search(r"(?:강세\s*측|긍정\s*측|낙관\s*측|\[강세\])[:：\s]*(.*?)(?=(?:약세\s*측|부정\s*측|보수\s*측|반면|\[약세\])|\Z)", debate_text, re.DOTALL)
        bear_part = re.search(r"(?:약세\s*측|부정\s*측|보수\s*측|반면|\[약세\])[:：\s]*(.*?)(?=(?:결론적으로|따라서|결국|합의)|\Z)", debate_text, re.DOTALL)
        conc_part = re.search(r"(?:결론적으로|따라서|결국|합의점)[:：\s]*(.*?)$", debate_text, re.DOTALL)

        b_txt = bull_part.group(1).strip() if (bull_part and bull_part.group(1)) else ""
        br_txt = bear_part.group(1).strip() if (bear_part and bear_part.group(1)) else ""
        c_txt = conc_part.group(1).strip() if (conc_part and conc_part.group(1)) else ""

        if b_txt:
            debate_lines.append(f"  - **불(Bull)**: {b_txt}")
        if br_txt:
            debate_lines.append(f"  - **베어(Bear)**: {br_txt}")
        if c_txt:
            debate_lines.append(f"  - **합의점(Consensus)**: {c_txt}")

        if not debate_lines:
            for s in clean_article_sentences(debate_text):
                debate_lines.append(f"  - {s}")
    else:
        debate_lines.append("  - 상호 대립하는 리스크 공방 논거 취합 완료.")

    debate_formatted = "\n".join(debate_lines)

    b_val = int(bull_score) if bull_score.isdigit() else 50
    verdict = "🟢 상승 우세" if b_val >= 60 else ("🔴 경계 우세" if b_val <= 40 else "⚖️ 팽팽한 중립")

    return (
        f"#### {domain_name} {sub_headline}\n"
        f"* **태그(Quick Pulse)**: `{quick_tags}`\n"
        f"* **현장 데이터 (Analyst Findings)**:\n{findings_bullets}\n"
        f"* **격돌하는 시각 (Adversarial Debate)**:\n{debate_formatted}\n"
        f"* **데스크 판정**: Bull **{bull_score}점** vs Bear **{bear_score}점** [{verdict}]"
    )


# ==============================================================================
# 3. 상세 분석 리포트 빌더 (엔진 판정 100% 미러링)
# ==============================================================================
def build_readable_report(
    raw_log: str, ticker: str, target_date: str, consensus: str
) -> str:
    """원시 로그를 '상단 계기판 + 증권 기사체 심층 브리핑'으로 가공"""
    cleaned_log = convert_scientific_numbers_kr(raw_log)

    corp_name_match = re.search(r"\[종목:\s*([^\(\]]+?)\s*\(", cleaned_log)
    corp_name = corp_name_match.group(1).strip() if corp_name_match else ticker
    display_title = f"{corp_name} ({ticker})" if corp_name != ticker else ticker

    # 1. 도메인 점수 추출
    def get_score(domain_keywords: list[str]) -> tuple[str, str]:
        for kw in domain_keywords:
            pattern = rf"{kw}.*?Bull\s*Score\s*[:：]?\s*(?:📈\s*)?(\d+)\s*/\s*Bear\s*Score\s*[:：]?\s*(?:📉\s*)?(\d+)"
            m = re.search(pattern, cleaned_log, re.IGNORECASE | re.DOTALL)
            if m and m.group(1) and m.group(2):
                return (m.group(1), m.group(2))
        return ("50", "50")

    t_bull, t_bear = get_score(["Technical", "차트"])
    f_bull, f_bear = get_score(["Fundamental", "실적", "재무"])
    s_bull, s_bear = get_score(["Sentiment", "심리", "소셜"])
    m_bull, m_bear = get_score(["Macro", "News", "거시", "뉴스"])

    try:
        overall_score = round((int(t_bull) + int(f_bull) + int(s_bull) + int(m_bull)) / 4)
    except Exception:
        overall_score = 50

    # [핵심 수정] 점수로 재판정하지 않고 엔진의 consensus를 100% 그대로 반영
    raw_cons = str(consensus).strip().upper()
    if any(k in raw_cons for k in ["BEAR", "SELL", "UNDERWEIGHT"]):
        consensus_badge = f"🐻 {raw_cons} (하방 리스크 경계 | 종합 {overall_score}점)"
        stance_desc = "단기 과열 및 재무/거시 리스크에 따른 방어 우선 국면"
    elif any(k in raw_cons for k in ["BULL", "BUY", "OVERWEIGHT"]):
        consensus_badge = f"🐂 {raw_cons} (상승 모멘텀 우위 | 종합 {overall_score}점)"
        stance_desc = "상방 확장 시나리오 우선 관측 국면"
    else:
        consensus_badge = f"⚖️ {raw_cons} (신호 균형 및 관망 | 종합 {overall_score}점)"
        stance_desc = "주요 지지/저항 밴드 내 조건부 대응 국면"

    def get_tag(domain_title: str) -> str:
        m = re.search(
            rf"\[{domain_title}\].*?Quick\s*Pulse\*\*:\s*([^\n]+)",
            cleaned_log,
            re.IGNORECASE | re.DOTALL,
        )
        return m.group(1).strip() if m else "-"

    t_tag = get_tag("Technical Analysis Report")
    f_tag = get_tag("Fundamentals Report")
    s_tag = get_tag("Social Sentiment Report")
    m_tag = get_tag("Macro & News Report")

    thesis_m = re.search(r"\*\*Investment Thesis\*\*.*?:(.*?)(?===|\Z)", cleaned_log, re.DOTALL)
    if not thesis_m:
        thesis_m = re.search(r"\*\*Risk & Market Synthesis\*\*:(.*?)(?=\*\*Strategic Scenario|\Z)", cleaned_log, re.DOTALL)

    thesis_raw = thesis_m.group(1).strip() if thesis_m else "단기 가격 지지선 방어 여부와 거시 할인율 압박을 동시에 점검해야 합니다."
    thesis_bullets = "\n".join([f"  • {s}" for s in clean_article_sentences(thesis_raw)])
    main_headline = f"{corp_name}, 핵심 이평선 공방전… 거시 할인율 속 '단기 분기점' 시험대"

    scenario_m = re.search(
        r"\*\*Strategic Scenario Map.*?\*\*:(.*?)(?=\*\*Investment Thesis|\Z)",
        cleaned_log,
        re.DOTALL,
    )
    scenario_block = build_scenario_article_block(scenario_m.group(1).strip()) if scenario_m else "* 전략 시나리오 데이터가 비어 있습니다."

    def get_domain_block(domain_name_key: str) -> str:
        pattern = rf"\[{domain_name_key}\]\s*\n*=*\n*(.*?)(?=(?:={5,}\s*\[|\Z))"
        m = re.search(pattern, cleaned_log, re.IGNORECASE | re.DOTALL)
        if m and len(m.group(1).strip()) > 15:
            return m.group(1).strip()
        return ""

    t_article = format_domain_news_desk("📈 [차트·수급 데스크]", get_domain_block("Technical Analysis Report"), t_bull, t_bear, t_tag)
    f_article = format_domain_news_desk("🏢 [기업·실적 데스크]", get_domain_block("Fundamentals Report"), f_bull, f_bear, f_tag)
    s_article = format_domain_news_desk("💬 [여론·심리 데스크]", get_domain_block("Social Sentiment Report"), s_bull, s_bear, s_tag)
    m_article = format_domain_news_desk("🌍 [거시·외풍 데스크]", get_domain_block("Macro & News Report"), m_bull, m_bear, m_tag)

    t_verdict = '🟢 상승 우세' if int(t_bull) >= 60 else ('🔴 경계' if int(t_bull) <= 40 else '⚖️ 중립')
    f_verdict = '🟢 가치 우세' if int(f_bull) >= 60 else ('🔴 경계' if int(f_bull) <= 40 else '⚖️ 중립')
    s_verdict = '🟢 낙관 우세' if int(s_bull) >= 60 else ('🔴 경계' if int(s_bull) <= 40 else '⚖️ 중립')
    m_verdict = '🟢 완화 우세' if int(m_bull) >= 60 else ('🔴 할인율 부담' if int(m_bull) <= 40 else '⚖️ 중립')

    report = f"""# 🏛 [HEYstock 모닝 인텔리전스] {display_title} 주간 전략 리포트
# {main_headline}
> 분석 기준일: {target_date} | AI 종합 컨센서스: **{consensus}**

================================================================================
🎯 【AI 종합 컨센서스 & 스탠스 계기판】
• 📊 AI 멀티에이전트 종합 점수 : [ {overall_score}점 / 100점 ] ({stance_desc})
• 🚦 최종 시장 판정 (Consensus) : {consensus_badge}
• 💡 데스크 최종 종합 의견 (Executive Thesis) :
{thesis_bullets}
================================================================================

### 📊 4대 에이전트 종합 관측 스코어보드
| 분석 도메인 | Bull 스코어 | Bear 스코어 | 도메인 판정 | 핵심 관측 키워드 (Quick Pulse) |
| :--- | :---: | :---: | :---: | :--- |
| **📈 차트/수급 (Technical)** | **{t_bull}점** | {t_bear}점 | {t_verdict} | {t_tag} |
| **🏢 기업실적 (Fundamental)** | **{f_bull}점** | {f_bear}점 | {f_verdict} | {f_tag} |
| **💬 투자심리 (Sentiment)** | **{s_bull}점** | {s_bear}점 | {s_verdict} | {s_tag} |
| **🌍 거시경제 (Macro)** | **{m_bull}점** | {m_bear}점 | {m_verdict} | {m_tag} |

---

### 📰 4대 데스크 집중 취재 (Desk Findings & Adversarial Debate)

{t_article}

---

{f_article}

---

{s_article}

---

{m_article}

---

### 🗺️ 주간 관전 포인트: 3대 전략 시나리오 속보 (Scenario Watch)

{scenario_block}

---

### ⚖️ Regulatory Notice & Legal Disclaimer
본 리포트는 인공지능 멀티 에이전트 시스템이 공시 데이터, 보조지표, 거시경제 통계를 바탕으로 자동 합성한 정량적 관측 요약본입니다. 금융투자상품의 매수·매도를 추천하거나 투자 자문을 제공하지 않으며, 투자 판단과 책임은 투자자 본인에게 있습니다.
"""
    return report


# ==============================================================================
# 4. 카카오톡 전송용 모바일 브리핑 카드 (엔진 판정 100% 미러링)
# ==============================================================================
def generate_kakao_report_card(analysis_data: dict) -> str:
    """스마트폰 화면 한눈에 들어오는 카카오톡 전용 속보 브리핑 카드"""
    ticker = analysis_data.get("ticker", "UNKNOWN")
    corp_name = analysis_data.get("corp_name", ticker)
    price = float(analysis_data.get("current_price", 0.0))
    currency = analysis_data.get("currency", "USD")

    # [핵심 수정] 점수로 재판정하지 않고 원본 consensus 반영
    raw_consensus = str(analysis_data.get("consensus", "BALANCED")).strip().upper()
    if any(k in raw_consensus for k in ["BEAR", "SELL", "UNDERWEIGHT"]):
        stance_str = f"🐻 {raw_consensus} (하방 경계)"
    elif any(k in raw_consensus for k in ["BULL", "BUY", "OVERWEIGHT"]):
        stance_str = f"🐂 {raw_consensus} (상승 우세)"
    else:
        stance_str = f"⚖️ {raw_consensus} (신호 균형)"

    f_score = analysis_data.get("fundamental_score", 50)
    t_score = analysis_data.get("technical_score", 50)
    s_score = analysis_data.get("sentiment_score", 50)
    m_score = analysis_data.get("macro_score", 50)
    overall_score = round((f_score + t_score + s_score + m_score) / 4)

    price_str = format_currency_price(price, currency)
    res_price = format_currency_price(float(analysis_data.get("resistance_price", price)), currency)
    sup_price = format_currency_price(float(analysis_data.get("support_price", price)), currency)

    t_tag = analysis_data.get("technical_tags", "#단기추세 #변동성")
    f_tag = analysis_data.get("fundamental_tags", "#기초체력 #밸류에이션")
    s_tag = analysis_data.get("sentiment_tags", "#소셜반응 #뉴스심리")
    m_tag = analysis_data.get("macro_tags", "#금리영향 #거시환경")

    summary = analysis_data.get("desk_summary", "핵심 이동평균선 지지 여부와 거시 할인율 압박을 동시에 점검해야 할 국면입니다.")
    report_id = analysis_data.get("report_id", "latest")

    return f"""[HEYstock 모닝 마켓 브리핑]
📌 {corp_name} ({ticker})
• 현재가: {price_str}
• 종합 판정: {stance_str} [평균 {overall_score}점]

───────────────────────
📊 4대 데스크 관측 스코어
📈 차트/수급 [{t_score}점]: {t_tag}
🏢 기업실적 [{f_score}점]: {f_tag}
💬 투자심리 [{s_score}점]: {s_tag}
🌍 거시경제 [{m_score}점]: {m_tag}

───────────────────────
🎯 핵심 관찰 기준선
• 📈 상방 돌파선: {res_price} (추세 확장 트리거)
• 📉 하방 지지선: {sup_price} (리스크 방어선)

───────────────────────
💡 데스크 종합 의견 (보고서 결론 직결)
"{summary}"

👉 [웹에서 4대 에이전트 상세 토론 기사 전문 보기]
https://heystock.app/report/{report_id}"""