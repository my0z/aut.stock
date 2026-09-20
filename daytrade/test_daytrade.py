"""합성 데이터로 데이 단타 후보 선정 / 수익 계산을 검증한다. python -m daytrade.test_daytrade"""
import numpy as np
import pandas as pd

from daytrade.backtest import DayParams, candidates, run, summarize

dates = pd.bdate_range("2024-01-01", periods=25)
tk = ["AAA", "BBB", "CCC", "DDD"]
C = pd.DataFrame(10000.0, index=dates, columns=tk)
O = C.copy()
I = pd.DataFrame(1e8, index=dates, columns=tk)   # 20일 평균 |기관|+|외인| = 2억 -> 기본 밴드 안
F = pd.DataFrame(1e8, index=dates, columns=tk)
d = dates[22]
O.loc[d, "AAA"] = 9500.0    # 갭 -5% 장중 +5.26%
O.loc[d, "BBB"] = 9700.0    # 갭 -3%
O.loc[d, "CCC"] = 9950.0   # 갭 -0.5% -> gap_max -2% 에 걸려 제외
O.loc[d, "DDD"] = 9400.0   # 갭 -6% 지만 전일 기관 외인 동시 순매도 -> 제외
I.loc[dates[21], "DDD"] = -1e8
F.loc[dates[21], "DDD"] = -1e8


def wide(O, C, I, F):
    prev = C.shift(1)
    return {"open": O, "close": C, "inst": I, "foreign": F, "prev_close": prev, "ret": C / O - 1, "gap": O / prev - 1,
            "prev_chg": (C / prev - 1).shift(1), "prev_inst": I.shift(1), "prev_foreign": F.shift(1),
            "liq20": (I.abs() + F.abs()).rolling(20, min_periods=10).mean().shift(1)}


w = wide(O, C, I, F)
p = DayParams()
sel = candidates(w, p)
assert sel.loc[d].tolist() == [True, True, False, False], sel.loc[d].tolist()
assert sel.drop(index=d).values.sum() == 0

# 수익률: 비용 18bp 차감
daily, trades = run(w, p)
assert len(daily) == 1 and len(trades) == 2
exp = ((10000 / 9500 - 1) + (10000 / 9700 - 1)) / 2 - 0.0018
assert abs(daily.iloc[0] - exp) < 1e-12, (daily.iloc[0], exp)

# top=1 이면 갭 하락 큰 AAA 만
d1, t1 = run(w, DayParams(top=1))
assert t1.ticker.tolist() == ["AAA"]

# 슬리피지 50bp: 진입가 95 x 1.005
d2, t2 = run(w, DayParams(top=1, slip_bps=50))
assert abs(t2.ret.iloc[0] - (10000 / (9500 * 1.005) - 1 - 0.0018)) < 1e-12

# 동시 순매도 포함 옵션이면 DDD 도 들어온다
assert candidates(w, DayParams(exclude_both_sell=False)).loc[d].tolist() == [True, True, False, True]

# 유동성 밴드 밖이면 아무것도 없다
assert candidates(w, DayParams(liq_lo=5e8, liq_hi=1e13)).values.sum() == 0

# 시가 결측 (거래 없음) 은 후보에서 빠진다
O2 = O.copy(); O2.loc[d, "AAA"] = np.nan
assert candidates(wide(O2, C, I, F), p).loc[d].tolist() == [False, True, False, False]

s = summarize(daily, trades)
assert s["days"] == 1 and s["avg_positions"] == 2 and 2024 in s["by_year"]
print("daytrade 테스트 통과")
