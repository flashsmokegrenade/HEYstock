import sqlite3

conn = sqlite3.connect("heystock.db")
cursor = conn.cursor()

print("=" * 60)
print("📊 [reports] 테이블에 적재된 분석 리포트 목록")
print("=" * 60)

cursor.execute("SELECT id, ticker, batch_date, total_score, consensus, full_report_path FROM reports")
rows = cursor.fetchall()

if not rows:
    print("저장된 리포트가 없습니다.")
else:
    for row in rows:
        print(f"ID: {row[0]} | 종목: {row[1]:<8} | 날짜: {row[2]} | 점수: {row[3]}점 | 판정: {row[4]}")
        print(f" └ 파일 경로: {row[5]}")

print("\n" + "=" * 60)
print("📱 최근 저장된 1개 종목의 카카오톡 카드 미리보기")
print("=" * 60)
cursor.execute("SELECT ticker, kakao_card_text FROM reports ORDER BY id DESC LIMIT 1")
latest = cursor.fetchone()
if latest:
    print(f"[{latest[0]}] 카카오톡 발송 문구:\n")
    print(latest[1])

conn.close()