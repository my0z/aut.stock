"""시가 범위 돌파 (Opening Range Breakout) 단타 전략.

선정 근거
- 09:00~09:30 의 고가/저가는 그날 수급이 처음 드러나는 구간이라 이 범위를 거래량을 동반해
  위로 뚫는 종목은 추세가 이어질 확률이 통계적으로 높다 (미국 시장에서 가장 검증이 많이 된 단타 규칙).
- 여기에 전일 기관+외국인 동시 순매수 종목으로 유니버스를 좁혀 수급 배경이 있는 돌파만 취한다.
- 손절과 익절 그리고 시간 청산이 고정돼 있어 하루 최대 손실이 정해진다.

규칙 (기본값)
- 유니버스: 전일 기관과 외국인 모두 순매수 + 거래대금 상위 (universe.py)
- 시가 범위: 09:00 이상 09:30 미만 1분봉의 최고가/최저가와 평균 거래량
- 진입: 09:30 이후 14:00 이전에 1분봉 종가가 범위 고가를 넘고
        그 봉 거래량이 범위 평균 거래량의 vol_mult 배 이상이며 종가가 VWAP 위일 때
        (백테스트는 다음 봉 시가 / 실전은 시장가)
- 손절: max(범위 저가, 진입가 x (1 - stop_pct))
- 익절: 진입가 x (1 + tp_pct)
- 시간 청산: exit_time 봉 종가
- 종목당 하루 1회
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as dtime

from .bars import Bar


@dataclass
class ORBParams:
    or_start: dtime = dtime(9, 0)  # 이전 봉 (NXT 프리마켓) 은 무시
    or_end: dtime = dtime(9, 30)
    entry_end: dtime = dtime(14, 0)
    exit_time: dtime = dtime(15, 10)
    vol_mult: float = 1.5
    stop_pct: float = 0.02
    tp_pct: float = 0.03
    use_vwap: bool = True
    min_or_bars: int = 10  # 시가 범위 구간 최소 봉 수 (데이터 결손 방어)


@dataclass
class Action:
    kind: str  # buy | sell
    code: str
    price: float  # 참고 가격 (백테스트 체결가 기준)
    reason: str
    time: datetime


@dataclass
class DayState:
    or_high: float = 0.0
    or_low: float = float("inf")
    or_vol: float = 0.0
    or_bars: int = 0
    cum_pv: float = 0.0
    cum_v: float = 0.0
    in_pos: bool = False
    pending_entry: bool = False
    entry: float = 0.0
    stop: float = 0.0
    tp: float = 0.0
    done: bool = False  # 오늘 트레이드 끝 (재진입 없음)
    last_day: object = None

    @property
    def vwap(self) -> float:
        return self.cum_pv / self.cum_v if self.cum_v > 0 else float("nan")

    @property
    def avg_or_vol(self) -> float:
        return self.or_vol / self.or_bars if self.or_bars else float("inf")


class ORBEngine:
    """종목별 상태를 들고 봉/틱을 받아 매매 액션을 낸다. 백테스트와 실전이 같은 코드를 쓴다."""

    def __init__(self, p: ORBParams | None = None):
        self.p = p or ORBParams()
        self.state: dict[str, DayState] = {}

    def _st(self, code: str, day) -> DayState:
        st = self.state.get(code)
        if st is None or st.last_day != day:
            st = DayState(last_day=day)
            self.state[code] = st
        return st

    def on_bar(self, bar: Bar) -> Action | None:
        """완성된 1분봉. 진입 시그널과 (백테스트용) 봉 고저 기반 청산을 처리한다."""
        p = self.p
        st = self._st(bar.code, bar.time.date())
        t = bar.time.time()
        if t < p.or_start:
            return None
        st.cum_pv += bar.close * bar.volume
        st.cum_v += bar.volume

        if t < p.or_end:
            st.or_high = max(st.or_high, bar.high)
            st.or_low = min(st.or_low, bar.low)
            st.or_vol += bar.volume
            st.or_bars += 1
            return None

        if st.in_pos:
            # 봉 안에서 손절이 먼저 닿았다고 보수적으로 가정
            if bar.low <= st.stop:
                return self._exit(st, bar, min(bar.open, st.stop), "stop")
            if bar.high >= st.tp:
                return self._exit(st, bar, max(bar.open, st.tp), "tp")
            if t >= p.exit_time:
                return self._exit(st, bar, bar.close, "time")
            return None

        if st.done or st.pending_entry or st.or_bars < p.min_or_bars:
            return None
        if t >= p.entry_end:
            return None
        breakout = bar.close > st.or_high
        vol_ok = bar.volume >= p.vol_mult * st.avg_or_vol
        vwap_ok = (not p.use_vwap) or bar.close > st.vwap
        if breakout and vol_ok and vwap_ok:
            st.pending_entry = True
            return Action("buy", bar.code, bar.close, "orb_breakout", bar.time)
        return None

    def on_price(self, code: str, ts: datetime, price: float) -> Action | None:
        """실전용: 틱마다 손절/익절/시간 청산 확인."""
        st = self.state.get(code)
        if st is None or not st.in_pos:
            return None
        if price <= st.stop:
            return self._exit(st, None, price, "stop", ts, code)
        if price >= st.tp:
            return self._exit(st, None, price, "tp", ts, code)
        if ts.time() >= self.p.exit_time:
            return self._exit(st, None, price, "time", ts, code)
        return None

    def mark_entry(self, code: str, price: float) -> None:
        st = self.state[code]
        st.pending_entry = False
        st.in_pos = True
        st.entry = price
        st.stop = max(st.or_low, price * (1 - self.p.stop_pct))
        st.tp = price * (1 + self.p.tp_pct)

    def cancel_entry(self, code: str) -> None:
        st = self.state[code]
        st.pending_entry = False
        st.done = True

    def _exit(self, st: DayState, bar: Bar | None, price: float, reason: str,
              ts: datetime | None = None, code: str | None = None) -> Action:
        st.in_pos = False
        st.done = True
        return Action("sell", code or bar.code, price, reason, ts or bar.time)


def simulate_day(bars: list[Bar], p: ORBParams, cost_bps: float = 0.0) -> dict | None:
    """한 종목 하루치 1분봉으로 트레이드 1건을 시뮬레이션한다. 진입은 시그널 다음 봉 시가."""
    eng = ORBEngine(p)
    trade: dict | None = None
    for i, bar in enumerate(bars):
        act = eng.on_bar(bar)
        if act is None:
            continue
        if act.kind == "buy":
            if i + 1 >= len(bars):
                eng.cancel_entry(bar.code)
                break
            fill = bars[i + 1].open
            eng.mark_entry(bar.code, fill)
            trade = {"code": bar.code, "day": bar.time.date(), "signal_time": bar.time,
                     "entry_time": bars[i + 1].time, "entry": fill}
        else:
            assert trade is not None
            trade.update({"exit_time": act.time, "exit": act.price, "reason": act.reason,
                          "ret": act.price / trade["entry"] - 1 - cost_bps / 1e4})
            return trade
    if trade is not None and "exit" not in trade:  # 데이터가 끝나 청산 못 함 -> 마지막 종가
        last = bars[-1]
        trade.update({"exit_time": last.time, "exit": last.close, "reason": "eod",
                      "ret": last.close / trade["entry"] - 1 - cost_bps / 1e4})
    return trade
