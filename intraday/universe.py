"""당일 매매 유니버스 선정.

기본: 전일 기관과 외국인이 모두 순매수한 종목 중 거래대금 상위 N.
- 실전/수집: 키움 API (ka10131 연속매매현황 + ka10032 거래대금상위)
- 백테스트: KRX 일별 패널 (data/panel.parquet) 의 inst/foreign 컬럼
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def _n(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.replace("+", ""), errors="coerce")


def kiwoom_universe(client, top: int = 30, min_price: float = 1000.0) -> list[str]:
    """키움 API 로 오늘의 유니버스. 장 시작 전에 호출한다."""
    both: set[str] = set()
    for mkt in ("001", "101"):
        try:
            df = client.investor_streak(mkt, days=1)
        except Exception as e:  # noqa: BLE001
            log.warning("ka10131 %s 실패: %s", mkt, e)
            continue
        if df.empty:
            continue
        org = _n(df["orgn_nettrde_amt"])
        frg = _n(df["frgnr_nettrde_amt"])
        codes = df.loc[(org > 0) & (frg > 0), "stk_cd"].astype(str).str.replace("A", "").str.zfill(6)
        both.update(codes)
    log.info("전일 기관+외국인 동시 순매수 %d 종목", len(both))

    tv = client.trading_value_top("000")
    if tv.empty:
        log.warning("거래대금 상위 조회 실패. 순매수 종목만 사용")
        return sorted(both)[:top]
    tv["code"] = tv["stk_cd"].astype(str).str.replace("A", "").str.zfill(6)
    tv["price"] = _n(tv["cur_prc"]).abs()
    tv["value"] = _n(tv["trde_prica"])
    tv = tv[tv["price"] >= min_price].drop_duplicates("code")
    ranked = tv.sort_values("value", ascending=False)
    picked = ranked[ranked["code"].isin(both)]["code"].tolist() if both else []
    if len(picked) < top:  # 순매수 조건이 비었거나 부족하면 거래대금 순으로 채운다
        extra = [c for c in ranked["code"] if c not in picked]
        picked += extra[: top - len(picked)]
    return picked[:top]


def panel_universe(day: str, top: int = 30, min_price: float = 1000.0) -> list[str]:
    """백테스트용: KRX 패널에서 day 의 직전 거래일에 기관+외국인 동시 순매수한 종목.

    거래대금이 패널에 없어 순매수 금액 합계 순으로 top 을 자른다.
    """
    pn = _load_panel()
    if pn is None:
        return []
    days = pn.index.get_level_values("date").unique().sort_values()
    prev = days[days < pd.Timestamp(day)]
    if len(prev) == 0:
        return []
    d = pn.xs(prev[-1], level="date")
    d = d[(d["inst"] > 0) & (d["foreign"] > 0) & (d["close"] >= min_price)]
    d = d.assign(score=d["inst"] + d["foreign"]).sort_values("score", ascending=False)
    return d.index[:top].tolist()


def panel_universe_union(start: str, end: str, top: int = 30) -> dict[str, list[str]]:
    """start~end 각 거래일의 유니버스를 dict[day] 로 돌려준다."""
    pn = _load_panel()
    if pn is None:
        return {}
    days = pn.index.get_level_values("date").unique().sort_values()
    days = days[(days >= pd.Timestamp(start)) & (days <= pd.Timestamp(end))]
    return {d.strftime("%Y%m%d"): panel_universe(d.strftime("%Y%m%d"), top) for d in days}


_PANEL: pd.DataFrame | None = None


def _load_panel() -> pd.DataFrame | None:
    global _PANEL
    if _PANEL is None:
        path = DATA_DIR / "panel.parquet"
        if not path.exists():
            log.warning("%s 없음. 먼저 fetch_data.py 와 pack_data.py 를 실행한다", path)
            return None
        _PANEL = pd.read_parquet(path)
    return _PANEL
