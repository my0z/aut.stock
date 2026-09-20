"""틱 -> 1분봉 집계와 parquet 저장.

저장 형식: data/minute/YYYYMMDD.parquet
columns: code time open high low close volume  (time 은 봉 시작 시각 KST naive)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from datetime import time as dtime

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MINUTE_DIR = DATA_DIR / "minute"
SESSION_START = dtime(9, 0)
SESSION_END = dtime(15, 30)  # 15:30 봉 (동시호가 체결) 까지 포함


def regular_session(df: pd.DataFrame) -> pd.DataFrame:
    """키움 분봉은 NXT 프리/애프터마켓 (08:00~20:00) 까지 섞여 온다. 정규장 봉만 남긴다."""
    if df.empty:
        return df
    t = pd.to_datetime(df["time"]).dt.time
    return df[(t >= SESSION_START) & (t <= SESSION_END)]


@dataclass
class Bar:
    code: str
    time: datetime  # 봉 시작 (분 단위로 내림)
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class BarBuilder:
    """종목별로 진행 중인 1분봉을 유지하다가 분이 바뀌면 완성된 봉을 콜백으로 넘긴다."""

    on_bar: Callable[[Bar], None] | None = None
    _cur: dict[str, Bar] = field(default_factory=dict)

    def add(self, code: str, ts: datetime, price: float, volume: float) -> Bar | None:
        minute = ts.replace(second=0, microsecond=0, tzinfo=None)
        cur = self._cur.get(code)
        done = None
        if cur is not None and minute > cur.time:
            done = cur
            cur = None
        if cur is None:
            cur = Bar(code, minute, price, price, price, price, 0.0)
            self._cur[code] = cur
        if minute < cur.time:  # 늦게 도착한 틱은 버린다
            return done
        cur.high = max(cur.high, price)
        cur.low = min(cur.low, price)
        cur.close = price
        cur.volume += volume
        if done is not None and self.on_bar:
            self.on_bar(done)
        return done

    def flush(self) -> list[Bar]:
        out = list(self._cur.values())
        self._cur.clear()
        for b in out:
            if self.on_bar:
                self.on_bar(b)
        return out

    def current(self, code: str) -> Bar | None:
        return self._cur.get(code)


def bars_to_frame(bars: list[Bar]) -> pd.DataFrame:
    if not bars:
        return pd.DataFrame(columns=["code", "time", "open", "high", "low", "close", "volume"])
    return pd.DataFrame([b.__dict__ for b in bars])[["code", "time", "open", "high", "low", "close", "volume"]]


def save_day(df: pd.DataFrame, day: str) -> Path:
    """같은 날짜 파일이 있으면 합치고 (code time) 중복은 나중 값으로 덮어쓴다."""
    MINUTE_DIR.mkdir(parents=True, exist_ok=True)
    path = MINUTE_DIR / f"{day}.parquet"
    if path.exists():
        old = pd.read_parquet(path)
        df = pd.concat([old, df], ignore_index=True)
    df = df.drop_duplicates(["code", "time"], keep="last").sort_values(["code", "time"]).reset_index(drop=True)
    df.to_parquet(path, compression="zstd")
    return path


def load_days(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    frames = []
    for p in sorted(MINUTE_DIR.glob("*.parquet")):
        d = p.stem
        if (start and d < start) or (end and d > end):
            continue
        frames.append(pd.read_parquet(p))
    if not frames:
        return pd.DataFrame(columns=["code", "time", "open", "high", "low", "close", "volume"])
    return pd.concat(frames, ignore_index=True)
