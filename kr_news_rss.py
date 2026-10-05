import html
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

# 국내 종목 기본 매핑
TICKER_NAME_MAP = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스",
    "005380": "현대차",
    "000270": "기아",
    "035420": "NAVER",
    "035720": "카카오",
    "068270": "셀트리온",
    "105560": "KB금융",
}


def get_kr_stock_news(query_or_ticker: str, limit: int = 10) -> list[dict]:
    """구글 뉴스 RSS를 통해 국내 주요 언론사의 최신 주식 뉴스를 수집합니다.

    (약관 시비 및 차단 리스크 없음)
    """
    # 종목코드가 들어온 경우 한글 기업명으로 매핑
    pure_code = "".join(filter(str.isdigit, query_or_ticker))
    keyword = TICKER_NAME_MAP.get(pure_code, query_or_ticker)

    # 검색어 인코딩 ('삼성전자 주식')
    query = f"{keyword} 주식"
    encoded_query = urllib.parse.quote(query)

    # 구글 뉴스 한국어/한국지역 RSS 엔드포인트
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ko&gl=KR&ceid=KR:ko"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }

    try:
        req = urllib.request.Request(rss_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()

        root = ET.fromstring(xml_data)
        articles = []

        for item in root.findall(".//channel/item"):
            title = item.findtext("title", "")
            pub_date = item.findtext("pubDate", "")
            link = item.findtext("link", "")

            # HTML 엔티티 복원 및 불필요한 특수문자 정제
            clean_title = html.unescape(title)

            # 구글 뉴스 제목 끝에 붙는 언론사 이름 분리 (예: '삼성전자 반등... - 매일경제')
            press = ""
            if " - " in clean_title:
                parts = clean_title.rsplit(" - ", 1)
                clean_title = parts[0].strip()
                press = parts[1].strip()

            articles.append({
                "title": clean_title,
                "press": press,
                "date": pub_date,
                "link": link,
            })

            if len(articles) >= limit:
                break

        return articles

    except Exception as e:
        print(f"[WARN] 국내 뉴스 RSS 수집 실패 ({query_or_ticker}): {e}")
        return []


if __name__ == "__main__":
    test_code = "005930"
    print("=" * 60)
    print(f"📰 [{test_code} 삼성전자] 구글 뉴스 RSS 수집 테스트")
    print("=" * 60)

    news_list = get_kr_stock_news(test_code, limit=5)
    if not news_list:
        print("수집된 뉴스가 없습니다.")
    else:
        for idx, news in enumerate(news_list, 1):
            print(f"[{idx}] {news['title']}")
            print(f"    언론사: {news['press']} | 일시: {news['date']}")
            print("-" * 60)