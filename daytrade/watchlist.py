"""다음 거래일 아침 감시 목록. 전일 (스냅샷 마지막 날) 조건을 통과한 종목과 매수 발동 가격을 찍는다.

발동 규칙: 08:59 예상체결가 (또는 09:00 시가) 가 trigger 이하 (전일 종가 대비 gap_max) 이면 시가 매수 -> 15:20 시장가 매도.
후보 중 갭 하락이 큰 순으로 top 개까지만 산다.

실전 순서 (08:59): 키움 예상체결등락률 하락 상위 (ka10029) 를 받아 이 목록과 교집합 -> 갭 -2% 이하 중 큰 순 30 시장가 매수.

python -m daytrade.watchlist                     # 밴드 전체 (약 1200 종목) + prev_drop5 플래그
python -m daytrade.watchlist --prev-drop -0.05   # 전일 -5% 이상 하락만 (검증상 표본이 적어 불안정. 참고용)
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from daytrade.data import load


def build(w: dict[str, pd.DataFrame], gap_max: float = -0.02, liq_lo: float = 1e7, liq_hi: float = 5e8,
          min_price: float = 1000.0, prev_drop: float = 0.0, min_flow: float = -1e13) -> pd.DataFrame:
    C, I, F = w["close"], w["inst"], w["foreign"]
    last = C.index[-1]
    c, i, f = C.loc[last], I.loc[last], F.loc[last]
    liq = (I.abs() + F.abs()).rolling(20, min_periods=10).mean().loc[last]
    chg = c / C.iloc[-2] - 1
    ok = (c >= min_price) & (liq >= liq_lo) & (liq < liq_hi) & ~((i < 0) & (f < 0)) & ((i + f) >= min_flow)
    if prev_drop < 0:
        ok &= chg <= prev_drop
    df = pd.DataFrame({"close": c, "prev_chg_%": chg * 100, "inst_억": i / 1e8, "foreign_억": f / 1e8, "liq20_억": liq / 1e8})[ok]
    df["prev_drop5"] = df["prev_chg_%"] <= -5
    df["trigger"] = (df["close"] * (1 + gap_max)).round(0)
    df.index.name = "ticker"
    df.attrs["asof"] = last.date()
    return df.sort_values("prev_chg_%")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gap-max", type=float, default=-0.02)
    ap.add_argument("--prev-drop", type=float, default=0.0, help="전일 등락률 상한. 0 이면 조건 없음")
    ap.add_argument("--min-flow", type=float, default=-1e13, help="전일 기관+외인 순매수 하한 (원)")
    ap.add_argument("--out", default="results/daytrade/watchlist.csv")
    a = ap.parse_args()
    w = load()
    df = build(w, gap_max=a.gap_max, prev_drop=a.prev_drop, min_flow=a.min_flow)
    pd.set_option("display.width", 200)
    print(f"기준일 {df.attrs['asof']} 후보 {len(df)} 종목. 발동: 예상체결가 <= trigger (전일 종가 {a.gap_max*100:+.0f}%)")
    print(df.head(40).round(2).to_string())
    if len(df) > 40:
        print(f"... 외 {len(df)-40} 종목은 CSV 참조")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out)
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
