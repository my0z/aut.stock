"""KRX 일별 패널 (data/panel.parquet) 을 최신 거래일까지 덧붙인다. 매일 16:40 타이머로 실행.

날짜 하나에 전 종목을 한 번에 받으므로 하루당 요청 6번 (코스피/코스닥 x 시세 1 + 기관 1 + 외국인 1).

python update_daily.py            # 마지막 날짜 다음부터 오늘까지
python update_daily.py --date 20260921
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

KST = timezone(timedelta(hours=9))
DATA_DIR = Path(__file__).resolve().parent / "data"
PANEL = DATA_DIR / "panel.parquet"


def fetch_day(day: str) -> pd.DataFrame:
    """day (YYYYMMDD) 의 (ticker) x [open close inst foreign] . 휴장일이면 빈 DataFrame."""
    from pykrx import stock

    frames = []
    for mkt in ("KOSPI", "KOSDAQ"):
        px = stock.get_market_ohlcv(day, market=mkt)
        time.sleep(1)
        if px is None or px.empty or "종가" not in px.columns:
            continue
        px = px[px["거래량"] > 0] if "거래량" in px.columns else px
        base = pd.DataFrame({"open": px["시가"].astype(float), "close": px["종가"].astype(float)})
        base.index.name = "ticker"
        for inv, col in (("기관합계", "inst"), ("외국인", "foreign")):
            np_ = stock.get_market_net_purchases_of_equities(day, day, mkt, inv)
            time.sleep(1)
            if np_ is not None and not np_.empty and "순매수거래대금" in np_.columns:
                base[col] = np_["순매수거래대금"].astype(float).reindex(base.index)
            else:
                base[col] = float("nan")
        frames.append(base)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames)
    out = out[~out.index.duplicated(keep="first")]
    out["date"] = pd.Timestamp(day)
    return out.reset_index().set_index(["date", "ticker"])[["open", "close", "inst", "foreign"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="특정 날짜만 (YYYYMMDD)")
    a = ap.parse_args()
    if not (os.environ.get("KRX_ID") and os.environ.get("KRX_PW")):
        print("KRX_ID / KRX_PW 환경변수가 필요하다", file=sys.stderr)
        sys.exit(1)
    pn = pd.read_parquet(PANEL) if PANEL.exists() else pd.DataFrame(columns=["open", "close", "inst", "foreign"])
    have = set(pn.index.get_level_values("date").unique()) if not pn.empty else set()
    now = datetime.now(KST)
    if a.date:
        days = [a.date]
    else:
        last = max(have) if have else pd.Timestamp(now.date() - timedelta(days=30))
        end = now.date() if now.hour >= 16 else now.date() - timedelta(days=1)  # 16시 전엔 오늘 확정치가 없다
        days = [d.strftime("%Y%m%d") for d in pd.bdate_range(last + pd.Timedelta(days=1), end)]
    if not days:
        print("추가할 날짜 없음")
        return
    added = []
    for day in days:
        if pd.Timestamp(day) in have:
            continue
        try:
            df = fetch_day(day)
        except Exception as e:  # noqa: BLE001
            print(f"{day} 실패: {e}", file=sys.stderr)
            continue
        if df.empty:
            print(f"{day} 휴장 또는 데이터 없음")
            continue
        pn = pd.concat([pn, df])
        added.append(day)
        print(f"{day} {len(df)} 종목 추가")
    if added:
        pn = pn.sort_index()
        pn.to_parquet(PANEL, compression="zstd")
        print(f"저장: {PANEL} ({pn.index.get_level_values('date').min().date()} ~ {pn.index.get_level_values('date').max().date()})")


if __name__ == "__main__":
    main()
