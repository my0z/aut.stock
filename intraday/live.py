"""ORB 실시간 매매 러너. 기본은 페이퍼 (주문 안 냄). --real 을 주면 키움 계좌로 주문한다.

python -m intraday.live                 # 페이퍼. 체결가는 다음 틱 가격
python -m intraday.live --real          # 실주문 (KIWOOM_MODE=demo 면 모의투자 서버)

장 시작 전(08:30~08:59)에 실행하면 09:00 부터 틱을 받는다. exit_time 이후 전량 청산하고 끝난다.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import math
from dataclasses import dataclass
from datetime import datetime, time as dtime
from pathlib import Path

from kiwoom import KiwoomClient, TradeStream
from kiwoom.client import KST

from .bars import BarBuilder, bars_to_frame, save_day
from .strategy import ORBEngine, ORBParams
from .universe import kiwoom_universe

log = logging.getLogger("live")
RESULTS = Path(__file__).resolve().parent.parent / "results"


@dataclass
class Position:
    code: str
    qty: int
    entry: float
    entry_time: datetime


class Trader:
    def __init__(self, client: KiwoomClient, engine: ORBEngine, capital: float, max_pos: int,
                 real: bool, daily_loss_limit: float):
        self.client, self.eng = client, engine
        self.capital, self.max_pos, self.real = capital, max_pos, real
        self.loss_limit = daily_loss_limit
        self.positions: dict[str, Position] = {}
        self.pending_buy: dict[str, str] = {}   # code -> ord_no ('' 이면 페이퍼)
        self.pending_sell: dict[str, tuple[str, str]] = {}  # code -> (ord_no, reason)
        self.realized = 0.0
        self.halted = False
        RESULTS.mkdir(exist_ok=True)
        self.log_path = RESULTS / f"live_{datetime.now(KST):%Y%m%d}.csv"
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="") as f:
                csv.writer(f).writerow(["time", "code", "side", "qty", "price", "reason", "pnl"])

    def _log(self, code, side, qty, price, reason, pnl=""):
        with open(self.log_path, "a", newline="") as f:
            csv.writer(f).writerow([datetime.now(KST).isoformat(timespec="seconds"), code, side, qty, price, reason, pnl])

    # ----- 진입 -----
    def try_buy(self, code: str, ref_price: float) -> None:
        if self.halted or code in self.positions or code in self.pending_buy:
            self.eng.cancel_entry(code)
            return
        if len(self.positions) + len(self.pending_buy) >= self.max_pos:
            log.info("%s 진입 생략: 최대 보유 %d", code, self.max_pos)
            self.eng.cancel_entry(code)
            return
        qty = int(math.floor(self.capital / self.max_pos / ref_price))
        if qty <= 0:
            self.eng.cancel_entry(code)
            return
        if self.real:
            try:
                ord_no = self.client.buy(code, qty)
            except Exception as e:  # noqa: BLE001
                log.error("매수 주문 실패 %s: %s", code, e)
                self.eng.cancel_entry(code)
                return
            self.pending_buy[code] = ord_no
        else:
            self.pending_buy[code] = ""
        log.info("매수 주문 %s x%d (참고가 %.0f) real=%s", code, qty, ref_price, self.real)
        self._qty_cache = getattr(self, "_qty_cache", {})
        self._qty_cache[code] = qty

    def on_fill_buy(self, code: str, price: float, ts: datetime) -> None:
        qty = self._qty_cache.pop(code, 0)
        self.pending_buy.pop(code, None)
        self.positions[code] = Position(code, qty, price, ts)
        self.eng.mark_entry(code, price)
        self._log(code, "buy", qty, price, "orb_breakout")
        log.info("매수 체결 %s x%d @%.0f 손절 %.0f 익절 %.0f", code, qty, price,
                 self.eng.state[code].stop, self.eng.state[code].tp)

    # ----- 청산 -----
    def try_sell(self, code: str, reason: str) -> None:
        pos = self.positions.get(code)
        if pos is None or code in self.pending_sell:
            return
        if self.real:
            try:
                ord_no = self.client.sell(code, pos.qty)
            except Exception as e:  # noqa: BLE001
                log.error("매도 주문 실패 %s: %s (다음 틱에 재시도)", code, e)
                self.eng.state[code].in_pos = True  # 엔진 상태 복구해 재시도
                self.eng.state[code].done = False
                return
            self.pending_sell[code] = (ord_no, reason)
        else:
            self.pending_sell[code] = ("", reason)

    def on_fill_sell(self, code: str, price: float) -> None:
        _, reason = self.pending_sell.pop(code)
        pos = self.positions.pop(code)
        pnl = (price - pos.entry) * pos.qty
        self.realized += pnl
        self._log(code, "sell", pos.qty, price, reason, f"{pnl:.0f}")
        log.info("매도 체결 %s @%.0f (%s) 손익 %+.0f 누적 %+.0f", code, price, reason, pnl, self.realized)
        if self.realized < -self.loss_limit * self.capital:
            self.halted = True
            log.warning("일일 손실 한도 도달. 신규 진입 중단")

    # ----- 틱 처리 -----
    def on_tick(self, tick) -> None:
        code = tick.code
        # 페이퍼 체결: 주문 다음 틱 가격으로 체결됐다고 본다
        if not self.real:
            if code in self.pending_buy:
                self.on_fill_buy(code, tick.price, tick.ts)
            if code in self.pending_sell:
                self.on_fill_sell(code, tick.price)
        if code in self.positions and code not in self.pending_sell:
            act = self.eng.on_price(code, tick.ts, tick.price)
            if act is not None and act.kind == "sell":
                self.try_sell(code, act.reason)

    def on_bar(self, bar) -> None:
        act = self.eng.on_bar(bar)
        if act is None:
            return
        if act.kind == "buy":
            self.try_buy(bar.code, act.price)
        elif act.kind == "sell":
            self.try_sell(bar.code, act.reason)

    def close_all(self, reason: str = "time") -> None:
        for code in list(self.positions):
            self.eng.state[code].in_pos = False
            self.eng.state[code].done = True
            self.try_sell(code, reason)

    async def poll_fills(self) -> None:
        """실주문 모드: 잔고를 주기적으로 조회해 체결을 반영한다 (주문체결 웹소켓 대신 단순 폴링)."""
        while True:
            await asyncio.sleep(3)
            if not (self.pending_buy or self.pending_sell):
                continue
            try:
                _, pos = self.client.balance()
            except Exception as e:  # noqa: BLE001
                log.warning("잔고 조회 실패: %s", e)
                continue
            held = {r.stk_cd: r for r in pos.itertuples(index=False)} if not pos.empty else {}
            for code in list(self.pending_buy):
                r = held.get(code)
                if r is not None and r.rmnd_qty > 0:
                    self.on_fill_buy(code, float(r.pur_pric), datetime.now(KST))
            for code in list(self.pending_sell):
                r = held.get(code)
                if r is None or r.rmnd_qty == 0:
                    # 체결가는 잔고에 없으므로 현재가 근사. 정확한 손익은 계좌 조회로 확인
                    price = self.eng.state[code].stop if self.pending_sell[code][1] == "stop" else float(r.cur_prc) if r is not None else self.positions[code].entry
                    self.on_fill_sell(code, price)


async def run(a) -> None:
    client = KiwoomClient(mode=a.kmode)
    if a.real:
        dep = client.deposit()
        capital = a.capital or dep["orderable"]
        log.info("주문가능금액 %.0f 원. 운용자본 %.0f 원 (%s)", dep["orderable"], capital, client.mode)
    else:
        capital = a.capital or 10_000_000
        log.info("페이퍼 모드. 가상 자본 %.0f 원", capital)
    p = ORBParams(vol_mult=a.vol_mult, stop_pct=a.stop, tp_pct=a.tp,
                  exit_time=dtime.fromisoformat(a.exit))
    trader = Trader(client, ORBEngine(p), capital, a.max_pos, a.real, a.loss_limit)
    universe = [c.strip().zfill(6) for c in a.codes.split(",")] if a.codes else kiwoom_universe(client, a.top)
    log.info("유니버스 %d: %s", len(universe), " ".join(universe))
    today = datetime.now(KST).strftime("%Y%m%d")
    finished = []
    builder = BarBuilder(on_bar=lambda b: (finished.append(b), trader.on_bar(b)))

    def on_tick(t):
        builder.add(t.code, t.ts, t.price, t.volume)
        trader.on_tick(t)
        if len(finished) >= 300:
            save_day(bars_to_frame(finished), today)
            finished.clear()

    stream = TradeStream(client, universe)
    tasks = [asyncio.create_task(stream.run(on_tick, until=dtime.fromisoformat(a.until)))]
    if a.real:
        tasks.append(asyncio.create_task(trader.poll_fills()))
    await tasks[0]
    trader.close_all("eod")
    if a.real and trader.pending_sell:
        await asyncio.sleep(10)
    for t in tasks[1:]:
        t.cancel()
    builder.flush()
    if finished:
        save_day(bars_to_frame(finished), today)
    log.info("장 종료. 실현손익 %+.0f 원. 기록 %s", trader.realized, trader.log_path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--real", action="store_true", help="실제 주문 전송")
    ap.add_argument("--capital", type=float, default=0.0, help="운용 자본 (원). 0 이면 주문가능금액 또는 페이퍼 1천만")
    ap.add_argument("--max-pos", type=int, default=5)
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--codes")
    ap.add_argument("--vol-mult", type=float, default=1.5)
    ap.add_argument("--stop", type=float, default=0.02)
    ap.add_argument("--tp", type=float, default=0.03)
    ap.add_argument("--exit", default="15:10")
    ap.add_argument("--until", default="15:20")
    ap.add_argument("--loss-limit", type=float, default=0.03, help="일일 손실 한도 (자본 대비)")
    ap.add_argument("--mode-env", dest="kmode")
    a = ap.parse_args()
    asyncio.run(run(a))


if __name__ == "__main__":
    main()
