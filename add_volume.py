"""data/panel.parquet 에 volume (거래량 주) 칸을 채운다. 서버에서 한 번 실행.

1. 서버 캐시 data/price/*.parquet 의 volume 을 옮긴다 (처음 3년 수집 때 같이 받아 둔 값. API 호출 없음)
2. 캐시 이후 날짜는 KRX 에서 날짜별로 받는다 (KRX_ID KRX_PW 필요. 하루 2건)
이후로는 update_daily.py 가 매일 volume 을 같이 붙인다.

python add_volume.py
"""
from __future__ import annotations

import os
import sys
import time

import pandas as pd

from update_daily import DATA_DIR, PANEL

PRICE_DIR = DATA_DIR / "price"


def from_cache() -> pd.Series:
    parts = []
    for p in sorted(PRICE_DIR.glob("*.parquet")):
        try:
            v = pd.read_parquet(p, columns=["volume"])["volume"]
        except Exception:  # noqa: BLE001
            continue
        v.index = pd.to_datetime(v.index).normalize()
        parts.append(pd.DataFrame({"date": v.index, "ticker": p.stem, "volume": v.values}))
    if not parts:
        return pd.Series(dtype=float, name="volume")
    df = pd.concat(parts).drop_duplicates(["date", "ticker"])
    return df.set_index(["date", "ticker"])["volume"].astype(float)


def from_krx(day: pd.Timestamp) -> pd.Series:
    from pykrx import stock

    out = []
    for mkt in ("KOSPI", "KOSDAQ"):
        px = stock.get_market_ohlcv(day.strftime("%Y%m%d"), market=mkt)
        time.sleep(1)
        if px is not None and not px.empty and "거래량" in px.columns:
            out.append(px["거래량"].astype(float))
    if not out:
        return pd.Series(dtype=float)
    s = pd.concat(out)
    s = s[~s.index.duplicated()]
    s.index = pd.MultiIndex.from_product([[day], s.index], names=["date", "ticker"])
    return s


def main() -> None:
    pn = pd.read_parquet(PANEL)
    vol = pd.Series(float("nan"), index=pn.index, name="volume")
    if "volume" in pn:
        vol = pn["volume"].astype(float)
    cache = from_cache()
    print(f"캐시 거래량 {len(cache):,} 행 ({PRICE_DIR})")
    if not cache.empty:
        vol = vol.fillna(cache.reindex(pn.index))
    dates = pn.index.get_level_values("date")
    cover = vol.notna().groupby(dates).mean()
    missing = cover[cover < 0.5].index
    if len(missing):
        if os.environ.get("KRX_ID") and os.environ.get("KRX_PW"):
            print(f"캐시에 없는 {len(missing)} 거래일을 KRX 에서 받는다")
            for d in missing:
                try:
                    s = from_krx(d)
                except Exception as e:  # noqa: BLE001
                    print(f"{d.date()} 실패: {e}", file=sys.stderr)
                    continue
                vol = vol.fillna(s.reindex(pn.index))
                print(f"{d.date()} {len(s)} 종목")
        else:
            print(f"KRX_ID/KRX_PW 없음. 거래량 빈 거래일 {len(missing)} 개는 비워 둔다", file=sys.stderr)
    pn["volume"] = vol
    pn.to_parquet(PANEL, compression="zstd")
    cover = pn["volume"].notna().groupby(dates).mean()
    print(f"저장: {PANEL} 거래량 채움 {pn['volume'].notna().mean()*100:.1f}% "
          f"(거래일 {len(cover)} 중 절반 이상 채운 날 {(cover >= 0.5).sum()}) 마지막 {cover.index.max().date()}")


if __name__ == "__main__":
    main()
