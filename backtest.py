"""기관 연속 순매수 이벤트 백테스트.

전략
- 시그널: 기관합계 순매수 금액이 N일 (기본 3일) 연속 양수인 종목
- 진입: 시그널 다음 거래일 (기본 시가. --entry close 로 종가 진입 가능)
- 청산: 진입일로부터 H 거래일 (기본 5일) 후 종가
- 시나리오 B: 같은 N일 동안 외국인합계 순매수도 매일 양수

집계
- 승률: 수익률 > 0 인 트레이드 비율
- 평균 수익률 / 중앙값 / 표준편차 / 손익비 / 연도별 분해
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class Params:
    streak: int = 3
    hold: int = 5
    entry: str = "open"  # open | close
    cost_bps: float = 0.0  # 왕복 비용 (bp). 예: 수수료 0.03% * 2 + 세금 0.18% = 24bp
    min_price: float = 0.0  # 동전주 제외용 진입가 하한
    exclusive: bool = False  # True 면 연속 N일 '시작' 시점만 시그널 (겹치는 시그널 제거)


def consecutive_positive(flow: pd.DataFrame, n: int) -> pd.DataFrame:
    """flow 의 값이 n 일 연속 > 0 인 위치를 True 로 표시 (마지막 날 기준)."""
    pos = (flow > 0).astype(float)
    pos[flow.isna()] = 0.0
    roll = pos.rolling(n, min_periods=n).sum()
    return roll == n


def build_signals(inst: pd.DataFrame, foreign: pd.DataFrame | None, p: Params) -> pd.DataFrame:
    sig = consecutive_positive(inst, p.streak)
    if foreign is not None:
        sig = sig & consecutive_positive(foreign, p.streak)
    if p.exclusive:
        # 직전 날에도 시그널이었다면 같은 연속 구간의 연장이므로 제거
        sig = sig & ~sig.shift(1, fill_value=False)
    return sig


def trades_from_signals(sig: pd.DataFrame, O: pd.DataFrame, C: pd.DataFrame, p: Params) -> pd.DataFrame:
    """시그널 (t) -> 진입 t+1 -> 청산 t+1+hold 종가. 롱 포맷 트레이드 목록 반환."""
    entry_px = O if p.entry == "open" else C
    entry = entry_px.shift(-1)  # t+1 진입가
    exit_ = C.shift(-(1 + p.hold))  # t+1+hold 종가
    entry_date = pd.Series(O.index, index=O.index).shift(-1)
    exit_date = pd.Series(O.index, index=O.index).shift(-(1 + p.hold))

    ret = (exit_ / entry - 1.0) - p.cost_bps / 1e4
    valid = sig & entry.notna() & exit_.notna() & (entry > 0)
    if p.min_price > 0:
        valid &= entry >= p.min_price

    stacked = ret.where(valid).stack(future_stack=True).dropna()
    if stacked.empty:
        return pd.DataFrame(columns=["signal_date", "ticker", "entry_date", "exit_date", "entry", "exit", "ret"])
    idx = stacked.index
    df = pd.DataFrame(
        {
            "signal_date": idx.get_level_values(0),
            "ticker": idx.get_level_values(1),
            "ret": stacked.values,
        }
    )
    df["entry_date"] = entry_date.reindex(df["signal_date"]).values
    df["exit_date"] = exit_date.reindex(df["signal_date"]).values
    df["entry"] = entry.stack(future_stack=True).reindex(idx).values
    df["exit"] = exit_.stack(future_stack=True).reindex(idx).values
    return df[["signal_date", "ticker", "entry_date", "exit_date", "entry", "exit", "ret"]].reset_index(drop=True)


def summarize(tr: pd.DataFrame) -> dict:
    if tr.empty:
        return {"trades": 0}
    r = tr["ret"]
    wins = r[r > 0]
    losses = r[r <= 0]
    return {
        "trades": int(len(r)),
        "tickers": int(tr["ticker"].nunique()),
        "win_rate": float((r > 0).mean()),
        "avg_ret": float(r.mean()),
        "median_ret": float(r.median()),
        "std_ret": float(r.std(ddof=0)),
        "avg_win": float(wins.mean()) if len(wins) else float("nan"),
        "avg_loss": float(losses.mean()) if len(losses) else float("nan"),
        "profit_factor": float(wins.sum() / -losses.sum()) if len(losses) and losses.sum() < 0 else float("inf"),
        "t_stat": float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 1 else float("nan"),
    }


def by_year(tr: pd.DataFrame) -> pd.DataFrame:
    if tr.empty:
        return pd.DataFrame()
    g = tr.groupby(pd.to_datetime(tr["entry_date"]).dt.year)["ret"]
    return pd.DataFrame({"trades": g.size(), "win_rate": g.apply(lambda s: (s > 0).mean()), "avg_ret": g.mean()})


def run_scenarios(O, C, I, F, p: Params) -> dict[str, dict]:
    out = {}
    scen = {
        "A_기관3일연속": build_signals(I, None, p),
        "B_기관+외국인3일연속": build_signals(I, F, p),
    }
    for name, sig in scen.items():
        tr = trades_from_signals(sig, O, C, p)
        out[name] = {"summary": summarize(tr), "by_year": by_year(tr), "trades": tr}
    return out


def print_report(res: dict[str, dict], p: Params) -> None:
    print(f"설정: 연속 {p.streak}일 / 보유 {p.hold}거래일 / 진입 {p.entry} / 비용 {p.cost_bps}bp / exclusive={p.exclusive}")
    rows = []
    for name, r in res.items():
        s = r["summary"]
        rows.append({"scenario": name, **{k: v for k, v in s.items()}})
    df = pd.DataFrame(rows).set_index("scenario")
    pct = ["win_rate", "avg_ret", "median_ret", "std_ret", "avg_win", "avg_loss"]
    fmt = df.copy()
    for c in pct:
        if c in fmt:
            fmt[c] = (fmt[c] * 100).round(2).astype(str) + "%"
    print(fmt.T.to_string())
    for name, r in res.items():
        print(f"\n[{name}] 연도별")
        y = r["by_year"].copy()
        if not y.empty:
            y["win_rate"] = (y["win_rate"] * 100).round(2)
            y["avg_ret"] = (y["avg_ret"] * 100).round(3)
        print(y.to_string())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--streak", type=int, default=3)
    ap.add_argument("--hold", type=int, default=5)
    ap.add_argument("--entry", choices=["open", "close"], default="open")
    ap.add_argument("--cost-bps", type=float, default=0.0)
    ap.add_argument("--min-price", type=float, default=0.0)
    ap.add_argument("--exclusive", action="store_true")
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    p = Params(a.streak, a.hold, a.entry, a.cost_bps, a.min_price, a.exclusive)

    from fetch_data import load_panel

    O, C, I, F = load_panel()
    if C.empty:
        print("data/ 캐시가 비어 있다. 먼저 python fetch_data.py 를 실행한다.", file=sys.stderr)
        sys.exit(1)
    print(f"데이터: {C.index.min().date()}~{C.index.max().date()} / {C.shape[1]} 종목 / {C.shape[0]} 거래일")
    res = run_scenarios(O, C, I, F, p)
    print_report(res, p)
    from pathlib import Path

    out = Path(a.out)
    out.mkdir(exist_ok=True)
    for name, r in res.items():
        r["trades"].to_csv(out / f"trades_{name}.csv", index=False)
    print(f"\n트레이드 목록 저장: {out}/")


if __name__ == "__main__":
    main()
