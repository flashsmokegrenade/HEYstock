import sqlite3
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple

DB_PATH = "heystock.db"

# 요금제 티어별 최대 등록 가능 종목 수
TIER_LIMITS = {
    "FREE": 1,
    "BASIC": 3,
    "PRO": 7
}


def get_connection() -> sqlite3.Connection:
    """데이터베이스 커넥션 생성 (딕셔너리 형태 조회를 위해 row_factory 설정)"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """테이블 초기화 및 인덱스 생성"""
    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. 회원 정보 테이블
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kakao_id TEXT UNIQUE NOT NULL,
            phone_number TEXT,
            plan_tier TEXT DEFAULT 'BASIC',      -- FREE, BASIC, PRO
            billing_status TEXT DEFAULT 'ACTIVE', -- ACTIVE, PAUSED, CANCELED
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # 2. 유저별 관심 종목 테이블
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_tickers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            market TEXT NOT NULL,                -- KR or US
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(user_id, ticker)
        )
        """)

        # 3. 주말 배치 분석 리포트 테이블 (종목당 주말에 1건만 저장)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            batch_date TEXT NOT NULL,            -- YYYY-MM-DD (해당 주말 일자)
            total_score INTEGER,
            consensus TEXT,
            kakao_card_text TEXT,                -- 카톡 발송용 정제 텍스트
            full_report_path TEXT,               -- 원본 상세 텍스트 파일 경로
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ticker, batch_date)
        )
        """)

        # 4. 발송 이력 관리 테이블
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS delivery_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            report_id INTEGER NOT NULL,
            status TEXT DEFAULT 'PENDING',       -- PENDING, SENT, FAILED
            sent_at TIMESTAMP,
            error_msg TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (report_id) REFERENCES reports(id) ON DELETE CASCADE
        )
        """)

        # 빠른 조회를 위한 인덱스 생성
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_tickers_user ON user_tickers(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reports_lookup ON reports(ticker, batch_date)")

        conn.commit()
    print("[DB] heystock.db 테이블 초기화 완료")


# ==============================================================================
# 유저 & 종목 관리 함수
# ==============================================================================

def register_user(kakao_id: str, phone_number: str = "", plan_tier: str = "BASIC") -> int:
    """카카오 로그인 기반 유저 등록 또는 기존 유저 ID 반환"""
    plan_tier = plan_tier.upper()
    if plan_tier not in TIER_LIMITS:
        plan_tier = "BASIC"

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO users (kakao_id, phone_number, plan_tier)
        VALUES (?, ?, ?)
        ON CONFLICT(kakao_id) DO UPDATE SET
            phone_number = excluded.phone_number,
            plan_tier = excluded.plan_tier
        """, (kakao_id, phone_number, plan_tier))
        conn.commit()

        cursor.execute("SELECT id FROM users WHERE kakao_id = ?", (kakao_id,))
        return cursor.fetchone()["id"]


def set_user_tickers(user_id: int, tickers: List[str]) -> Tuple[bool, str]:
    """
    유저의 관심 종목 목록을 교체 갱신 (요금제 티어 한도 검증 포함)
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT plan_tier, billing_status FROM users WHERE id = ?", (user_id,))
        user = cursor.fetchone()
        if not user:
            return False, "존재하지 않는 회원입니다."

        limit = TIER_LIMITS.get(user["plan_tier"], 1)
        cleaned_tickers = list(dict.fromkeys([t.strip().upper() for t in tickers if t.strip()]))

        if len(cleaned_tickers) > limit:
            return False, f"현재 요금제({user['plan_tier']})에서는 최대 {limit}개 종목만 등록할 수 있습니다."

        # 기존 등록 종목 삭제 후 신규 등록
        cursor.execute("DELETE FROM user_tickers WHERE user_id = ?", (user_id,))
        for ticker in cleaned_tickers:
            market = "KR" if re.match(r"^\d{6}$", ticker) or ticker.endswith((".KS", ".KQ")) else "US"
            cursor.execute("""
            INSERT INTO user_tickers (user_id, ticker, market)
            VALUES (?, ?, ?)
            """, (user_id, ticker, market))

        conn.commit()
        return True, f"종목 {len(cleaned_tickers)}건 등록 완료"


# ==============================================================================
# 주말 배치 & 월요일 발송 파이프라인 전용 함수
# ==============================================================================

def get_unique_tickers_for_batch() -> List[Dict]:
    """
    [토요일 배치 실행용]
    전체 유료 유저들의 등록 종목 중 중복을 완벽히 제거한 고유 티커 목록 추출
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT DISTINCT ut.ticker, ut.market
        FROM user_tickers ut
        JOIN users u ON ut.user_id = u.id
        WHERE u.billing_status = 'ACTIVE'
        ORDER BY ut.market DESC, ut.ticker ASC
        """)
        return [dict(row) for row in cursor.fetchall()]


def save_batch_report(ticker: str, batch_date: str, total_score: int, 
                      consensus: str, kakao_card_text: str, full_report_path: str) -> int:
    """
    [토요일 배치 완료용]
    에이전트 분석 결과 및 카톡용 카드를 DB에 영구 적재
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO reports (ticker, batch_date, total_score, consensus, kakao_card_text, full_report_path)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker, batch_date) DO UPDATE SET
            total_score = excluded.total_score,
            consensus = excluded.consensus,
            kakao_card_text = excluded.kakao_card_text,
            full_report_path = excluded.full_report_path
        """, (ticker.upper(), batch_date, total_score, consensus, kakao_card_text, full_report_path))
        conn.commit()

        cursor.execute("SELECT id FROM reports WHERE ticker = ? AND batch_date = ?", (ticker.upper(), batch_date))
        return cursor.fetchone()["id"]


def get_monday_dispatch_targets(batch_date: str) -> List[Dict]:
    """
    [월요일 아침 8시 발송용]
    활성 유저별로 그 주말에 생성된 분석 리포트들을 묶어서 조회
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT 
            u.id as user_id,
            u.kakao_id,
            u.phone_number,
            r.id as report_id,
            r.ticker,
            r.kakao_card_text
        FROM users u
        JOIN user_tickers ut ON u.id = ut.user_id
        JOIN reports r ON ut.ticker = r.ticker AND r.batch_date = ?
        WHERE u.billing_status = 'ACTIVE'
        ORDER BY u.id ASC
        """, (batch_date,))
        
        rows = cursor.fetchall()

        # 유저 단위로 전송할 리포트들을 그룹화
        user_dispatches = {}
        for row in rows:
            uid = row["user_id"]
            if uid not in user_dispatches:
                user_dispatches[uid] = {
                    "user_id": uid,
                    "kakao_id": row["kakao_id"],
                    "phone_number": row["phone_number"],
                    "messages": []
                }
            user_dispatches[uid]["messages"].append({
                "report_id": row["report_id"],
                "ticker": row["ticker"],
                "text": row["kakao_card_text"]
            })

        return list(user_dispatches.values())


# ==============================================================================
# 단독 테스트 시뮬레이션
# ==============================================================================
if __name__ == "__main__":
    print("=== [HEYstock] Database Pipeline Test ===")
    init_db()

    # 1. 테스트 유저 생성 (홍길동: Basic, 김철수: Basic)
    user1_id = register_user(kakao_id="kakao_user_101", phone_number="010-1111-2222", plan_tier="BASIC")
    user2_id = register_user(kakao_id="kakao_user_102", phone_number="010-3333-4444", plan_tier="BASIC")

    # 2. 관심 종목 등록 (NVDA가 두 명 모두에게 겹치도록 설정)
    set_user_tickers(user1_id, ["NVDA", "005930", "AAPL"])
    set_user_tickers(user2_id, ["NVDA", "TSLA"])

    # 3. 토요일 배치: 중복 제거된 분석 대상 종목 추출
    batch_targets = get_unique_tickers_for_batch()
    print(f"\n[토요일 배치] 분석해야 할 고유 종목 (총 {len(batch_targets)}개):")
    for t in batch_targets:
        print(f" - {t['ticker']} ({t['market']})")

    # 4. 주말 배치 완료 가상 데이터 저장
    today_str = datetime.today().strftime("%Y-%m-%d")
    save_batch_report("NVDA", today_str, 65, "BULLISH_LEANING", "[NVDA 요약 카드]", "results/NVDA.txt")
    save_batch_report("005930", today_str, 58, "NEUTRAL", "[삼성전자 요약 카드]", "results/005930.txt")
    save_batch_report("AAPL", today_str, 70, "BULLISH", "[애플 요약 카드]", "results/AAPL.txt")
    save_batch_report("TSLA", today_str, 48, "BEARISH", "[테슬라 요약 카드]", "results/TSLA.txt")

    # 5. 월요일 발송 대상 매핑 검증
    dispatches = get_monday_dispatch_targets(today_str)
    print(f"\n[월요일 발송] 유저별 발송 대기열 (총 {len(dispatches)}명):")
    for d in dispatches:
        tickers = [m["ticker"] for m in d["messages"]]
        print(f" - 유저 #{d['user_id']} ({d['phone_number']}) -> 발송 종목: {tickers}")