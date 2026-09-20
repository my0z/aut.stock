"""키움 REST 클라이언트.

환경변수
- KIWOOM_MODE      real | demo (기본 demo)
- KIWOOM_APPKEY    앱키
- KIWOOM_SECRET    시크릿
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pandas as pd
import requests

log = logging.getLogger(__name__)
KST = timezone(timedelta(hours=9))

BASE_URLS = {"real": "https://api.kiwoom.com", "demo": "https://mockapi.kiwoom.com"}
WS_URLS = {"real": "wss://api.kiwoom.com:10000", "demo": "wss://mockapi.kiwoom.com:10000"}
AUTH_RETRY_CODES = {8005, 8031, 8103}
RATE_LIMIT_CODE = 1700  # 허용된 API 요청 개수 초과 (초당 1건)


class KiwoomError(RuntimeError):
    def __init__(self, code: int | None, msg: str):
        super().__init__(f"[{code}] {msg}" if code is not None else msg)
        self.code = code
        self.msg = msg


@dataclass
class Page:
    body: dict
    cont_yn: str
    next_key: str


def _num(v: Any) -> float:
    """키움 숫자 문자열 ('+1,234' '-56' '') -> float. 부호는 등락 표시일 뿐이라 절대값을 쓴다."""
    if v is None:
        return float("nan")
    s = str(v).strip().replace(",", "")
    if s in ("", "+", "-"):
        return float("nan")
    return abs(float(s))


def _signed(v: Any) -> float:
    if v is None:
        return float("nan")
    s = str(v).strip().replace(",", "")
    if s in ("", "+", "-"):
        return float("nan")
    return float(s)


class KiwoomClient:
    def __init__(self, mode: str | None = None, appkey: str | None = None, secret: str | None = None,
                 timeout: int = 30, min_interval: float = 1.0):
        self.mode = (mode or os.environ.get("KIWOOM_MODE") or "demo").lower()
        if self.mode not in BASE_URLS:
            raise ValueError("KIWOOM_MODE 는 real 또는 demo")
        self.appkey = appkey or os.environ.get("KIWOOM_APPKEY", "")
        self.secret = secret or os.environ.get("KIWOOM_SECRET", "")
        if not (self.appkey and self.secret):
            raise KiwoomError(None, "KIWOOM_APPKEY / KIWOOM_SECRET 환경변수가 필요하다")
        self.base = BASE_URLS[self.mode]
        self.ws_url = WS_URLS[self.mode] + "/api/dostk/websocket"
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_call = 0.0
        self._token: str | None = None
        self._token_exp: datetime | None = None
        self.sess = requests.Session()

    # ---------- 인증 ----------
    def token(self) -> str:
        now = datetime.now(KST)
        if self._token and self._token_exp and now < self._token_exp - timedelta(minutes=10):
            return self._token
        r = self.sess.post(
            f"{self.base}/oauth2/token",
            json={"grant_type": "client_credentials", "appkey": self.appkey, "secretkey": self.secret},
            headers={"Content-Type": "application/json;charset=UTF-8"},
            timeout=self.timeout,
        )
        data = r.json() if r.content else {}
        code = _code(data.get("return_code"))
        if r.status_code >= 400 or code not in (None, 0):
            raise KiwoomError(code, str(data.get("return_msg", f"HTTP {r.status_code}")))
        self._token = data["token"]
        self._token_exp = datetime.strptime(data["expires_dt"], "%Y%m%d%H%M%S").replace(tzinfo=KST)
        log.info("키움 토큰 발급 (%s) 만료 %s", self.mode, self._token_exp)
        return self._token

    def _throttle(self) -> None:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    # ---------- 공통 호출 ----------
    def call(self, api_id: str, path: str, body: dict | None = None,
             cont_yn: str | None = None, next_key: str | None = None, _retry: bool = True,
             _rate_tries: int = 5) -> Page:
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "api-id": api_id,
            "authorization": f"Bearer {self.token()}",
        }
        if cont_yn:
            headers["cont-yn"] = cont_yn
        if next_key:
            headers["next-key"] = next_key
        self._throttle()
        r = self.sess.post(f"{self.base}{path}", headers=headers, json=body or {}, timeout=self.timeout)
        try:
            data = r.json()
        except ValueError:
            raise KiwoomError(None, f"{api_id} 응답이 JSON 이 아님 (HTTP {r.status_code}): {r.text[:200]}")
        code = _code(data.get("return_code"))
        embedded = _embedded_code(data.get("return_msg"))
        if _retry and (r.status_code == 401 or code in AUTH_RETRY_CODES or embedded in AUTH_RETRY_CODES):
            self._token = None
            return self.call(api_id, path, body, cont_yn, next_key, _retry=False)
        if embedded == RATE_LIMIT_CODE or code == RATE_LIMIT_CODE:
            if _rate_tries <= 0:
                raise KiwoomError(RATE_LIMIT_CODE, str(data.get("return_msg", "요청 한도 초과")))
            wait = 1.0 * (6 - _rate_tries)
            log.info("%s 요청 한도 초과. %.0f초 대기 후 재시도", api_id, wait)
            time.sleep(wait)
            return self.call(api_id, path, body, cont_yn, next_key, _retry, _rate_tries - 1)
        if r.status_code >= 400 or code not in (None, 0):
            raise KiwoomError(code, str(data.get("return_msg", f"HTTP {r.status_code}")))
        return Page(data, r.headers.get("cont-yn", "N"), r.headers.get("next-key", ""))

    def pages(self, api_id: str, path: str, body: dict, max_pages: int = 10) -> Iterator[dict]:
        cont, key = None, None
        for _ in range(max_pages):
            p = self.call(api_id, path, body, cont, key)
            yield p.body
            if p.cont_yn != "Y":
                return
            cont, key = "Y", p.next_key

    # ---------- 시세 / 차트 ----------
    def minute_chart(self, code: str, tic: int = 1, base_dt: str | None = None,
                     max_pages: int = 5, since: str | None = None) -> pd.DataFrame:
        """ka10080 분봉. 최신순으로 내려오는 것을 시간순으로 뒤집어 돌려준다.

        since: 'YYYYMMDD' 이전 봉이 나오면 페이징을 멈춘다.
        """
        body = {"stk_cd": code, "tic_scope": str(tic), "upd_stkpc_tp": "1"}
        if base_dt:
            body["base_dt"] = base_dt
        rows: list[dict] = []
        for page in self.pages("ka10080", "/api/dostk/chart", body, max_pages):
            recs = page.get("stk_min_pole_chart_qry") or []
            rows.extend(recs)
            if since and recs and str(recs[-1].get("cntr_tm", ""))[:8] < since:
                break
        return _chart_frame(rows, "cntr_tm", "%Y%m%d%H%M%S")

    def daily_chart(self, code: str, base_dt: str | None = None, max_pages: int = 2) -> pd.DataFrame:
        body = {"stk_cd": code, "upd_stkpc_tp": "1", "base_dt": base_dt or datetime.now(KST).strftime("%Y%m%d")}
        rows: list[dict] = []
        for page in self.pages("ka10081", "/api/dostk/chart", body, max_pages):
            rows.extend(page.get("stk_dt_pole_chart_qry") or [])
        df = _chart_frame(rows, "dt", "%Y%m%d")
        if not df.empty and "trde_prica" in df.columns:
            df["value"] = df["trde_prica"].map(_num) * 1e6  # 단위 백만원
        return df

    def investor_daily(self, code: str, since: str, base_dt: str | None = None, max_pages: int = 20) -> pd.DataFrame:
        """ka10059 종목별 투자자 일별 순매수 금액. since (YYYYMMDD) 까지 거슬러 페이징한다.

        반환 columns: inst foreign indiv (기관계 / 외국인 / 개인) index=date. 단위는 키움 응답 그대로.
        """
        body = {"dt": base_dt or datetime.now(KST).strftime("%Y%m%d"), "stk_cd": code,
                "amt_qty_tp": "1", "trde_tp": "0", "unit_tp": "1"}
        rows: list[dict] = []
        for page in self.pages("ka10059", "/api/dostk/stkinfo", body, max_pages):
            recs = page.get("stk_invsr_orgn") or next((v for v in page.values() if isinstance(v, list)), [])
            rows.extend(recs)
            if recs and str(recs[-1].get("dt", ""))[:8] <= since:
                break
        if not rows:
            return pd.DataFrame(columns=["inst", "foreign", "indiv"])
        df = pd.DataFrame(rows)
        out = pd.DataFrame({
            "inst": df["orgn"].map(_signed),
            "foreign": df["frgnr_invsr"].map(_signed),
            "indiv": df["ind_invsr"].map(_signed),
        })
        out.index = pd.to_datetime(df["dt"].astype(str).str[:8], format="%Y%m%d")
        out.index.name = "date"
        out = out[~out.index.duplicated(keep="first")].sort_index()
        return out[out.index >= pd.Timestamp(since)]

    def stock_list(self, market: str) -> pd.DataFrame:
        """ka10099 종목 리스트. market: '0' 코스피 '10' 코스닥."""
        rows: list[dict] = []
        for page in self.pages("ka10099", "/api/dostk/stkinfo", {"mrkt_tp": market}, 20):
            rows.extend(page.get("list") or [])
        return pd.DataFrame(rows)

    def investor_streak(self, market: str, days: int = 1, amount: bool = True) -> pd.DataFrame:
        """ka10131 기관외국인 연속 순매수 현황. market '001' 코스피 '101' 코스닥."""
        body = {
            "dt": str(days), "mrkt_tp": market, "netslmt_tp": "2", "stk_inds_tp": "0",
            "amt_qty_tp": "0" if amount else "1", "stex_tp": "1", "strt_dt": "", "end_dt": "",
        }
        rows: list[dict] = []
        for page in self.pages("ka10131", "/api/dostk/frgnistt", body, 10):
            key = next((k for k, v in page.items() if isinstance(v, list)), None)
            if key:
                rows.extend(page[key])
        return pd.DataFrame(rows)

    def trading_value_top(self, market: str = "000") -> pd.DataFrame:
        """ka10032 거래대금 상위. market '000' 전체 '001' 코스피 '101' 코스닥."""
        body = {"mrkt_tp": market, "mang_stk_incls": "0", "stex_tp": "1"}
        rows: list[dict] = []
        for page in self.pages("ka10032", "/api/dostk/rkinfo", body, 3):
            key = next((k for k, v in page.items() if isinstance(v, list)), None)
            if key:
                rows.extend(page[key])
        return pd.DataFrame(rows)

    # ---------- 계좌 ----------
    def deposit(self) -> dict:
        p = self.call("kt00001", "/api/dostk/acnt", {"qry_tp": "3"})
        b = p.body
        return {"cash": _num(b.get("entr")), "orderable": _num(b.get("ord_alow_amt")), "raw": b}

    def balance(self) -> tuple[dict, pd.DataFrame]:
        p = self.call("kt00018", "/api/dostk/acnt", {"qry_tp": "1", "dmst_stex_tp": "KRX"})
        b = p.body
        summary = {k: _signed(b.get(k)) for k in ("tot_pur_amt", "tot_evlt_amt", "tot_evlt_pl", "tot_prft_rt", "prsm_dpst_aset_amt")}
        pos = pd.DataFrame(b.get("acnt_evlt_remn_indv_tot") or [])
        if not pos.empty:
            pos["stk_cd"] = pos["stk_cd"].astype(str).str.replace("A", "", regex=False).str.zfill(6)
            for c in ("rmnd_qty", "trde_able_qty", "pur_pric", "cur_prc", "evltv_prft", "prft_rt"):
                if c in pos:
                    pos[c] = pos[c].map(_signed)
        return summary, pos

    def unfilled(self) -> pd.DataFrame:
        p = self.call("ka10075", "/api/dostk/acnt", {"all_stk_tp": "0", "trde_tp": "0", "stex_tp": "1", "stk_cd": ""})
        key = next((k for k, v in p.body.items() if isinstance(v, list)), None)
        return pd.DataFrame(p.body.get(key) or []) if key else pd.DataFrame()

    # ---------- 주문 ----------
    def buy(self, code: str, qty: int, price: int | None = None) -> str:
        return self._order("kt10000", code, qty, price)

    def sell(self, code: str, qty: int, price: int | None = None) -> str:
        return self._order("kt10001", code, qty, price)

    def cancel(self, orig_ord_no: str, code: str, qty: int = 0) -> str:
        body = {"dmst_stex_tp": "KRX", "orig_ord_no": orig_ord_no, "stk_cd": code, "cncl_qty": str(qty)}
        return str(self.call("kt10003", "/api/dostk/ordr", body).body.get("ord_no", ""))

    def _order(self, api_id: str, code: str, qty: int, price: int | None) -> str:
        body = {
            "dmst_stex_tp": "KRX", "stk_cd": code, "ord_qty": str(int(qty)),
            "trde_tp": "0" if price else "3",  # 0 지정가 3 시장가
            "ord_uv": str(int(price)) if price else "", "cond_uv": "",
        }
        p = self.call(api_id, "/api/dostk/ordr", body)
        ord_no = str(p.body.get("ord_no", ""))
        log.info("주문 %s %s qty=%s price=%s -> ord_no=%s", api_id, code, qty, price, ord_no)
        return ord_no


def _code(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(str(v).strip())
    except ValueError:
        return None


def _embedded_code(msg: Any) -> int | None:
    """return_msg 가 '[8005:...]' 형태로 실제 코드를 품는 경우."""
    s = str(msg or "")
    i = s.find("[")
    if i >= 0 and ":" in s[i:]:
        try:
            return int(s[i + 1:s.index(":", i)])
        except ValueError:
            return None
    return None


def _chart_frame(rows: list[dict], tcol: str, fmt: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "open": df["open_pric"].map(_num),
        "high": df["high_pric"].map(_num),
        "low": df["low_pric"].map(_num),
        "close": df["cur_prc"].map(_num),
        "volume": df["trde_qty"].map(_num),
    })
    if "trde_prica" in df.columns:
        out["trde_prica"] = df["trde_prica"]
    out.index = pd.to_datetime(df[tcol].astype(str), format=fmt)
    out.index.name = "time"
    out = out[~out.index.duplicated(keep="first")].sort_index()
    return out
