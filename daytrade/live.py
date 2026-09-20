"""소형주 갭 하락 반등 데이 단타 러너 (시가 매수 -> 15:20 매도).

select : 08:58~08:59 실행. 키움 예상체결등락률 하락 상위 (ka10029) 를 받아 daytrade 감시 목록 (유동성 밴드) 과
         교집합 -> 예상체결가가 전일 종가 대비 gap_max 이하인 종목을 갭 큰 순으로 top 개 고른다
buy    : select 결과를 기록한다. 기본은 페이퍼 (주문 안 냄). --real 이면 장전 시장가 매수 (시가 체결)
sell   : 15:20 실행. --real 이면 보유 전량 시장가 매도 (동시호가 종가 체결). 페이퍼는 아무것도 안 한다
eval   : 15:45 이후 실행. 오늘 페이퍼/실주문 기록에 종가를 채워 수익률을 계산하고 카톡으로 보낸다
status : 잔고

python -m daytrade.live select            # 지금 뭐가 잡히는지 본다 (08:30~09:00 에만 의미 있음)
python -m daytrade.live buy               # 페이퍼 기록
python -m daytrade.live buy --real        # 실주문
python -m daytrade.live eval

키움 필드명이 문서와 다르면 --dump 로 원본 첫 행을 찍어 확인한다.
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

from kiwoom import KiwoomClient
from kiwoom.client import KST, _signed
from notify.kakao import send as kakao

from daytrade import data as ddata
from daytrade.watchlist import build as build_watchlist

log = logging.getLogger("daytrade")
RESULTS = Path(__file__).resolve().parent.parent / "results"
PAPER = RESULTS / "daytrade_paper.csv"
LOG = RESULTS / "daytrade_log.csv"
SHOW = ["name", "exp_price", "close", "gap", "prev_chg_%", "liq20_억"]


def _pick(row: dict, *names: str) -> str:
    """응답 필드명이 문서와 다를 때를 대비해 후보 이름을 순서대로 찾는다."""
    for n in names:
        if n in row and str(row[n]).strip() != "":
            return row[n]
    for n in names:
        for k in row:
            if n in k and str(row[k]).strip() != "":
                return row[k]
    return ""


def expected_drops(client: KiwoomClient, market: str = "000", max_pages: int = 10, dump: bool = False) -> pd.DataFrame:
    """ka10029 예상체결등락률상위 (하락률 순). columns: name exp_price base_price gap (index=code)."""
    body = {"mrkt_tp": market, "sort_tp": "4", "trde_qty_cnd": "0", "stk_cnd": "0", "crd_cnd": "0",
            "pric_cnd": "0", "stex_tp": "1"}
    rows: list[dict] = []
    for page in client.pages("ka10029", "/api/dostk/rkinfo", body, max_pages):
        key = next((k for k, v in page.items() if isinstance(v, list)), None)
        if key:
            rows.extend(page[key])
    if dump and rows:
        print("원본 첫 행:", rows[0])
    if not rows:
        return pd.DataFrame(columns=["name", "exp_price", "base_price", "gap"])
    out = []
    for r in rows:
        code = str(_pick(r, "stk_cd")).replace("A", "")[:6]
        exp = abs(_signed(_pick(r, "exp_cntr_pric", "cur_prc", "pric")))
        base = abs(_signed(_pick(r, "base_pric", "pred_close_pric")))
        rt = _signed(_pick(r, "flu_rt", "exp_cntr_flu_rt"))
        gap = rt / 100.0 if rt else (exp / base - 1 if base else float("nan"))
        if not code or not exp:
            continue
        out.append({"code": code, "name": _pick(r, "stk_nm"), "exp_price": exp, "base_price": base, "gap": gap})
    return pd.DataFrame(out).drop_duplicates("code").set_index("code")


def refresh_snapshot() -> None:
    """panel.parquet 가 스냅샷보다 새로우면 스냅샷을 다시 만든다 (원본은 읽기만)."""
    if not ddata.SNAPSHOT.exists() or ddata.SOURCE.stat().st_mtime > ddata.SNAPSHOT.stat().st_mtime:
        ddata.build()
        log.info("스냅샷 갱신: %s", ddata.info())


def choose(drops: pd.DataFrame, wl: pd.DataFrame, top: int, gap_max: float) -> pd.DataFrame:
    """예상체결 하락 표 x 감시 목록 -> 갭 gap_max 이하 갭 큰 순 top."""
    both = drops.join(wl[["close", "prev_chg_%", "liq20_억", "trigger"]], how="inner")
    # 기준가는 감시 목록의 전일 종가로 다시 계산. 권리락/배당락 조정가로 갭이 크게 보이는 착시를 걸러낸다
    both["gap_vs_close"] = both["exp_price"] / both["close"] - 1
    both["gap"] = both[["gap", "gap_vs_close"]].max(axis=1)
    return both[(both["gap"] <= gap_max) & (both["gap"] >= -0.30)].sort_values("gap").head(top)


def select(client: KiwoomClient, top: int, gap_max: float, dump: bool = False) -> pd.DataFrame:
    refresh_snapshot()
    wl = build_watchlist(ddata.load(), gap_max=gap_max)
    drops = expected_drops(client, dump=dump)
    log.info("감시 목록 %d 종목 (기준일 %s) / 예상체결 하락 %d 종목", len(wl), wl.attrs.get("asof"), len(drops))
    return choose(drops, wl, top, gap_max)


def _append(path: Path, row: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def cmd_buy(client: KiwoomClient, a) -> None:
    now = datetime.now(KST)
    picks = select(client, a.top, a.gap_max, a.dump)
    if picks.empty:
        log.warning("후보 없음")
        kakao(f"[daytrade] {now:%m/%d} 갭 하락 후보 없음")
        return
    capital = a.capital or (client.deposit()["orderable"] if a.real else 10_000_000)
    per = capital / a.top
    print(picks[SHOW].to_string())
    n = 0
    for code, r in picks.iterrows():
        qty = int(math.floor(per / r["exp_price"]))
        if qty <= 0:
            continue
        ord_no = ""
        if a.real:
            try:
                ord_no = client.buy(code, qty)  # 장전 시장가 -> 시가 체결
            except Exception as e:  # noqa: BLE001
                log.error("매수 실패 %s: %s", code, e)
                continue
        _append(LOG if a.real else PAPER, {
            "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"), "code": code, "name": r["name"],
            "side": "buy", "qty": qty, "price": r["exp_price"], "prev_close": r["close"], "gap": round(r["gap"], 4),
            "liq20": round(r["liq20_억"], 2), "ord_no": ord_no,
        })
        n += 1
    log.info("매수 %d 종목 기록 (%s)", n, "실주문" if a.real else "페이퍼")
    head = f"[daytrade] {now:%m/%d} {'실주문' if a.real else '페이퍼'} 갭 하락 매수 {n}종목 (종목당 {per/10000:.0f}만원)"
    body = "\n".join(f"{r['name']} {r['exp_price']:,.0f} 갭{r['gap']*100:+.1f}%" for _, r in picks.iterrows())
    kakao(head + "\n" + body)


def cmd_sell(client: KiwoomClient, a) -> None:
    now = datetime.now(KST)
    if not a.real:
        log.info("페이퍼는 매도 주문 없음. eval 로 종가 평가")
        return
    _, pos = client.balance()
    if pos.empty:
        log.info("보유 없음")
        return
    n = 0
    for r in pos.itertuples(index=False):
        qty = int(r.trde_able_qty if r.trde_able_qty == r.trde_able_qty else r.rmnd_qty)
        if qty <= 0:
            continue
        try:
            ord_no = client.sell(r.stk_cd, qty)  # 15:20 이후 시장가 -> 동시호가 종가 체결
        except Exception as e:  # noqa: BLE001
            log.error("매도 실패 %s: %s", r.stk_cd, e)
            continue
        _append(LOG, {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"), "code": r.stk_cd,
                      "name": r.stk_nm, "side": "sell", "qty": qty, "price": r.cur_prc, "prev_close": "", "gap": "",
                      "liq20": "", "ord_no": ord_no})
        n += 1
    kakao(f"[daytrade] {now:%m/%d} 종가 매도 주문 {n}종목")


def cmd_eval(client: KiwoomClient, a) -> None:
    """오늘 매수 기록에 종가를 채워 수익률을 계산한다 (실주문도 종가 근사)."""
    now = datetime.now(KST)
    path = LOG if a.real else PAPER
    if not path.exists():
        log.info("기록 없음")
        return
    df = pd.read_csv(path, dtype={"code": str})
    if "exit" not in df:
        df["exit"] = float("nan")
        df["ret"] = float("nan")
    today = now.strftime("%Y-%m-%d")
    m = (df["side"] == "buy") & (df["date"] == today) & df["exit"].isna()
    if not m.any():
        log.info("오늘 평가할 포지션 없음")
        return
    closes = {}
    for code in df.loc[m, "code"].unique():
        try:
            d = client.daily_chart(code, base_dt=now.strftime("%Y%m%d"), max_pages=1)
            if not d.empty and d.index[-1].strftime("%Y-%m-%d") == today:
                closes[code] = float(d["close"].iloc[-1])
        except Exception as e:  # noqa: BLE001
            log.warning("%s 종가 조회 실패: %s", code, e)
    m &= df["code"].isin(closes)
    df.loc[m, "exit"] = df.loc[m, "code"].map(closes)
    df.loc[m, "ret"] = df.loc[m, "exit"] / df.loc[m, "price"] - 1 - a.cost_bps / 1e4
    df.to_csv(path, index=False)
    done = df[m]
    if done.empty:
        return
    allp = df[df["ret"].notna()]
    daily = allp.groupby("date")["ret"].mean()
    log.info("오늘 %d 종목 평균 %+.2f%% / 누적 %d 일 일평균 %+.2f%%", len(done), done["ret"].mean() * 100, len(daily), daily.mean() * 100)
    print(done[["code", "name", "price", "exit", "ret"]].to_string())
    best = done.nlargest(3, "ret")
    worst = done.nsmallest(3, "ret")
    kakao(f"[daytrade] {now:%m/%d} 결과 {len(done)}종목 평균 {done['ret'].mean()*100:+.2f}% 승률 {(done['ret']>0).mean()*100:.0f}%\n"
          + "상승: " + " ".join(f"{r['name']} {r['ret']*100:+.1f}%" for _, r in best.iterrows()) + "\n"
          + "하락: " + " ".join(f"{r['name']} {r['ret']*100:+.1f}%" for _, r in worst.iterrows()) + "\n"
          + f"누적 {len(daily)}일 일평균 {daily.mean()*100:+.2f}% 누적 {((1+daily).prod()-1)*100:+.1f}%")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["select", "buy", "sell", "eval", "status"])
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--gap-max", type=float, default=-0.02)
    ap.add_argument("--capital", type=float, default=0.0)
    ap.add_argument("--cost-bps", type=float, default=18.0)
    ap.add_argument("--dump", action="store_true", help="키움 응답 원본 첫 행 출력")
    ap.add_argument("--mode-env", dest="kmode")
    a = ap.parse_args()
    try:
        client = KiwoomClient(mode=a.kmode)
        if a.mode == "select":
            picks = select(client, a.top, a.gap_max, a.dump)
            print(picks[SHOW].to_string() if not picks.empty else "후보 없음")
        elif a.mode == "buy":
            cmd_buy(client, a)
        elif a.mode == "sell":
            cmd_sell(client, a)
        elif a.mode == "eval":
            cmd_eval(client, a)
        else:
            dep = client.deposit()
            summ, pos = client.balance()
            print(f"예수금 {dep['cash']:,.0f} 주문가능 {dep['orderable']:,.0f}")
            if not pos.empty:
                print(pos[["stk_cd", "stk_nm", "rmnd_qty", "pur_pric", "cur_prc", "prft_rt"]].to_string())
    except Exception as e:  # noqa: BLE001
        log.exception("실행 실패")
        kakao(f"[daytrade] {a.mode} 실패: {type(e).__name__}: {str(e)[:150]}")
        raise


if __name__ == "__main__":
    main()
