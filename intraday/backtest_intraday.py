"""저장된 1분봉 (data/minute/*.parquet) 으로 ORB 전략을 백테스트한다.

python -m intraday.backtest_intraday --cost-bps 28 --top 30
"""
from __future__ import annotations

import argparse
import sys
from datetime import time as dtime
from pathlib import Path

import numpy as np
import pandas as pd

from .bars import Bar, load_days, regular_session
from .strategy import ORBParams, simulate_day
from .universe import panel_universe


def run(minute: pd.DataFrame, p: ORBParams, cost_bps: float, top: int | None,
        universe: dict[str, list[str]] | None = None) -> pd.DataFrame:
    trades = []
    minute = regular_session(minute).sort_values(["code", "time"])
    minute["day"] = pd.to_datetime(minute["time"]).dt.strftime("%Y%m%d")
    for (day, code), g in minute.groupby(["day", "code"], sort=True):
        if universe is not None:
            allowed = universe.get(day)
            if allowed is not None and code not in allowed:
                continue
        bars = [Bar(code, r.time.to_pydatetime(), r.open, r.high, r.low, r.close, r.volume)
                for r in g.itertuples(index=False)]
        tr = simulate_day(bars, p, cost_bps)
        if tr:
            trades.append(tr)
    return pd.DataFrame(trades)


def summarize(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"trades": 0}
    r = tr["ret"]
    wins, losses = r[r > 0], r[r <= 0]
    daily = tr.groupby("day")["ret"].mean()
    return {
        "trades": int(len(r)),
        "days": int(tr["day"].nunique()),
        "win_rate": float((r > 0).mean()),
        "avg_ret": float(r.mean()),
        "median_ret": float(r.median()),
        "avg_win": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss": float(losses.mean()) if len(losses) else float("nan"),
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else float("inf"),
        "t_stat": float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 1 else float("nan"),
        "daily_avg": float(daily.mean()),
        "daily_win_rate": float((daily > 0).mean()),
        "max_dd": float(_max_drawdown(daily)),
        "by_reason": tr["reason"].value_counts().to_dict(),
    }


def _max_drawdown(daily: pd.Series) -> float:
    eq = (1 + daily).cumprod()
    return float((eq / eq.cummax() - 1).min())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--cost-bps", type=float, default=28.0, help="왕복 비용 bp (수수료 0.015%%x2 + 세금 0.15% + 슬리피지 0.1%%)")
    ap.add_argument("--top", type=int, default=30, help="유니버스 크기. 0 이면 수집된 전 종목")
    ap.add_argument("--vol-mult", type=float, default=1.5)
    ap.add_argument("--stop", type=float, default=0.02)
    ap.add_argument("--tp", type=float, default=0.03)
    ap.add_argument("--no-vwap", action="store_true")
    ap.add_argument("--or-end", default="09:30")
    ap.add_argument("--exit", default="15:10")
    ap.add_argument("--out", default="results")
    a = ap.parse_args()

    minute = load_days(a.start, a.end)
    if minute.empty:
        print("data/minute 가 비어 있다. 먼저 python -m intraday.collect history 를 실행한다", file=sys.stderr)
        sys.exit(1)
    p = ORBParams(
        or_end=dtime.fromisoformat(a.or_end), exit_time=dtime.fromisoformat(a.exit),
        vol_mult=a.vol_mult, stop_pct=a.stop, tp_pct=a.tp, use_vwap=not a.no_vwap,
    )
    universe = None
    if a.top:
        days = pd.to_datetime(minute["time"]).dt.strftime("%Y%m%d").unique()
        universe = {d: panel_universe(d, a.top) for d in days}
        universe = {d: u for d, u in universe.items() if u}  # 패널 없는 날은 전 종목 허용
        if not universe:
            print("패널이 없어 유니버스 필터 없이 전 종목으로 돌린다", file=sys.stderr)
            universe = None
    tr = run(minute, p, a.cost_bps, a.top, universe)
    s = summarize(tr)
    print(f"기간 {minute['time'].min()} ~ {minute['time'].max()} / 종목 {minute['code'].nunique()} / 설정 {p}")
    for k, v in s.items():
        if isinstance(v, float) and k not in ("t_stat", "profit_factor", "trades"):
            print(f"{k:>14}: {v*100:.2f}%")
        else:
            print(f"{k:>14}: {v}")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tr.to_csv(out / "trades_orb.csv", index=False)
    print(f"트레이드 저장: {out}/trades_orb.csv")


if __name__ == "__main__":
    main()
