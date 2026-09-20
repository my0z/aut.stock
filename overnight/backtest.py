"""오버나이트 수급 전략 백테스트 (KRX 일별 패널 기반).

발견
- 최근 3년 한국 시장은 장중 (시가->종가) 이 평균 마이너스이고 오버나이트 (종가->익일 시가) 가 플러스다.
- 당일 기관과 외국인이 동시에 순매수한 종목 중 순매수 금액 상위 N 을 종가에 사서 익일 시가에 팔면
  비용 18bp 를 빼고도 매일 평균 +0.16% 안팎이 남고 3년 내내 플러스였다.
- 당일 +3% 이상 오른 종목으로 좁히면 평균 +0.28% 로 커진다.

규칙
- 후보: 당일 기관합계 > 0 그리고 외국인합계 > 0 (금액 기준)
- 정렬: 기관 + 외국인 순매수 금액 합계 내림차순 상위 N
- 필터: 당일 등락률 >= min_chg (기본 +3%) 그리고 종가 >= min_price
- 진입: 당일 종가 (15:20~15:30 동시호가 시장가)
- 청산: 익일 시가 (08:30~09:00 장전 동시호가 시장가)
- 균등 배분

python -m overnight.backtest --top 30 --min-chg 0.03 --cost-bps 18
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class OvernightParams:
    top: int = 30
    min_chg: float = 0.03
    min_price: float = 0.0
    cost_bps: float = 18.0  # 수수료 0.015% x2 + 거래세 0.15%


def candidates(C: pd.DataFrame, I: pd.DataFrame, F: pd.DataFrame, p: OvernightParams) -> pd.DataFrame:
    """날짜 x 종목 bool. 그날 종가에 살 종목."""
    chg = C / C.shift(1) - 1
    ok = (I > 0) & (F > 0) & (chg >= p.min_chg) & (C >= p.min_price)
    score = (I + F).where(ok)
    return score.rank(axis=1, ascending=False) <= p.top


def run(O: pd.DataFrame, C: pd.DataFrame, I: pd.DataFrame, F: pd.DataFrame, p: OvernightParams) -> tuple[pd.Series, pd.DataFrame]:
    """(일별 포트폴리오 수익률, 종목별 트레이드 목록)"""
    O = O.replace(0, np.nan)
    sel = candidates(C, I, F, p)
    ret = (O.shift(-1) / C - 1).where(sel) - p.cost_bps / 1e4
    daily = ret.mean(axis=1).dropna()
    st = ret.stack(future_stack=True).dropna()
    trades = pd.DataFrame({"date": st.index.get_level_values(0), "ticker": st.index.get_level_values(1), "ret": st.values})
    trades["entry"] = C.stack(future_stack=True).reindex(st.index).values
    trades["exit"] = O.shift(-1).stack(future_stack=True).reindex(st.index).values
    return daily, trades


def summarize(daily: pd.Series, trades: pd.DataFrame) -> dict:
    eq = (1 + daily).cumprod()
    dd = eq / eq.cummax() - 1
    r = trades["ret"]
    return {
        "days": int(len(daily)),
        "avg_positions": float(trades.groupby("date").size().mean()),
        "daily_avg": float(daily.mean()),
        "daily_win_rate": float((daily > 0).mean()),
        "annualized": float(eq.iloc[-1] ** (252 / len(daily)) - 1),
        "sharpe": float(daily.mean() / daily.std() * np.sqrt(252)),
        "max_dd": float(dd.min()),
        "worst_day": float(daily.min()),
        "trade_win_rate": float((r > 0).mean()),
        "trade_avg": float(r.mean()),
        "trade_p05": float(r.quantile(0.05)),
        "trade_p95": float(r.quantile(0.95)),
        "by_year": {int(k): float((1 + g).prod() - 1) for k, g in daily.groupby(daily.index.year)},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--min-chg", type=float, default=0.03)
    ap.add_argument("--min-price", type=float, default=0.0)
    ap.add_argument("--cost-bps", type=float, default=18.0)
    ap.add_argument("--out", default="results/overnight")
    a = ap.parse_args()
    from pathlib import Path

    from fetch_data import load_panel

    O, C, I, F = load_panel()
    p = OvernightParams(a.top, a.min_chg, a.min_price, a.cost_bps)
    daily, trades = run(O, C, I, F, p)
    s = summarize(daily, trades)
    print(f"설정 {p}\n데이터 {C.index.min().date()}~{C.index.max().date()} {C.shape[1]} 종목")
    for k, v in s.items():
        if k == "by_year":
            print(f"{'by_year':>16}: " + "  ".join(f"{y}:{r*100:+.1f}%" for y, r in v.items()))
        elif k in ("days",):
            print(f"{k:>16}: {v}")
        elif k in ("sharpe", "avg_positions"):
            print(f"{k:>16}: {v:.2f}")
        else:
            print(f"{k:>16}: {v*100:.2f}%")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    daily.rename("ret").to_csv(out / "daily.csv")
    trades.to_csv(out / "trades.csv", index=False)
    print(f"저장: {out}/")


if __name__ == "__main__":
    main()
