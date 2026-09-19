"""키움 웹소켓 실시간 체결(0B) 스트림.

- LOGIN -> REG 로 종목 등록 -> REAL 메시지를 Tick 으로 변환해 콜백/큐로 전달
- PING 은 그대로 되돌려 보낸다
- 연결이 끊기면 지수 백오프로 재접속하고 종목을 다시 등록한다
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from typing import Awaitable, Callable, Iterable

import websockets

from .client import KST, KiwoomClient, _num

log = logging.getLogger(__name__)

FID_TIME, FID_PRICE, FID_VOL, FID_ACC_VOL, FID_OPEN, FID_HIGH, FID_LOW = "20", "10", "15", "13", "16", "17", "18"


@dataclass
class Tick:
    code: str
    ts: datetime  # KST
    price: float
    volume: float  # 이번 체결량 (절대값)
    acc_volume: float


def parse_real(msg: dict, today: date | None = None) -> list[Tick]:
    """REAL 프레임 -> Tick 목록. 0B 이외 타입은 무시."""
    if str(msg.get("trnm", "")).upper() != "REAL":
        return []
    today = today or datetime.now(KST).date()
    out = []
    for entry in msg.get("data") or []:
        if str(entry.get("type")) != "0B":
            continue
        v = entry.get("values") or {}
        hms = str(v.get(FID_TIME, "")).zfill(6)
        try:
            t = dtime(int(hms[:2]), int(hms[2:4]), int(hms[4:6]))
        except ValueError:
            continue
        price = _num(v.get(FID_PRICE))
        vol = _num(v.get(FID_VOL))
        if price != price or vol != vol:  # NaN
            continue
        out.append(Tick(
            code=str(entry.get("item", "")).replace("A", "")[:6],
            ts=datetime.combine(today, t, tzinfo=KST),
            price=price,
            volume=vol,
            acc_volume=_num(v.get(FID_ACC_VOL)),
        ))
    return out


class TradeStream:
    def __init__(self, client: KiwoomClient, codes: Iterable[str], grp_no: str = "1"):
        self.client = client
        self.codes = sorted(set(codes))
        self.grp_no = grp_no
        self._ws = None
        self._stop = False

    async def _connect(self):
        self._ws = await websockets.connect(self.client.ws_url, open_timeout=30, ping_interval=None, max_size=2**22)
        await self._ws.send(json.dumps({"trnm": "LOGIN", "token": self.client.token()}))
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=30)
            m = _parse(raw)
            if _is_ping(m):
                await self._ws.send(raw)
                continue
            if isinstance(m, dict) and str(m.get("trnm", "")).upper() == "LOGIN":
                if str(m.get("return_code", "0")) not in ("0", "0000"):
                    raise RuntimeError(f"웹소켓 로그인 실패: {m.get('return_msg')}")
                break
        # 키움은 그룹당 등록 종목 수 제한이 있어 50개씩 나눠 등록한다
        for i in range(0, len(self.codes), 50):
            chunk = self.codes[i:i + 50]
            await self._ws.send(json.dumps({
                "trnm": "REG", "grp_no": self.grp_no, "refresh": "1",
                "data": [{"item": chunk, "type": ["0B"]}],
            }))
        log.info("실시간 등록 %d 종목", len(self.codes))

    async def run(self, on_tick: Callable[[Tick], Awaitable[None] | None], until: dtime | None = None) -> None:
        """until (KST 시각) 까지 틱을 콜백으로 전달. 끊기면 재접속."""
        backoff = 1.0
        while not self._stop:
            try:
                await self._connect()
                backoff = 1.0
                while not self._stop:
                    if until and datetime.now(KST).time() >= until:
                        self._stop = True
                        break
                    try:
                        raw = await asyncio.wait_for(self._ws.recv(), timeout=60)
                    except asyncio.TimeoutError:
                        continue  # 장중 체결이 없을 수도 있다
                    m = _parse(raw)
                    if _is_ping(m):
                        await self._ws.send(raw)
                        continue
                    if not isinstance(m, dict):
                        continue
                    if str(m.get("trnm", "")).upper() == "REAL":
                        for tick in parse_real(m):
                            r = on_tick(tick)
                            if asyncio.iscoroutine(r):
                                await r
                    elif str(m.get("return_code", "0")) not in ("0", "0000"):
                        log.warning("웹소켓 오류 프레임: %s", m)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                if self._stop:
                    break
                log.warning("웹소켓 끊김 (%s). %.0f초 후 재접속", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            finally:
                await self.close()

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None

    def stop(self) -> None:
        self._stop = True


def _parse(raw):
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _is_ping(m) -> bool:
    if isinstance(m, str):
        return m.strip().upper() == "PING"
    return isinstance(m, dict) and str(m.get("trnm", "")).upper() == "PING"
