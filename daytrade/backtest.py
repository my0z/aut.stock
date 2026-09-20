"""데이 단타 백테스트: 시가 매수 -> 당일 종가 매도.

3년 일봉 (시가 종가 기관 외국인) 으로 09:00 에 알 수 있는 정보만 써서 그날 장중 (시가->종가) 에
플러스인 종목군을 찾는다. 한국 시장 장중 평균은 마이너스라 (-0.12%/일) 조건 없이 사면 진다.

찾은 것
- 갭 하락 (시가 < 전일 종가) 종목은 장중에 반등한다. 갭 -1%~-2% 이면 +0.24% 갭 -5% 이하면 +0.7% 이상
- 그런데 이 반등은 유동성이 낮을수록 크고 20일 평균 기관+외인 거래금액 5억 이상인 종목에서는 사라진다
  (호가 스프레드 반등 성격). 실제로 사려면 시가보다 비싸게 사게 되고 슬리피지 0.5% 면 수익이 거의 없어진다
- 유동 종목 (5억 이상) 에서는 갭 전일등락 수급 조합 어디에도 장중 롱 우위가 없었다

규칙 (기본값)
- 후보: 시가 갭 gap_min <= gap <= gap_max (기본 -30% ~ -2%)
- 유동성 밴드: liq_lo <= 20일 평균 |기관|+|외인| < liq_hi (기본 0.1억 ~ 5억)
- 필터: 전일 종가 >= min_price (1,000원). 전일 기관 외국인 동시 순매도는 제외
- 선정: 갭 하락 큰 순서 상위 top (30) 균등 배분
- 진입: 시가 x (1 + slip_bps). 청산: 종가. 비용 cost_bps (18bp)

python -m daytrade.backtest                       # 기본 설정
python -m daytrade.backtest --slip-bps 50         # 슬리피지 반영
python -m daytrade.backtest --liq-lo 5e8 --liq-hi 1e13   # 유동 종목만
python -m daytrade.backtest --sensitivity         # 유동성 밴드 x 슬리피지 표
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

SCORES = ("gap_down", "prev_down", "prev_up", "liq", "flow")


@dataclass
class DayParams:
    gap_max: float = -0.02
    gap_min: float = -0.30
    liq_lo: float = 1e7
    liq_hi: float = 5e8
    min_price: float = 1000.0
    exclude_both_sell: bool = True
    score: str = "gap_down"
    top: int = 30
    cost_bps: float = 18.0   # 수수료 0.015% x2 + 거래세 0.15%
    slip_bps: float = 0.0    # 시가 대비 매수 체결 슬리피지


def _score(w: dict[str, pd.DataFrame], name: str) -> pd.DataFrame:
    if name == "gap_down":
        return -w["gap"]
    if name == "prev_down":
        return -w["prev_chg"]
    if name == "prev_up":
        return w["prev_chg"]
    if name == "liq":
        return w["liq20"]
    if name == "flow":
        return w["prev_inst"] + w["prev_foreign"]
    raise ValueError(f"score 는 {SCORES} 중 하나: {name}")


def candidates(w: dict[str, pd.DataFrame], p: DayParams) -> pd.DataFrame:
    """날짜 x 종목 bool. 그날 시가에 살 종목."""
    gap, liq, pc = w["gap"], w["liq20"], w["prev_close"]
    ok = (gap <= p.gap_max) & (gap >= p.gap_min) & (liq >= p.liq_lo) & (liq < p.liq_hi) & (pc >= p.min_price)
    ok &= w["ret"].notna()
    if p.exclude_both_sell:
        ok &= ~((w["prev_inst"] < 0) & (w["prev_foreign"] < 0))
    sc = _score(w, p.score).where(ok)
    return sc.rank(axis=1, ascending=False, method="first") <= p.top


def run(w: dict[str, pd.DataFrame], p: DayParams) -> tuple[pd.Series, pd.DataFrame]:
    """(일별 포트폴리오 수익률, 트레이드 목록). 후보가 없는 날은 빠진다."""
    sel = candidates(w, p)
    entry = w["open"] * (1 + p.slip_bps / 1e4)
    ret = (w["close"] / entry - 1).where(sel) - p.cost_bps / 1e4
    daily = ret.mean(axis=1).dropna()
    st = ret.stack(future_stack=True).dropna()
    idx = st.index
    trades = pd.DataFrame({
        "date": idx.get_level_values(0), "ticker": idx.get_level_values(1), "ret": st.values,
        "entry": entry.stack(future_stack=True).reindex(idx).values,
        "exit": w["close"].stack(future_stack=True).reindex(idx).values,
        "gap": w["gap"].stack(future_stack=True).reindex(idx).values,
        "liq20": w["liq20"].stack(future_stack=True).reindex(idx).values,
    })
    return daily, trades


def summarize(daily: pd.Series, trades: pd.DataFrame) -> dict:
    if daily.empty:
        return {"days": 0}
    eq = (1 + daily).cumprod()
    dd = eq / eq.cummax() - 1
    r = trades["ret"]
    sd = daily.std()
    return {
        "days": int(len(daily)),
        "avg_positions": float(trades.groupby("date").size().mean()),
        "daily_avg": float(daily.mean()),
        "daily_win_rate": float((daily > 0).mean()),
        "annualized": float(eq.iloc[-1] ** (252 / len(daily)) - 1),
        "sharpe": float(daily.mean() / sd * np.sqrt(252)) if sd > 0 else float("nan"),
        "max_dd": float(dd.min()),
        "worst_day": float(daily.min()),
        "trade_win_rate": float((r > 0).mean()),
        "trade_avg": float(r.mean()),
        "trade_median": float(r.median()),
        "by_year": {int(k): float((1 + g).prod() - 1) for k, g in daily.groupby(daily.index.year)},
    }


def print_summary(s: dict) -> None:
    for k, v in s.items():
        if k == "by_year":
            print(f"{'by_year':>16}: " + "  ".join(f"{y}:{r*100:+.1f}%" for y, r in v.items()))
        elif k == "days":
            print(f"{k:>16}: {v}")
        elif k in ("sharpe", "avg_positions"):
            print(f"{k:>16}: {v:.2f}")
        else:
            print(f"{k:>16}: {v*100:.2f}%")


BANDS = [(0, 1e7), (1e7, 1e8), (1e8, 5e8), (5e8, 1e9), (1e9, 1e13)]
SLIPS = [0, 30, 50, 100]


def sensitivity(w: dict[str, pd.DataFrame], p: DayParams) -> pd.DataFrame:
    """유동성 밴드 x 슬리피지 별 일평균 수익률 (%) 과 샤프."""
    rows = []
    for lo, hi in BANDS:
        for slip in SLIPS:
            q = replace(p, liq_lo=lo, liq_hi=hi, slip_bps=slip)
            d, t = run(w, q)
            s = summarize(d, t)
            rows.append({"band": f"{lo/1e8:g}~{hi/1e8:g}억", "slip_bps": slip, "days": s.get("days", 0),
                         "avg_n": round(s.get("avg_positions", 0), 1), "daily_%": round(s.get("daily_avg", 0) * 100, 3),
                         "sharpe": round(s.get("sharpe", 0), 2), "trade_win_%": round(s.get("trade_win_rate", 0) * 100, 1)})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap-max", type=float, default=-0.02)
    ap.add_argument("--gap-min", type=float, default=-0.30)
    ap.add_argument("--liq-lo", type=float, default=1e7)
    ap.add_argument("--liq-hi", type=float, default=5e8)
    ap.add_argument("--min-price", type=float, default=1000.0)
    ap.add_argument("--keep-both-sell", action="store_true", help="전일 동시 순매도 종목도 포함")
    ap.add_argument("--score", choices=SCORES, default="gap_down")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--cost-bps", type=float, default=18.0)
    ap.add_argument("--slip-bps", type=float, default=0.0)
    ap.add_argument("--sensitivity", action="store_true", help="유동성 밴드 x 슬리피지 표")
    ap.add_argument("--out", default="results/daytrade")
    a = ap.parse_args()
    from daytrade.data import load

    w = load()
    p = DayParams(a.gap_max, a.gap_min, a.liq_lo, a.liq_hi, a.min_price, not a.keep_both_sell, a.score, a.top, a.cost_bps, a.slip_bps)
    C = w["close"]
    print(f"설정 {p}\n데이터 {C.index.min().date()}~{C.index.max().date()} {C.shape[1]} 종목")
    base = (w["ret"].where(w["prev_close"] >= p.min_price) - p.cost_bps / 1e4).mean(axis=1).dropna()
    print(f"참고 전 종목 장중 일평균 {base.mean()*100:+.3f}% (비용 후)")
    daily, trades = run(w, p)
    print_summary(summarize(daily, trades))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    daily.rename("ret").to_csv(out / "daily.csv")
    trades.to_csv(out / "trades.csv", index=False)
    if a.sensitivity:
        tbl = sensitivity(w, p)
        pd.set_option("display.width", 200)
        print("\n유동성 밴드 (20일 평균 기관+외인 거래금액) x 슬리피지")
        print(tbl.to_string(index=False))
        tbl.to_csv(out / "sensitivity.csv", index=False)
    print(f"저장: {out}/")


if __name__ == "__main__":
    main()
