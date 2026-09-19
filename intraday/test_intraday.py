"""합성 분봉으로 ORB 엔진과 봉 집계를 검증한다. python -m intraday.test_intraday"""
from datetime import datetime, timedelta, timezone

from intraday.bars import Bar, BarBuilder
from intraday.strategy import ORBEngine, ORBParams, simulate_day
from kiwoom.stream import parse_real

KST = timezone(timedelta(hours=9))
D = datetime(2026, 9, 18, 9, 0)


def mk(minutes: int, o, h, l, c, v, code="AAA") -> Bar:
    return Bar(code, D + timedelta(minutes=minutes), o, h, l, c, v)


def or_bars(n=30, vol=100.0):
    # 09:00~09:29: 시가 100 고가 102 저가 98 종가 100 거래량 100
    return [mk(i, 100, 102, 98, 100, vol) for i in range(n)]


p = ORBParams(vol_mult=1.5, stop_pct=0.02, tp_pct=0.03)

# 1) 돌파 + 거래량 -> 다음 봉 시가 진입 -> 익절
bars = or_bars() + [
    mk(30, 100, 101, 99, 101, 100),      # 돌파 아님 (101 <= 102)
    mk(31, 101, 103, 101, 102.5, 120),   # 돌파지만 거래량 120 < 150
    mk(32, 102.5, 103, 102, 102.8, 200), # 돌파 + 거래량 -> 시그널
    mk(33, 103, 104, 102.8, 103.5, 100), # 진입가 103 -> 손절 max(98, 100.94)=100.94 익절 106.09
    mk(34, 103.5, 106.5, 103, 106, 100), # 고가 106.5 >= 106.09 -> 익절
    mk(35, 106, 107, 105, 106, 100),
]
tr = simulate_day(bars, p)
assert tr and tr["entry"] == 103 and tr["reason"] == "tp", tr
assert abs(tr["exit"] - 103 * 1.03) < 1e-9 and abs(tr["ret"] - 0.03) < 1e-9, tr

# 2) 손절 (봉 안에서 손절 먼저)
bars2 = or_bars() + [mk(30, 102, 103.5, 102, 103, 300), mk(31, 103, 103, 103, 103, 50), mk(32, 103, 103.5, 100, 100.5, 80)]
tr2 = simulate_day(bars2, p)
assert tr2["reason"] == "stop" and abs(tr2["exit"] - 103 * 0.98) < 1e-9, tr2

# 2b) 갭 하락 시가가 손절가 아래면 시가 체결
bars2b = or_bars() + [mk(30, 102, 103.5, 102, 103, 300), mk(31, 103, 103, 103, 103, 50), mk(32, 99, 99.5, 98.5, 99, 80)]
assert simulate_day(bars2b, p)["exit"] == 99

# 3) 시간 청산: 15:10 봉 종가
late = or_bars() + [mk(30, 102, 103.5, 102, 103, 300), mk(31, 103, 103, 103, 103, 50)]
late += [mk(m, 103, 103.5, 102.5, 103, 10) for m in range(32, 370)]  # ~15:09
late += [mk(370, 104, 104, 104, 104, 10)]  # 15:10
tr3 = simulate_day(late, p)
assert tr3["reason"] == "time" and tr3["exit"] == 104, tr3

# 4) 14:00 이후 돌파는 무시
no = or_bars() + [mk(m, 100, 101, 99, 100, 10) for m in range(30, 300)] + [mk(300, 102, 104, 102, 103.5, 500)]
assert simulate_day(no, p) is None

# 5) VWAP 조건: 종가가 VWAP 아래면 진입 안 함 (거래량 큰 봉이 낮은 가격에 몰린 경우)
low_vwap = [mk(i, 100, 102, 98, 100, 100) for i in range(30)]
low_vwap[10] = mk(10, 60, 60, 60, 60, 100000)  # VWAP 을 60 근처로 끌어내림
# 이 봉 때문에 OR 저가는 60. 돌파 봉 종가 102.5 > VWAP(≈60.4) 이므로 진입된다 -> use_vwap 검증은 반대로
hi = ORBParams(vol_mult=1.5, use_vwap=True)
b5 = low_vwap + [mk(30, 102, 103, 102, 102.5, 100000)]  # 거래량 100000 >= 1.5*avg(3433)
assert simulate_day(b5 + [mk(31, 102.5, 102.5, 102.5, 102.5, 1)], hi) is not None
# VWAP 이 위에 있는 케이스: 초반 고가 거래 집중
hv = [mk(i, 100, 102, 98, 100, 100) for i in range(30)]
hv[5] = mk(5, 101.9, 102, 101.9, 102, 100000)  # VWAP ≈ 102 근처. 돌파 종가 102.05 > OR high 102 이지만 VWAP(101.9x) 초과 여부
b6 = hv + [mk(30, 102, 102.1, 102, 102.05, 100000), mk(31, 102.05, 102.05, 102.05, 102.05, 1)]
eng = ORBEngine(hi)
for b in b6[:30]:
    eng.on_bar(b)
vwap = eng.state["AAA"].vwap
assert 101.9 < vwap < 102.0, vwap
assert simulate_day(b6, hi) is not None  # 102.05 > vwap
assert simulate_day(hv + [mk(30, 101.5, 102.5, 101.5, 101.95, 100000), mk(31, 1, 1, 1, 1, 1)], hi) is None  # 101.95 < OR high 102

# 6) min_or_bars 미달이면 진입 없음
assert simulate_day(or_bars(5) + [mk(30, 102, 104, 102, 103.5, 500), mk(31, 103, 103, 103, 103, 1)], p) is None

# 7) 실전 경로: on_price 로 손절
eng = ORBEngine(p)
for b in or_bars():
    eng.on_bar(b)
act = eng.on_bar(mk(30, 102, 103.5, 102, 103, 300))
assert act and act.kind == "buy"
eng.mark_entry("AAA", 103.0)
assert eng.on_price("AAA", D + timedelta(minutes=31), 102.0) is None
sell = eng.on_price("AAA", D + timedelta(minutes=32), 100.9)
assert sell and sell.reason == "stop"
assert eng.on_bar(mk(33, 105, 110, 105, 110, 999)) is None  # 하루 1회

# 8) BarBuilder: 틱 -> 1분봉
done = []
bb = BarBuilder(on_bar=done.append)
t0 = datetime(2026, 9, 18, 9, 0, 5, tzinfo=KST)
bb.add("AAA", t0, 100, 10)
bb.add("AAA", t0 + timedelta(seconds=20), 103, 5)
bb.add("AAA", t0 + timedelta(seconds=40), 99, 7)
bb.add("AAA", t0 + timedelta(seconds=70), 101, 3)  # 09:01 -> 09:00 봉 완성
assert len(done) == 1 and (done[0].open, done[0].high, done[0].low, done[0].close, done[0].volume) == (100, 103, 99, 99, 22)
assert done[0].time == datetime(2026, 9, 18, 9, 0)
bb.add("AAA", t0 + timedelta(seconds=30), 50, 1)  # 늦은 틱 무시
assert bb.current("AAA").low == 101
bb.flush()
assert len(done) == 2

# 9) 실시간 프레임 파싱 (부호 붙은 문자열)
msg = {"trnm": "REAL", "data": [{"type": "0B", "name": "주식체결", "item": "005930",
                                  "values": {"20": "093012", "10": "-71200", "15": "-35", "13": "1234567"}}]}
ticks = parse_real(msg, today=datetime(2026, 9, 18).date())
assert len(ticks) == 1 and ticks[0].price == 71200 and ticks[0].volume == 35 and ticks[0].ts.hour == 9 and ticks[0].ts.minute == 30
assert parse_real({"trnm": "REAL", "data": [{"type": "0D", "item": "005930", "values": {}}]}) == []

print("모든 테스트 통과")
