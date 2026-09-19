"""합성 데이터로 시그널 / 진입 / 청산 로직을 검증한다. python test_backtest.py"""
import numpy as np
import pandas as pd

from backtest import Params, build_signals, run_scenarios, trades_from_signals

dates = pd.bdate_range("2024-01-01", periods=12)
# 종가 100 101 ... 111 / 시가 = 종가 - 0.5
C = pd.DataFrame({"AAA": np.arange(100, 112, dtype=float)}, index=dates)
O = C - 0.5
# 기관: 인덱스 0..2 양수 (3일 연속 -> 2일차 시그널) / 3 음수 / 4..7 양수 (6일차 7일차 시그널)
I = pd.DataFrame({"AAA": [1, 1, 1, -1, 1, 1, 1, 1, 0, 0, 0, 0]}, index=dates, dtype=float)
# 외국인: 4..7 만 양수 -> 시나리오 B 는 6일차 7일차만
F = pd.DataFrame({"AAA": [1, -1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0]}, index=dates, dtype=float)

p = Params(streak=3, hold=5, entry="open")
sigA = build_signals(I, None, p)
assert list(np.where(sigA["AAA"])[0]) == [2, 6, 7], sigA["AAA"].tolist()
sigB = build_signals(I, F, p)
assert list(np.where(sigB["AAA"])[0]) == [6, 7], sigB["AAA"].tolist()

trA = trades_from_signals(sigA, O, C, p)
# 시그널 idx2 -> 진입 idx3 시가 102.5 -> 청산 idx8 종가 108
row = trA.iloc[0]
assert row.entry_date == dates[3] and row.exit_date == dates[8]
assert abs(row.entry - 102.5) < 1e-9 and abs(row.exit - 108) < 1e-9
assert abs(row.ret - (108 / 102.5 - 1)) < 1e-12
# idx7 시그널은 청산일 idx13 이 범위 밖 -> 제외. idx6 은 청산 idx12 도 범위 밖 -> 제외
assert len(trA) == 1, trA

# 종가 진입 / 비용 반영
p2 = Params(streak=3, hold=5, entry="close", cost_bps=25)
tr2 = trades_from_signals(sigA, O, C, p2)
assert abs(tr2.iloc[0].ret - ((108 / 103 - 1) - 0.0025)) < 1e-12

# exclusive: idx6 idx7 연속 시그널 중 idx7 제거
p3 = Params(streak=3, hold=1, exclusive=True)
sig3 = build_signals(I, None, p3)
assert list(np.where(sig3["AAA"])[0]) == [2, 6]

# NaN 처리: 결측은 양수로 치지 않는다
I2 = I.copy(); I2.iloc[1, 0] = np.nan
assert not build_signals(I2, None, p)["AAA"].iloc[2]

# 전체 파이프라인 요약 키 확인
res = run_scenarios(O, C, I, F, Params(streak=3, hold=2))
assert res["A_기관3일연속"]["summary"]["trades"] == 3
assert res["B_기관+외국인3일연속"]["summary"]["trades"] == 2
assert res["A_기관3일연속"]["summary"]["win_rate"] == 1.0
print("모든 테스트 통과")
