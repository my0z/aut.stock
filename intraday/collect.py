"""분봉 수집기.

history : 키움 분봉 차트 (ka10080) 로 과거 1분봉을 받아 data/minute 에 저장
          유니버스는 KRX 패널로 날짜별 계산한 종목의 합집합
          python -m intraday.collect history --days 60 --top 30
today   : 장 마감 후 오늘 유니버스 종목의 1분봉을 REST 로 받아 저장 (웹소켓 누락 보정)
          python -m intraday.collect today
stream  : 웹소켓 체결을 1분봉으로 묶어 저장 (장중 실행)
          python -m intraday.collect stream --until 15:35
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, time as dtime, timedelta

import pandas as pd

from kiwoom import KiwoomClient, TradeStream
from kiwoom.client import KST

from .bars import BarBuilder, bars_to_frame, save_day
from .universe import kiwoom_universe, panel_universe_union

log = logging.getLogger("collect")


def _save_minute_frame(code: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    out = df.reset_index().rename(columns={"time": "time"})
    out["code"] = code
    out = out[["code", "time", "open", "high", "low", "close", "volume"]]
    n = 0
    for day, g in out.groupby(out["time"].dt.strftime("%Y%m%d")):
        save_day(g, day)
        n += len(g)
    return n


def cmd_history(client: KiwoomClient, days: int, top: int, codes: list[str] | None) -> None:
    end = datetime.now(KST).date()
    start = end - timedelta(days=int(days * 1.5) + 7)
    since = start.strftime("%Y%m%d")
    if codes:
        universe = codes
    else:
        per_day = panel_universe_union(since, end.strftime("%Y%m%d"), top)
        if not per_day:
            print("KRX 패널이 없다. --codes 로 직접 지정하거나 fetch_data.py 를 먼저 실행한다", file=sys.stderr)
            sys.exit(1)
        universe = sorted({c for u in per_day.values() for c in u})
    print(f"{since} 이후 분봉 수집 대상 {len(universe)} 종목")
    max_pages = max(2, days * 400 // 900 + 2)  # 하루 약 390봉 기준
    for i, code in enumerate(universe, 1):
        try:
            df = client.minute_chart(code, tic=1, max_pages=max_pages, since=since)
            n = _save_minute_frame(code, df[df.index >= pd.Timestamp(start)])
            print(f"[{i}/{len(universe)}] {code} {n} 봉", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{len(universe)}] {code} 실패: {e}", file=sys.stderr)


def cmd_today(client: KiwoomClient, top: int, codes: list[str] | None) -> None:
    today = datetime.now(KST).strftime("%Y%m%d")
    universe = codes or kiwoom_universe(client, top)
    for code in universe:
        try:
            df = client.minute_chart(code, tic=1, max_pages=2, since=today)
            n = _save_minute_frame(code, df[df.index >= pd.Timestamp(today)])
            print(f"{code} {n} 봉")
        except Exception as e:  # noqa: BLE001
            print(f"{code} 실패: {e}", file=sys.stderr)


async def cmd_stream(client: KiwoomClient, top: int, until: dtime, codes: list[str] | None) -> None:
    universe = codes or kiwoom_universe(client, top)
    today = datetime.now(KST).strftime("%Y%m%d")
    done = []
    builder = BarBuilder(on_bar=done.append)
    n_ticks = 0

    def on_tick(t):
        nonlocal n_ticks
        n_ticks += 1
        builder.add(t.code, t.ts, t.price, t.volume)
        if len(done) >= 200:
            save_day(bars_to_frame(done), today)
            done.clear()

    stream = TradeStream(client, universe)
    print(f"{len(universe)} 종목 스트림 시작. {until} 까지")
    await stream.run(on_tick, until=until)
    builder.flush()
    if done:
        save_day(bars_to_frame(done), today)
    print(f"종료. 틱 {n_ticks} 건")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["history", "today", "stream"])
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--codes", help="쉼표로 구분한 종목코드. 지정하면 유니버스 계산을 건너뛴다")
    ap.add_argument("--until", default="15:35")
    ap.add_argument("--mode-env", dest="kmode", help="real 또는 demo. 기본은 KIWOOM_MODE")
    a = ap.parse_args()
    client = KiwoomClient(mode=a.kmode)
    codes = [c.strip().zfill(6) for c in a.codes.split(",")] if a.codes else None
    if a.mode == "history":
        cmd_history(client, a.days, a.top, codes)
    elif a.mode == "today":
        cmd_today(client, a.top, codes)
    else:
        asyncio.run(cmd_stream(client, a.top, dtime.fromisoformat(a.until), codes))


if __name__ == "__main__":
    main()
