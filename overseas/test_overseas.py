"""미국 모듈 순수 로직 검증 (네트워크 없이). python -m overseas.test_overseas"""
import types
from pathlib import Path

import pandas as pd

from kiwoom.client import _us_chart_frame, _us_rank_frame
from overseas import live
from overseas.backtest import run, summarize
from overseas.universe import all_tickers

# 1) 유니버스: 중복/빈 항목 없음
u = all_tickers()
assert len(u) == len(set(u)) and all(t and e in ("NY", "ND", "NA") for t, e in u)

# 2) 일봉 파싱
rows = [
    {"dt": "20260918", "open_pric": "100.5", "high_pric": "105", "low_pric": "99", "cur_prc": "104", "acc_trde_qty": "123456"},
    {"dt": "20260919", "open_pric": "104", "high_pric": "110", "low_pric": "103", "cur_prc": "108", "acc_trde_qty": "200000"},
]
df = _us_chart_frame(rows)
assert list(df.columns) == ["open", "high", "low", "close", "volume"]
assert df.loc["2026-09-18", "close"] == 104 and df.loc["2026-09-19", "volume"] == 200000
assert _us_chart_frame([]).empty

# 3) 랭킹 파싱 (부호 있는 등락률, 종가)
rank_rows = [
    {"stk_cd": "AAPL", "stk_nm": "애플", "stex_tp": "ND", "cur_prc": "+230.5", "flu_rt": "+3.20", "acc_trde_qty": "5000000", "sdnin_rt": "+150.0"},
    {"stk_cd": "TSLA", "stk_nm": "테슬라", "stex_tp": "ND", "cur_prc": "+410", "flu_rt": "+8.10", "acc_trde_qty": "9000000"},
]
rf = _us_rank_frame(rank_rows)
assert rf.loc["AAPL", "price"] == 230.5 and abs(rf.loc["AAPL", "chg"] - 0.032) < 1e-9
assert rf.loc["TSLA", "chg"] > rf.loc["AAPL", "chg"]
assert _us_rank_frame([]).empty

# 4) select(): 등락률/가격 필터
class FakeClient:
    def us_price_surge(self, **kw):
        return rf.assign(volume=[5000000, 9000000])

picks = live.select(FakeClient(), top=5, min_chg=0.05, min_price=1.0)
assert list(picks.index) == ["TSLA"], picks  # 애플은 3.2% < 5% 컷

# 5) 백테스트 run(): 합성 데이터로 부호와 비용 반영 확인
dates = pd.bdate_range("2026-01-05", periods=6)
C = pd.DataFrame({"A": [100, 103, 100, 100, 100, 100], "B": [50, 50, 50, 50, 50, 50]}, index=dates)
O = C.copy()
O.loc[dates[2]] = [106, 50]  # A 는 2일차(103) 다음날 시가 106 -> +2.91%
V = pd.DataFrame({"A": [0, 1000, 0, 0, 0, 0], "B": [0, 0, 0, 0, 0, 0]}, index=dates)
daily, trades = run(O, C, V, top=1, min_chg=0.02, cost_bps=10.0)
assert len(trades) == 1 and trades.iloc[0]["ticker"] == "A"
assert abs(trades.iloc[0]["ret"] - (106 / 103 - 1 - 0.001)) < 1e-9
s = summarize(daily)
assert s["days"] == 1

# 6) cmd_buy 페이퍼 기록 (파일 검증 후 원복)
p = Path("results/overseas_paper.csv")
backup = p.read_text() if p.exists() else None
if p.exists():
    p.unlink()
live.kakao = lambda *a, **k: True  # noqa: ARG005

class FakeClient2:
    def us_price_surge(self, **kw):
        return pd.DataFrame({"name": ["애플"], "stex_tp": ["ND"], "price": [230.5], "chg": [0.08], "volume": [5000000]}, index=pd.Index(["AAPL"], name="code"))

a = types.SimpleNamespace(top=5, min_chg=0.03, min_price=1.0, real=False, capital=5000.0, cost_bps=5.0)
live.cmd_buy(FakeClient2(), a)
df = pd.read_csv(p, dtype={"code": str})
assert df.iloc[0]["code"] == "AAPL" and df.iloc[0]["qty"] == int(5000 / 5 / 230.5)
p.unlink()
if backup is not None:
    p.write_text(backup)

print("모든 테스트 통과")
