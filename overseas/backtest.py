"""미국 시장에서 '장중 대비 오버나이트' 가설과 '당일 등락률 상위' 신호를 검증한다.

주의: 이 스크립트는 아직 실제 데이터로 돌려보지 않았다 (개발 환경이 키움 API 에 접속하지 못함).
서버에서 python -m overseas.fetch_data 로 data/us_panel.parquet 을 만든 뒤 이 스크립트를 돌려
실제 숫자를 확인하고 나서 live.py 로 넘어간다. 국내 오버나이트 전략과 달리 검증되지 않은 가설이다.

python -m overseas.backtest --top 20 --min-chg 0.03 --cost-bps 5
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd


def load_panel() -> pd.DataFrame:
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "us_panel.parquet"
    if not path.exists():
        raise SystemExit(f"{path} 가 없다. 먼저 python -m overseas.fetch_data 를 실행한다")
    return pd.read_parquet(path)


def wide(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    O = panel["open"].unstack("ticker").sort_index()
    C = panel["close"].unstack("ticker").sort_index()
    V = panel["volume"].unstack("ticker").sort_index() if "volume" in panel else pd.DataFrame(index=C.index, columns=C.columns)
    return O, C, V


def intraday_vs_overnight(O: pd.DataFrame, C: pd.DataFrame) -> None:
    intra = (C / O.replace(0, np.nan) - 1).stack(future_stack=True).dropna()
    over = (O.shift(-1) / C - 1).stack(future_stack=True).dropna()
    print(f"장중 (시가->종가): 평균 {intra.mean()*100:+.3f}% 승률 {(intra>0).mean()*100:.1f}% (n={len(intra):,})")
    print(f"오버나이트 (종가->익일시가): 평균 {over.mean()*100:+.3f}% 승률 {(over>0).mean()*100:.1f}% (n={len(over):,})")


def run(O: pd.DataFrame, C: pd.DataFrame, V: pd.DataFrame, top: int, min_chg: float, cost_bps: float,
        min_vol: float = 0.0) -> tuple[pd.Series, pd.DataFrame]:
    chg = C / C.shift(1) - 1
    ok = (chg >= min_chg) & (chg < 0.9)
    if min_vol > 0 and V.notna().any().any():
        ok &= V >= min_vol
    score = chg.where(ok)
    sel = score.rank(axis=1, ascending=False) <= top
    ret = (O.shift(-1) / C - 1).where(sel) - cost_bps / 1e4
    daily = ret.mean(axis=1).dropna()
    st = ret.stack(future_stack=True).dropna()
    trades = pd.DataFrame({"date": st.index.get_level_values(0), "ticker": st.index.get_level_values(1), "ret": st.values})
    return daily, trades


def summarize(daily: pd.Series) -> dict:
    if daily.empty:
        return {"days": 0}
    eq = (1 + daily).cumprod()
    dd = eq / eq.cummax() - 1
    return {
        "days": int(len(daily)), "daily_avg": float(daily.mean()), "daily_win_rate": float((daily > 0).mean()),
        "annualized": float(eq.iloc[-1] ** (252 / len(daily)) - 1), "sharpe": float(daily.mean() / daily.std() * np.sqrt(252)),
        "max_dd": float(dd.min()), "by_year": {int(k): float((1 + g).prod() - 1) for k, g in daily.groupby(daily.index.year)},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--min-chg", type=float, default=0.03)
    ap.add_argument("--cost-bps", type=float, default=5.0, help="미국 증권사 수수료+슬리피지 가정 (왕복)")
    ap.add_argument("--out", default="results/overseas")
    a = ap.parse_args()

    panel = load_panel()
    O, C, V = wide(panel)
    print(f"데이터 {C.index.min().date()}~{C.index.max().date()} / {C.shape[1]} 종목 / {C.shape[0]} 거래일\n")
    print("== 가설: 장중 vs 오버나이트 ==")
    intraday_vs_overnight(O, C)

    print(f"\n== 신호: 당일 등락 {a.min_chg*100:.0f}%+ 상위{a.top} 종가매수->익일시가매도 (비용 {a.cost_bps}bp) ==")
    daily, trades = run(O, C, V, a.top, a.min_chg, a.cost_bps)
    s = summarize(daily)
    for k, v in s.items():
        if k == "by_year":
            print(f"{'by_year':>14}: " + "  ".join(f"{y}:{r*100:+.1f}%" for y, r in v.items()))
        elif k in ("days",):
            print(f"{k:>14}: {v}")
        elif k == "sharpe":
            print(f"{k:>14}: {v:.2f}")
        else:
            print(f"{k:>14}: {v*100:.2f}%")

    from pathlib import Path

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    daily.rename("ret").to_csv(out / "daily.csv")
    trades.to_csv(out / "trades.csv", index=False)
    print(f"\n저장: {out}/")
    print("\n주의: curated 179종목 3년치는 표본이 제한적이다. 실계좌 전환 전 최소 몇 주 페이퍼로 재확인한다.")


if __name__ == "__main__":
    main()
