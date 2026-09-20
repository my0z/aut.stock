"""조건 격자 스캔. 어떤 조합이 장중 롱에 유리한지 한 번에 본다. 결과는 results/daytrade/scan.csv

python -m daytrade.scan
python -m daytrade.scan --slip-bps 30
"""
from __future__ import annotations

import argparse
import itertools
from pathlib import Path

import pandas as pd

from daytrade.backtest import SCORES, DayParams, run, summarize
from daytrade.data import load

GAP_MAX = [-0.01, -0.02, -0.03, -0.05]
BANDS = [(0, 5e8), (1e7, 5e8), (1e8, 5e8), (5e8, 1e13)]
TOPS = [10, 30]


def scan(w: dict[str, pd.DataFrame], slip_bps: float = 0.0, cost_bps: float = 18.0) -> pd.DataFrame:
    rows = []
    for gmax, (lo, hi), score, top, excl in itertools.product(GAP_MAX, BANDS, SCORES, TOPS, [True, False]):
        p = DayParams(gap_max=gmax, liq_lo=lo, liq_hi=hi, score=score, top=top, exclude_both_sell=excl,
                      cost_bps=cost_bps, slip_bps=slip_bps)
        d, t = run(w, p)
        s = summarize(d, t)
        if s["days"] < 100:
            continue
        rows.append({"gap_max": gmax, "band": f"{lo/1e8:g}~{hi/1e8:g}억", "score": score, "top": top, "excl_both_sell": excl,
                     "days": s["days"], "avg_n": round(s["avg_positions"], 1), "daily_%": round(s["daily_avg"] * 100, 3),
                     "win_%": round(s["daily_win_rate"] * 100, 1), "sharpe": round(s["sharpe"], 2),
                     "max_dd_%": round(s["max_dd"] * 100, 1),
                     **{f"y{y}_%": round(v * 100, 1) for y, v in s["by_year"].items()}})
    return pd.DataFrame(rows).sort_values("sharpe", ascending=False)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slip-bps", type=float, default=0.0)
    ap.add_argument("--cost-bps", type=float, default=18.0)
    ap.add_argument("--out", default="results/daytrade/scan.csv")
    a = ap.parse_args()
    w = load()
    df = scan(w, a.slip_bps, a.cost_bps)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(f"{len(df)} 조합 (슬리피지 {a.slip_bps}bp)\n상위 20\n{df.head(20).to_string(index=False)}")
    print(f"\n하위 5\n{df.tail(5).to_string(index=False)}")
    for col in ("band", "score", "gap_max", "top", "excl_both_sell"):
        print(f"{col} 별 평균 샤프: {df.groupby(col).sharpe.mean().round(2).to_dict()}")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
