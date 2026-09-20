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

from .bars import MINUTE_DIR, BarBuilder, bars_to_frame, regular_session, save_day
from .universe import kiwoom_universe, panel_universe_union

log = logging.getLogger("collect")


def _save_minute_frame(code: str, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    out = df.reset_index()
    out["code"] = code
    out = regular_session(out[["code", "time", "open", "high", "low", "close", "volume"]])
    if out.empty:
        return 0
    n = 0
    for day, g in out.groupby(out["time"].dt.strftime("%Y%m%d")):
        save_day(g, day)
        n += len(g)
    return n


def cmd_history(client: KiwoomClient, days: int, top: int, codes: list[str] | None) -> None:
    """최근 days 거래일 동안 날짜별 유니버스 종목의 그날 1분봉을 받는다.

    키움 분봉은 base_dt 기준 최신 900봉이 한 페이지라 하루치 (정규장 381봉 + NXT) 는 한 페이지에 들어온다.
    -> (날짜 x 종목) 당 요청 1건. 60일 x 30종목 = 1800 건 = 약 30분.
    """
    end = datetime.now(KST).date()
    start = end - timedelta(days=int(days * 1.5) + 7)
    since = start.strftime("%Y%m%d")
    if codes:
        per_day = {}
        pn_days = panel_universe_union(since, end.strftime("%Y%m%d"), 1)
        for d in list(pn_days)[-days:]:
            per_day[d] = codes
    else:
        per_day = panel_universe_union(since, end.strftime("%Y%m%d"), top)
        per_day = dict(list(per_day.items())[-days:])
    if not per_day:
        print("KRX 패널이 없다. fetch_data.py 와 pack_data.py 를 먼저 실행한다", file=sys.stderr)
        sys.exit(1)
    total = sum(len(v) for v in per_day.values())
    print(f"{len(per_day)} 거래일 x 유니버스 = {total} 건 수집 (약 {total // 60 + 1} 분)")
    done = 0
    for day, universe in per_day.items():
        existing = set()
        path = MINUTE_DIR / f"{day}.parquet"
        if path.exists():
            existing = set(pd.read_parquet(path, columns=["code"])["code"].unique())
        frames = []
        for code in universe:
            done += 1
            if code in existing:
                continue
            try:
                df = client.minute_chart(code, tic=1, base_dt=day, max_pages=1)
                df = df[df.index.strftime("%Y%m%d") == day]
                if df.empty:
                    continue
                out = df.reset_index()
                out["code"] = code
                frames.append(out[["code", "time", "open", "high", "low", "close", "volume"]])
            except Exception as e:  # noqa: BLE001
                print(f"{day} {code} 실패: {e}", file=sys.stderr)
        if frames:
            merged = regular_session(pd.concat(frames, ignore_index=True))
            save_day(merged, day)
        print(f"[{done}/{total}] {day} {len(frames)} 종목 저장", flush=True)


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
