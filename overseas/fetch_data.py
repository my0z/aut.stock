"""키움 미국주식 API 로 일봉을 모아 data/us_panel.parquet 을 만든다.

KRX 와 달리 미국은 전 종목을 한 번에 주는 API가 없어 종목별로 요청한다 (초당 1건 제한).
curated 유니버스 179종목 기준 약 3분. --all 로 실제 상장 종목을 더 긁으려면 페이지가 늘어난다.

python -m overseas.fetch_data                 # 유니버스 전체 3년치
python -m overseas.fetch_data --limit 20       # 테스트용
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from kiwoom import KiwoomClient, KiwoomError
from .universe import all_tickers

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PRICE_DIR = DATA_DIR / "us_price"
PANEL = DATA_DIR / "us_panel.parquet"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--mode", help="real 또는 demo")
    a = ap.parse_args()
    start = (date.today() - timedelta(days=int(a.years * 365.25) + 10)).strftime("%Y%m%d")
    client = KiwoomClient(mode=a.mode, min_interval=a.sleep)
    PRICE_DIR.mkdir(parents=True, exist_ok=True)

    tickers = all_tickers()
    if a.limit:
        tickers = tickers[: a.limit]
    n = len(tickers)
    print(f"기간 {start}~ 대상 {n} 종목 (키움 {client.mode})")
    fail = 0
    for i, (code, exch) in enumerate(tickers, 1):
        path = PRICE_DIR / f"{code}.parquet"
        if path.exists():
            continue
        try:
            df = client.us_daily_chart(code, exch=exch, since=start, max_pages=40)
            df = df[df.index >= pd.Timestamp(start)]  # 페이징이 과거로 며칠 더 갈 수 있어 안전하게 자른다
            if df.empty:
                fail += 1
                print(f"[{i}/{n}] {code} 데이터 없음", file=sys.stderr)
                continue
            df.to_parquet(path)
        except KiwoomError as e:
            fail += 1
            print(f"[{i}/{n}] {code} 실패: {e}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"[{i}/{n}] {code} 실패: {e}", file=sys.stderr)
        if i % 20 == 0:
            print(f"[{i}/{n}] 진행 중 (실패 {fail})", flush=True)

    frames = {}
    for p in sorted(PRICE_DIR.glob("*.parquet")):
        frames[p.stem] = pd.read_parquet(p)
    if not frames:
        print("수집된 데이터 없음", file=sys.stderr)
        sys.exit(1)
    panel = pd.concat({k: v for k, v in frames.items()}, names=["ticker", "date"])
    panel = panel.reorder_levels(["date", "ticker"]).sort_index()
    panel.to_parquet(PANEL, compression="zstd")
    print(f"저장: {PANEL} ({len(frames)} 종목 / {len(panel):,} 행)")


if __name__ == "__main__":
    main()
