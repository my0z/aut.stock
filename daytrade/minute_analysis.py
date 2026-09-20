"""갭 하락 후보의 장중 경로 분석. 반등이 몇 시에 오고 언제 팔아야 하는지.

입력: data/daytrade/minute/*.parquet (python -m daytrade.collect history 로 수집)
출력: 콘솔 표 + results/daytrade/minute_path.csv

- 평균 경로: 시가 대비 분 단위 평균 수익률 (09:01 ... 15:30)
- 매도 시각별: 시가에 사서 T 에 팔았을 때 평균 (비용 후)
- 매수 지연별: 09:05 / 09:10 / 09:30 종가에 사서 15:20 에 팔았을 때
- 고점 시각 분포: 종목-일 별 장중 최고가가 찍힌 시간대
- 첫 1분 (시가 체결 슬리피지 대용): 09:00 봉의 고가/종가 대비 시가

python -m daytrade.minute_analysis
python -m daytrade.minute_analysis --cost-bps 18
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from daytrade.collect import load_minutes

KEY_TIMES = ["09:01", "09:03", "09:05", "09:10", "09:15", "09:20", "09:30", "09:45", "10:00", "10:30", "11:00",
             "12:00", "13:00", "14:00", "14:30", "15:00", "15:10", "15:20", "15:30"]


def paths(m: pd.DataFrame) -> pd.DataFrame:
    """(종목-일) x 시각(HH:MM) 의 시가 대비 수익률. 시가 = 그날 첫 봉 (09:00) 시가."""
    m = m.copy()
    m["time"] = pd.to_datetime(m["time"])
    m["day"] = m["time"].dt.strftime("%Y%m%d")
    m["hm"] = m["time"].dt.strftime("%H:%M")
    m = m.sort_values(["day", "code", "time"])
    first = m.groupby(["day", "code"])["open"].transform("first")
    m["r"] = m["close"] / first - 1
    m["r_high"] = m["high"] / first - 1
    m["r_low"] = m["low"] / first - 1
    wide = m.pivot_table(index=["day", "code"], columns="hm", values="r")
    return wide.ffill(axis=1), m


def summarize(m: pd.DataFrame, cost_bps: float) -> dict[str, pd.DataFrame]:
    wide, long = paths(m)
    cost = cost_bps / 1e4
    times = [t for t in KEY_TIMES if t in wide.columns]
    out: dict[str, pd.DataFrame] = {}
    # 1) 평균 경로 와 매도 시각별 (시가 매수)
    path = pd.DataFrame({
        "mean_%": wide[times].mean() * 100,
        "median_%": wide[times].median() * 100,
        "win_%": (wide[times] > 0).mean() * 100,
        "sell_here_net_%": (wide[times] - cost).mean() * 100,
    }).round(3)
    out["path"] = path
    # 2) 매수 지연: T 종가에 사서 15:20 에 판다
    last = "15:20" if "15:20" in wide.columns else wide.columns[-1]
    rows = []
    for t in ["09:00", "09:01", "09:03", "09:05", "09:10", "09:15", "09:30", "10:00"]:
        if t not in wide.columns:
            continue
        entry = 1 + wide[t]
        r = (1 + wide[last]) / entry - 1 - cost
        rows.append({"buy_at": t, "sell_at": last, "mean_%": r.mean() * 100, "median_%": r.median() * 100, "win_%": (r > 0).mean() * 100})
    out["entry_delay"] = pd.DataFrame(rows).round(3)
    # 3) 최적 조합 격자 (매수 T1 x 매도 T2)
    grid = []
    for t1 in ["09:00", "09:05", "09:10", "09:30"]:
        for t2 in ["09:10", "09:30", "10:00", "11:00", "13:00", "14:00", "15:00", "15:20"]:
            if t1 not in wide.columns or t2 not in wide.columns or t2 <= t1:
                continue
            r = (1 + wide[t2]) / (1 + wide[t1]) - 1 - cost
            grid.append({"buy": t1, "sell": t2, "mean_%": round(r.mean() * 100, 3), "win_%": round((r > 0).mean() * 100, 1),
                         "sharpe_d": round(r.groupby(level="day").mean().pipe(lambda d: d.mean() / d.std() * np.sqrt(252)), 2)})
    out["grid"] = pd.DataFrame(grid).sort_values("mean_%", ascending=False)
    # 4) 고점 시각 분포 (시간대별 비율)
    hi_time = long.loc[long.groupby(["day", "code"])["r_high"].idxmax(), ["day", "code", "hm", "r_high"]]
    hi_time["hour"] = hi_time["hm"].str[:2]
    out["high_time"] = pd.DataFrame({
        "share_%": hi_time["hour"].value_counts(normalize=True).sort_index() * 100,
        "avg_high_%": hi_time.groupby("hour")["r_high"].mean() * 100,
    }).round(2)
    # 5) 첫 1분 슬리피지 대용 + 장중 +2% 터치 비율
    f = long[long["hm"] == "09:00"]
    touch2 = long.groupby(["day", "code"])["r_high"].max() >= 0.02
    out["first_min"] = pd.DataFrame({
        "value": {
            "n_stock_days": len(wide),
            "first_min_close_vs_open_%": f["r"].mean() * 100,
            "first_min_high_vs_open_%": f["r_high"].mean() * 100,
            "first_min_low_vs_open_%": f["r_low"].mean() * 100,
            "touch_+2%_anytime_%": touch2.mean() * 100,
            "close_vs_open_%": wide[wide.columns[-1]].mean() * 100,
        }
    }).round(3)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-bps", type=float, default=18.0)
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--out", default="results/daytrade")
    a = ap.parse_args()
    m = load_minutes(a.start, a.end)
    if m.empty:
        print("분봉이 없다. 먼저 python -m daytrade.collect history --days 60")
        return
    pd.set_option("display.width", 200)
    res = summarize(m, a.cost_bps)
    print(f"분봉 {len(m):,} 행 / 종목-일 {int(res['first_min'].loc['n_stock_days','value'])} 건 / 비용 {a.cost_bps}bp\n")
    print("== 시가 대비 평균 경로 (여기서 팔면)\n", res["path"].to_string())
    print("\n== 매수 시각을 늦추면 (15:20 매도)\n", res["entry_delay"].to_string(index=False))
    print("\n== 매수 x 매도 시각 격자 상위\n", res["grid"].head(12).to_string(index=False))
    print("\n== 장중 고점이 찍힌 시간대\n", res["high_time"].to_string())
    print("\n== 첫 1분 과 터치\n", res["first_min"].to_string())
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    res["path"].to_csv(out / "minute_path.csv")
    res["grid"].to_csv(out / "minute_grid.csv", index=False)
    print(f"\n저장: {out}/minute_path.csv minute_grid.csv")


if __name__ == "__main__":
    main()
