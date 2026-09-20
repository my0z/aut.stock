"""키움 REST API 로 투자자별 일별 순매수 (data/flow) 를 채운다. KRX 차단과 무관하게 동작한다.

기본은 data/price 는 있는데 data/flow 가 없는 종목만 받는다. --all 이면 전 종목을 다시 받는다.
가격 (data/price) 이 비어 있으면 키움 일봉 (ka10081) 으로 함께 채운다.

python fetch_data_kiwoom.py            # 빠진 flow 만
python fetch_data_kiwoom.py --all      # 전부 키움 기준으로 통일
"""
from __future__ import annotations

import argparse
import sys
import time

from fetch_data import FLOW_DIR, PRICE_DIR, default_range, ticker_universe_cached
from kiwoom import KiwoomClient, KiwoomError


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--sleep", type=float, default=1.0, help="요청 간격 (초). 키움은 초당 1건 제한")
    ap.add_argument("--mode", help="real 또는 demo. 시세 조회는 둘 다 된다")
    a = ap.parse_args()
    start, end = default_range(a.years)
    client = KiwoomClient(mode=a.mode, min_interval=a.sleep)
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    FLOW_DIR.mkdir(parents=True, exist_ok=True)

    tickers = ticker_universe_cached(client)
    if not a.all:
        tickers = [t for t in tickers if not (FLOW_DIR / f"{t}.parquet").exists()]
    if a.limit:
        tickers = tickers[: a.limit]
    n = len(tickers)
    print(f"기간 {start}~{end} 대상 {n} 종목 (키움 {client.mode})")
    fail = 0
    for i, t in enumerate(tickers, 1):
        try:
            p_path = PRICE_DIR / f"{t}.parquet"
            if not p_path.exists():
                px = client.daily_chart(t, max_pages=10)
                px = px[px.index >= start]
                if not px.empty:
                    px[["open", "high", "low", "close", "volume"]].to_parquet(p_path)
            fl = client.investor_daily(t, since=start)
            if fl.empty:
                fail += 1
                print(f"[{i}/{n}] {t} 투자자 데이터 없음", file=sys.stderr)
            else:
                fl.to_parquet(FLOW_DIR / f"{t}.parquet")
        except KiwoomError as e:
            fail += 1
            print(f"[{i}/{n}] {t} 실패: {e}", file=sys.stderr)
            if e.code in (None,) and "JSON" in str(e):
                time.sleep(5)
        except Exception as e:  # noqa: BLE001
            fail += 1
            print(f"[{i}/{n}] {t} 실패: {e}", file=sys.stderr)
        if i % 50 == 0:
            print(f"[{i}/{n}] 진행 중 (실패 {fail})", flush=True)
    n_price = len(list(PRICE_DIR.glob("*.parquet")))
    n_flow = len(list(FLOW_DIR.glob("*.parquet")))
    print(f"수집 완료: 가격 {n_price} / 투자자 {n_flow} 종목. 실패 {fail}")


if __name__ == "__main__":
    main()
