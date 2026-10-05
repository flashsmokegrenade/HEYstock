import json
import os
from datetime import datetime
import FinanceDataReader as fdr

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER_FILE = os.path.join(CURRENT_DIR, "krx_master.json")


def update_krx_master():
    print("=" * 60)
    print("🔄 [KRX Master] 주식 + ETF 전 종목 통합 수집 시작...")
    print("=" * 60)

    try:
        merged_by_name = {}
        merged_by_code = {}

        # 1. 코스피/코스닥 일반 주식 (약 2,700개)
        df_stocks = fdr.StockListing("KRX")
        for _, row in df_stocks.iterrows():
            code = str(row["Code"]).zfill(6)
            name = str(row["Name"]).strip()
            market = str(row.get("Market", "KOSPI")).upper()
            suffix = ".KQ" if "KOSDAQ" in market else ".KS"

            info = {
                "code": code,
                "agent_ticker": f"{code}{suffix}",
                "corp_name": name,
                "market": "KOSDAQ" if "KOSDAQ" in market else "KOSPI",
                "suffix": suffix,
                "type": "STOCK",
            }
            merged_by_name[name] = info
            merged_by_name[name.replace(" ", "").upper()] = info
            merged_by_code[code] = info

        # 2. 국내 상장 ETF (약 900개) - 대부분 코스피(.KS) 거래소에 상장
        df_etf = fdr.StockListing("ETF/KR")  #
        for _, row in df_etf.iterrows():
            code = str(row["Symbol"]).zfill(6)
            name = str(row["Name"]).strip()

            info = {
                "code": code,
                "agent_ticker": f"{code}.KS",
                "corp_name": name,
                "market": "KOSPI",
                "suffix": ".KS",
                "type": "ETF",
            }
            merged_by_name[name] = info
            merged_by_name[name.replace(" ", "").upper()] = info
            merged_by_code[code] = info

        master_data = {
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_count": len(merged_by_code),
            "by_name": merged_by_name,
            "by_code": merged_by_code,
        }

        with open(MASTER_FILE, "w", encoding="utf-8") as f:
            json.dump(master_data, f, ensure_ascii=False, indent=2)

        print(
            f"✅ [저장 성공] 주식 + ETF 총 {master_data['total_count']:,}개 종목 마스터 캐싱 완료!"
        )
        print("=" * 60)

    except Exception as e:
        print(f"❌ [오류 발생] {e}")


if __name__ == "__main__":
    update_krx_master()