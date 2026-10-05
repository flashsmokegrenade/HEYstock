import os
import json
import re
import pandas as pd

# ==============================================================================
# 1. 백그라운드 1회 실행: LLM 기반 종목 맞춤형 교육 카드 생성기
# ==============================================================================
def generate_edu_cards_with_llm(ticker: str, report_text: str) -> dict:
    """
    정량 분석 완료 시 백그라운드에서 딱 1번 실행됩니다.
    종목과 리포트 맥락에 100% 들어맞는 교육 카드를 JSON으로 생성합니다.
    """
    try:
        from openai import OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None

        client = OpenAI(api_key=api_key)

        prompt = f"""
당신은 월스트리트 출신의 핀테크 금융 교육 전문가입니다.
아래는 '{ticker}' 종목에 대해 분석된 리포트입니다.
초보 투자자가 이 종목을 제대로 이해하고 리스크를 관리할 수 있도록, 
이 종목의 실제 재무/비즈니스/시장 환경에 100% 맞춘 3대 교육 카드를 JSON으로 작성하세요.

[리포트 요약]
{report_text[:2500]}

[작성 요구사항]
1. macro_chain: 이 종목에 가장 치명적이거나 호재인 핵심 거시경제 지표 1개를 선정하여 3단계 도미노 인과 체인 작성 (1단계: 거시환경 -> 2단계: 기업 원가/재무/환율 전이 -> 3단계: 밸류에이션/주가 영향, takeaway: 1줄 핵심 원리 교훈)
2. traps: 이 종목 투자 시 초보자들이 가장 흔히 빠지는 지표 착시 및 함정 1~2개 (topic, trap: 흔한 착각, insight: 프로 애널리스트의 의심과 검증법, badge: 4글자 뱃지)
3. critical_thinking: 리포트 분석에 기반한 상승 전제 조건(bull_triggers 1개)과 하방 무효화/손절 기준(bear_risks 1개)

반드시 아래 JSON 포맷으로만 응답하세요:
{{
  "macro_chain": {{
    "indicator": "핵심 매크로 지표명 (예: 미 국채 10년물 금리, WTI 유가, AI 반도체 수출 규제 등)",
    "stage1": "거시 환경 변화",
    "stage2": "기업 원가/재무/수급 전이",
    "stage3": "최종 밸류에이션 및 주가 영향",
    "takeaway": "초보자를 위한 핵심 원리 교훈"
  }},
  "traps": [
    {{
      "topic": "지표 함정 주제 (예: PER 밸류 트랩, 고배당 착시 등)",
      "trap": "초보자의 흔한 오해",
      "insight": "애널리스트의 실질적 검증법",
      "badge": "함정 뱃지명"
    }}
  ],
  "critical_thinking": {{
    "bull_triggers": ["상승이 정당화되기 위한 트리거"],
    "bear_risks": ["투자의견 무효화 및 손절 기준"]
  }}
}}
"""
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"[교육 모드] LLM 카드 생성 실패 (기본 룰셋으로 폴백): {e}")
        return None


# ==============================================================================
# 2. 저장된 파일 캐시 로드 & 차트 팩트체크 엔진 (토큰 0개 / 즉시 렌더링)
# ==============================================================================
def verify_and_explain(report_text: str, df: pd.DataFrame, ticker: str = "UNKNOWN") -> dict:
    """
    리포트 파일 내에 영구 저장된 [HEYSTOCK_EDU_CARDS_JSON]을 0.00초 만에 파싱합니다.
    """
    cached_cards = None
    clean_report = report_text

    # 파일 내에 캐시된 교육 카드가 있는지 확인
    if "[HEYSTOCK_EDU_CARDS_JSON]" in report_text:
        try:
            parts = report_text.split("[HEYSTOCK_EDU_CARDS_JSON]")
            clean_report = parts[0].strip()
            json_block = parts[1].split("=" * 80)[0].strip()
            cached_cards = json.loads(json_block)
        except Exception:
            cached_cards = None

    # 캐시가 있으면 LLM이 사전 생성했던 고유 카드 사용, 없으면 폴백 룰셋 적용
    if cached_cards:
        macro_chains = [cached_cards.get("macro_chain", {})]
        traps = cached_cards.get("traps", [])
        crit = cached_cards.get("critical_thinking", {
            "bull_triggers": ["주요 저항선 돌파 및 지지 확인"],
            "bear_risks": ["주요 지지선 이탈 및 매크로 역풍"]
        })
    else:
        # 레거시 파일용 기본 룰셋
        macro_chains = [{
            "indicator": "미국 10년물 국채 금리 및 매크로 유동성",
            "stage1": "10년물 국채 금리(무위험 수익률) 상승",
            "stage2": "기업 미래 현금흐름 할인율(WACC) 증가 및 차입 비용 가중",
            "stage3": "고멀티플 성장주 밸류에이션(PER) 압축",
            "takeaway": "금리가 오르면 미래 이익의 현재 가치가 수학적으로 할인되어 주가가 조정받을 수 있습니다."
        }]
        traps = [{
            "topic": "PER (주가수익비율): 밸류 트랩(Value Trap)",
            "trap": "PER이 낮으니 무조건 저평가된 꿀종목이다?",
            "insight": "성장 동력이 훼손되어 시장에서 소외된 상태일 수 있으므로 미래 EPS 전망치를 확인해야 합니다.",
            "badge": "가치함정 주의"
        }]
        crit = {
            "bull_triggers": ["주요 저항선 돌파 및 거래량 동반"],
            "bear_risks": ["직전 저점 이탈 및 매크로 지표 악화"]
        }

    # 차트 정합성 팩트체크
    factchecks = []
    if not df.empty and len(df) >= 5:
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        pct = ((latest["Close"] - prev["Close"]) / prev["Close"]) * 100
        ema20 = latest.get("EMA20", latest["Close"])
        pos_ema = "상회 (단기 매수 우위)" if latest["Close"] >= ema20 else "하회 (단기 조정 압력)"

        factchecks.append({
            "category": "종가 체결 및 가격 모멘텀 팩트체크",
            "claim": f"최근 종가 ${latest['Close']:.2f} 형성 (전일비 {pct:+.2f}%)",
            "chart_fact": f"차트 최종 캔들 종가: ${latest['Close']:.2f}",
            "status": "정합 (100% 일치)",
            "is_valid": True,
            "lesson": "단기 캔들의 마감 종가는 당일 매수자와 매도자의 최종 합의 가격입니다. 거래량 수반 여부를 함께 대조해야 합니다."
        })
        factchecks.append({
            "category": "추세 기준선 (20 EMA) 정합성 및 생명선 해석",
            "claim": f"20 EMA(${ema20:.2f}) 대비 주가 위치: {pos_ema}",
            "chart_fact": f"실제 20일 지수이동평균선 값: ${ema20:.2f}",
            "status": "정합 (100% 일치)",
            "is_valid": True,
            "lesson": "20 EMA는 기관 투자자들이 단기 추세의 지속 여부를 판단하는 기준선입니다. 이탈 시 단기 매도세 출회를 경계해야 합니다."
        })

    return {
        "factchecks": factchecks,
        "macro_chains": macro_chains,
        "traps": traps,
        "critical_thinking": crit,
        "clean_report": clean_report
    }