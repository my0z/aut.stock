"""KRX 데이터 수집 (pykrx 기반).

수집 항목
- 종목별 일봉 OHLCV
- 종목별 투자자 순매수 금액 (기관합계 / 외국인합계)

결과는 data/ 아래 parquet 로 캐시된다. 이미 받은 종목은 건너뛴다.
KRX 데이터포털 로그인이 필요한 pykrx 버전에서는 KRX_ID / KRX_PW 환경변수를 설정한다.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from pykrx import stock

DATA_DIR = Path(__file__).resolve().parent / "data"
PRICE_DIR = DATA_DIR / "price"
FLOW_DIR = DATA_DIR / "flow"


def _yyyymmdd(d: date) -> str:
    return d.strftime("%Y%m%d")


def default_range(years: int = 3) -> tuple[str, str]:
    today = date.today()
    start = today - timedelta(days=365 * years)
    return _yyyymmdd(start), _yyyymmdd(today)


def ticker_universe(asof: str, markets: tuple[str, ...] = ("KOSPI", "KOSDAQ")) -> list[str]:
    tickers: list[str] = []
    for m in markets:
        tickers += stock.get_market_ticker_list(asof, market=m)
    return sorted(set(tickers))


def _retry(fn, *args, tries: int = 4, sleep: float = 1.5, **kwargs):
    last = None
    for i in range(tries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(sleep * (2**i))
    raise RuntimeError(f"failed after {tries} tries: {last}")


def fetch_price(ticker: str, start: str, end: str) -> pd.DataFrame:
    df = _retry(stock.get_market_ohlcv, start, end, ticker)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.rename(columns={"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"})
    df.index.name = "date"
    return df[["open", "high", "low", "close", "volume"]]


def fetch_flow(ticker: str, start: str, end: str) -> pd.DataFrame:
    df = _retry(stock.get_market_trading_value_by_date, start, end, ticker)
    if df is None or df.empty:
        return pd.DataFrame()
    cols = {"기관합계": "inst", "외국인합계": "foreign", "개인": "indiv"}
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise KeyError(f"{ticker}: 투자자 컬럼 누락 {missing} / 실제 컬럼 {list(df.columns)}")
    df = df.rename(columns=cols)
    df.index.name = "date"
    return df[["inst", "foreign", "indiv"]]


def fetch_all(start: str, end: str, tickers: list[str], sleep: float = 0.3) -> None:
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    FLOW_DIR.mkdir(parents=True, exist_ok=True)
    n = len(tickers)
    for i, t in enumerate(tickers, 1):
        p_path = PRICE_DIR / f"{t}.parquet"
        f_path = FLOW_DIR / f"{t}.parquet"
        if p_path.exists() and f_path.exists():
            continue
        try:
            if not p_path.exists():
                px = fetch_price(t, start, end)
                if not px.empty:
                    px.to_parquet(p_path)
                time.sleep(sleep)
            if not f_path.exists():
                fl = fetch_flow(t, start, end)
                if not fl.empty:
                    fl.to_parquet(f_path)
                time.sleep(sleep)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{n}] {t} 실패: {e}", file=sys.stderr)
            continue
        if i % 50 == 0:
            print(f"[{i}/{n}] 진행 중", flush=True)
    print("수집 완료")


def load_panel() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """캐시를 읽어 (open close inst foreign) 와이드 패널을 돌려준다. index=date columns=ticker.

    data/panel.parquet (pack_data.py 결과) 가 있으면 그것을 우선 읽는다.
    """
    packed = DATA_DIR / "panel.parquet"
    if packed.exists():
        pn = pd.read_parquet(packed)
        wide = {c: pn[c].unstack("ticker").sort_index() for c in ["open", "close", "inst", "foreign"]}
        return wide["open"], wide["close"], wide["inst"], wide["foreign"]
    opens, closes, insts, foreigns = {}, {}, {}, {}
    for p_path in sorted(PRICE_DIR.glob("*.parquet")):
        t = p_path.stem
        f_path = FLOW_DIR / f"{t}.parquet"
        if not f_path.exists():
            continue
        px = pd.read_parquet(p_path)
        fl = pd.read_parquet(f_path)
        opens[t] = px["open"]
        closes[t] = px["close"]
        insts[t] = fl["inst"]
        foreigns[t] = fl["foreign"]
    O = pd.DataFrame(opens).sort_index()
    C = pd.DataFrame(closes).sort_index()
    I = pd.DataFrame(insts).reindex(C.index)
    F = pd.DataFrame(foreigns).reindex(C.index)
    return O, C, I, F


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--markets", default="KOSPI,KOSDAQ")
    ap.add_argument("--limit", type=int, default=0, help="테스트용 종목 수 제한")
    ap.add_argument("--sleep", type=float, default=0.3)
    a = ap.parse_args()
    start, end = default_range(a.years)
    start = a.start or start
    end = a.end or end
    if not (os.environ.get("KRX_ID") and os.environ.get("KRX_PW")):
        print("경고: KRX_ID / KRX_PW 미설정. 최신 pykrx 는 KRX 로그인이 필요할 수 있다.", file=sys.stderr)
    tickers = ticker_universe(end, tuple(a.markets.split(",")))
    if a.limit:
        tickers = tickers[: a.limit]
    print(f"기간 {start}~{end} 종목 {len(tickers)}개")
    fetch_all(start, end, tickers, sleep=a.sleep)


if __name__ == "__main__":
    main()
