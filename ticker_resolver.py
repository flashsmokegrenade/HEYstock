import json
import os
import re
import urllib.parse
import urllib.request

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER_FILE = os.path.join(CURRENT_DIR, "krx_master.json")

# 1. 흔히 쓰는 대형주 약어 / 별칭 매핑
POPULAR_ALIASES = {
    "삼전": "삼성전자",
    "하이닉스": "SK하이닉스",
    "삼바": "삼성바이오로직스",
    "엔솔": "LG에너지솔루션",
    "포스코": "포스코홀딩스",
    "POSCO": "포스코홀딩스",
}

# 2. 메모리에 로드할 마스터 캐시 객체
KRX_MASTER = {"by_name": {}, "by_code": {}}


def load_master_data():
    """프로젝트 내 krx_master.json을 메모리에 로드 (없으면 자동 1회 생성)"""
    global KRX_MASTER
    if not os.path.exists(MASTER_FILE):
        try:
            from krx_updater import update_krx_master
            update_krx_master()
        except Exception:
            pass

    if os.path.exists(MASTER_FILE):
        try:
            with open(MASTER_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                KRX_MASTER["by_name"] = data.get("by_name", {})
                KRX_MASTER["by_code"] = data.get("by_code", {})
        except Exception:
            pass


# 모듈 임포트 시 즉시 메모리에 1회 로드
load_master_data()


def search_kr_stock_online(query: str) -> dict | None:
    """신규 공모주 등 마스터 파일에 없는 최신 종목을 위한 온라인 폴백 검색"""
    query = query.strip()
    try:
        try:
            q_enc = urllib.parse.quote(query.encode("cp949"))
        except Exception:
            q_enc = urllib.parse.quote(query)

        url = f"https://finance.naver.com/search/searchList.naver?query={q_enc}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://finance.naver.com/",
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=4) as res:
            final_url = res.geturl()
            html_text = res.read().decode("cp949", errors="ignore")

        code_match = re.search(r"code=(\d{6})", final_url)
        if code_match:
            code = code_match.group(1)
            name_match = re.search(r"<title>([^:]+)\s*:", html_text)
            name = name_match.group(1).strip() if name_match else query
            is_kosdaq = bool(re.search(r'class="kosdaq"|코스닥', html_text))
            suffix = ".KQ" if is_kosdaq else ".KS"
            return {
                "ticker": code,
                "agent_ticker": f"{code}{suffix}",
                "corp_name": name,
                "market": "KOSDAQ" if is_kosdaq else "KOSPI",
            }
    except Exception:
        pass
    return None


def resolve_stock_input(user_input: str) -> dict:
    """
    사용자 입력(한글 회사명, 숫자 코드, 영문 티커)을 야후 파이낸스 호환 심볼로 정규화
    1순위: 마스터 캐시 (0.0001초)
    2순위: 온라인 실시간 검색
    """
    cleaned = user_input.strip()

    # 1. 이미 .KS 또는 .KQ가 붙어 있는 경우
    if cleaned.upper().endswith((".KS", ".KQ")):
        code = cleaned[:-3]
        return {
            "ticker": code,
            "agent_ticker": cleaned.upper(),
            "corp_name": code,
            "market": "KR",
        }

    # 2. 약어 변환 (예: '삼전' -> '삼성전자')
    lookup_name = POPULAR_ALIASES.get(cleaned, cleaned)
    norm_name = lookup_name.replace(" ", "").upper()

    # 3. 마스터 캐시에서 이름으로 조회 (코스피/코스닥 전 종목)
    if norm_name in KRX_MASTER["by_name"]:
        item = KRX_MASTER["by_name"][norm_name]
        return {
            "ticker": item["code"],
            "agent_ticker": item["agent_ticker"],
            "corp_name": item["corp_name"],
            "market": item["market"],
        }

    # 4. 숫자 6자리인 경우 (예: '005930', '010350')
    if len(cleaned) == 6 and cleaned.isdigit():
        if cleaned in KRX_MASTER["by_code"]:
            item = KRX_MASTER["by_code"][cleaned]
            return {
                "ticker": item["code"],
                "agent_ticker": item["agent_ticker"],
                "corp_name": item["corp_name"],
                "market": item["market"],
            }
        return {
            "ticker": cleaned,
            "agent_ticker": f"{cleaned}.KS",
            "corp_name": cleaned,
            "market": "KR",
        }

    # 5. 미국 주식 티커 (예: 'NVDA', 'AAPL', 'TSLA')
    if re.match(r"^[A-Za-z\.\-]+$", cleaned):
        return {
            "ticker": cleaned.upper(),
            "agent_ticker": cleaned.upper(),
            "corp_name": cleaned.upper(),
            "market": "US",
        }

    # 6. 마스터에 없는 갓 상장된 신규 종목인 경우 온라인 검색 (백업)
    searched = search_kr_stock_online(lookup_name)
    if searched:
        return searched

    # 7. 검색 실패 방어
    if re.search(r"[가-힣]", cleaned):
        raise ValueError(f"'{cleaned}' 종목을 찾을 수 없습니다. 6자리 종목코드로 입력해 주세요.")

    return {
        "ticker": cleaned,
        "agent_ticker": cleaned,
        "corp_name": cleaned,
        "market": "KR",
    }


if __name__ == "__main__":
    test_cases = ["삼아알미늄", "일진전기", "삼전", "에코프로비엠", "005930", "NVDA"]
    print("=" * 60)
    print("🔍 [HEYstock] 마스터 캐시 기반 초고속 티커 변환 테스트")
    print("=" * 60)
    for q in test_cases:
        res = resolve_stock_input(q)
        print(f"입력: {q:<10} ➔ 티커: {res['ticker']:<8} | 수집심볼: {res['agent_ticker']:<11} | 이름: {res['corp_name']}")