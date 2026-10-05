import time
import datetime
from database import get_connection, get_monday_dispatch_targets

# ==============================================================================
# 카카오톡 발송 클라이언트 (시뮬레이션 / 실제 API 연동부)
# ==============================================================================
def send_kakao_message(phone_number: str, message_text: str) -> bool:
    """
    실제 환경: 알리고(Aligo), 솔라피(Solapi) 등의 비즈니스 카카오 알림톡/친구톡 API 호출
    테스트 환경: 콘솔에 발송 시뮬레이션 로그 출력
    """
    try:
        # TODO: 실제 서비스 시 카카오 비즈메시지 API 호출 로직 삽입
        # response = requests.post("https://api.solapi.com/messages/v4/send", ...)
        time.sleep(0.3)  # 실제 통신 딜레이 시뮬레이션
        return True
    except Exception as e:
        print(f"      [전송 에러] {e}")
        return False


def log_delivery(user_id: int, report_id: int, status: str, error_msg: str = ""):
    """발송 결과를 DB delivery_logs 테이블에 기록"""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO delivery_logs (user_id, report_id, status, sent_at, error_msg)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?)
        """, (user_id, report_id, status, error_msg))
        conn.commit()


# ==============================================================================
# 월요일 정기 발송 메인 파이프라인
# ==============================================================================
def run_monday_dispatch(batch_date: str = None):
    """
    월요일 아침 8시 실행: 유저별 구독 종목 카드를 묶어서 자동 순차 발송
    """
    if not batch_date:
        batch_date = datetime.date.today().strftime("%Y-%m-%d")

    print("==================================================")
    print(f"📬 [HEYstock] 주간 맞춤 브리핑 발송 시작 (기준 배치일: {batch_date})")
    print("==================================================")

    # 1. 월요일 발송 대상자 및 종목 매핑 조회
    dispatch_targets = get_monday_dispatch_targets(batch_date)

    if not dispatch_targets:
        print(f"[INFO] '{batch_date}' 일자로 생성된 발송 대상 리포트가 없습니다.")
        return

    total_users = len(dispatch_targets)
    total_messages = sum(len(d["messages"]) for d in dispatch_targets)
    print(f"[INFO] 총 {total_users}명의 회원에게 {total_messages}건의 브리핑을 순차 발송합니다.\n")

    sent_count = 0
    fail_count = 0

    # 2. 유저별 발송 루프
    for u_idx, target in enumerate(dispatch_targets, 1):
        user_id = target["user_id"]
        phone = target["phone_number"]
        messages = target["messages"]
        tickers = [m["ticker"] for m in messages]

        print(f"[{u_idx}/{total_users}] 회원 #{user_id} ({phone}) 발송 시작 - 종목: {tickers}")

        # 안내 헤더 메시지
        header_text = f"📢 [HEYstock] 이번 주 신청하신 맞춤 분석 리포트 {len(messages)}건이 도착했습니다."
        send_kakao_message(phone, header_text)

        # 종목별 카드 전송
        for m_idx, msg in enumerate(messages, 1):
            report_id = msg["report_id"]
            ticker = msg["ticker"]
            card_text = msg["text"]

            success = send_kakao_message(phone, card_text)

            if success:
                log_delivery(user_id=user_id, report_id=report_id, status="SENT")
                sent_count += 1
                print(f"   └ ({m_idx}/{len(messages)}) [{ticker}] 발송 완료 ✅")
            else:
                log_delivery(user_id=user_id, report_id=report_id, status="FAILED", error_msg="Network Timeout")
                fail_count += 1
                print(f"   └ ({m_idx}/{len(messages)}) [{ticker}] 발송 실패 ❌")

            time.sleep(0.2)  # 통신사 스팸 방지용 딜레이

        print()

    print("==================================================")
    print(f"🏁 발송 작업 완료: 성공 {sent_count}건 / 실패 {fail_count}건")
    print("==================================================")


if __name__ == "__main__":
    # 오늘 생성된 배치 결과 기준으로 발송 시뮬레이션 실행
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    run_monday_dispatch(batch_date=today_str)