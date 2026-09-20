"""데이 단타 후보 종목의 1분봉 수집 (키움 ka10080). 반등이 몇 시에 오는지 보기 위한 데이터.

history : 최근 days 거래일 동안 백테스트 규칙으로 뽑힌 종목 (하루 약 20) 의 그날 1분봉을 받는다.
          (날짜 x 종목) 당 요청 1건. 60일 x 20종목 = 1200 건 = 약 20분 (초당 1건 한도는 클라이언트가 지킨다)
today   : 장 마감 후 오늘 페이퍼/실주문 기록 종목의 1분봉을 받는다 (eval 뒤에 run_daytrade.sh 가 같이 돌린다)

저장: data/daytrade/minute/YYYYMMDD.parquet  columns code time open high low close volume (정규장 09:00~15:30)
읽기: from daytrade.collect import load_minutes; m = load_minutes()

python -m daytrade.collect history --days 60
python -m daytrade.collect today
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, time as dtime
from pathlib import Path

import pandas as pd

from daytrade import data as ddata
from daytrade.backtest import DayParams, run

MINUTE_DIR = ddata.DATA_DIR / "minute"
COLS = ["code", "time", "open", "high", "low", "close", "volume"]
SESSION = (dtime(9, 0), dtime(15, 30))


def regular_session(df: pd.DataFrame) -> pd.DataFrame:
    t = pd.to_datetime(df["time"]).dt.time
    return df[(t >= SESSION[0]) & (t <= SESSION[1])].copy()


def picks_by_day(days: int, p: DayParams | None = None) -> dict[str, list[str]]:
    """백테스트 규칙 (기본 갭 큰 순 30) 으로 뽑힌 날짜별 종목. 최근 days 거래일."""
    w = ddata.load()
    _, trades = run(w, p or DayParams())
    trades["day"] = pd.to_datetime(trades["date"]).dt.strftime("%Y%m%d")
    per_day = {d: sorted(g["ticker"].unique().tolist()) for d, g in trades.groupby("day")}
    return dict(list(per_day.items())[-days:])


def save_day(df: pd.DataFrame, day: str) -> Path:
    MINUTE_DIR.mkdir(parents=True, exist_ok=True)
    path = MINUTE_DIR / f"{day}.parquet"
    if path.exists():
        old = pd.read_parquet(path)
        df = pd.concat([old, df], ignore_index=True).drop_duplicates(["code", "time"], keep="last")
    df = df.sort_values(["code", "time"]).reset_index(drop=True)
    df.to_parquet(path, compression="zstd")
    return path


def load_minutes(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    frames = []
    for p in sorted(MINUTE_DIR.glob("*.parquet")):
        d = p.stem
        if (start and d < start) or (end and d > end):
            continue
        frames.append(pd.read_parquet(p))
    if not frames:
        return pd.DataFrame(columns=COLS)
    return pd.concat(frames, ignore_index=True)


def _fetch_day(client, code: str, day: str) -> pd.DataFrame:
    df = client.minute_chart(code, tic=1, base_dt=day, max_pages=1)
    df = df[df.index.strftime("%Y%m%d") == day]
    if df.empty:
        return df
    out = df.reset_index()
    out["code"] = code
    return regular_session(out[COLS])


def cmd_history(client, days: int) -> None:
    per_day = picks_by_day(days)
    total = sum(len(v) for v in per_day.values())
    print(f"{len(per_day)} 거래일 x 후보 = {total} 건 수집 (약 {total // 60 + 1} 분)")
    done = 0
    for day, codes in per_day.items():
        path = MINUTE_DIR / f"{day}.parquet"
        existing = set(pd.read_parquet(path, columns=["code"])["code"].unique()) if path.exists() else set()
        frames = []
        for code in codes:
            done += 1
            if code in existing:
                continue
            try:
                df = _fetch_day(client, code, day)
                if not df.empty:
                    frames.append(df)
            except Exception as e:  # noqa: BLE001
                print(f"{day} {code} 실패: {e}", file=sys.stderr)
        if frames:
            save_day(pd.concat(frames, ignore_index=True), day)
        print(f"[{done}/{total}] {day} {len(frames)} 종목 저장", flush=True)


def today_codes() -> list[str]:
    from daytrade.live import LOG, PAPER

    today = datetime.now().strftime("%Y-%m-%d")
    codes: set[str] = set()
    for path in (PAPER, LOG):
        if path.exists():
            df = pd.read_csv(path, dtype={"code": str})
            codes |= set(df[(df["date"] == today) & (df["side"] == "buy")]["code"])
    return sorted(codes)


def cmd_today(client) -> None:
    from kiwoom.client import KST

    day = datetime.now(KST).strftime("%Y%m%d")
    codes = today_codes()
    if not codes:
        print("오늘 매수 기록 없음")
        return
    frames = []
    for code in codes:
        try:
            df = _fetch_day(client, code, day)
            if not df.empty:
                frames.append(df)
        except Exception as e:  # noqa: BLE001
            print(f"{code} 실패: {e}", file=sys.stderr)
    if frames:
        p = save_day(pd.concat(frames, ignore_index=True), day)
        print(f"{day} {len(frames)} 종목 저장 -> {p}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["history", "today"])
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--mode-env", dest="kmode")
    a = ap.parse_args()
    from kiwoom import KiwoomClient

    client = KiwoomClient(mode=a.kmode)
    if a.mode == "history":
        cmd_history(client, a.days)
    else:
        cmd_today(client)


if __name__ == "__main__":
    main()
