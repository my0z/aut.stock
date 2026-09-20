"""오버나이트 수급 전략 실전 러너.

buy   : 15:20 께 실행. 키움 장중투자자별매매 (ka10063) 로 기관+외국인 동시 순매수 상위 종목을 뽑아
        동시호가 시장가로 매수 (종가 체결). 기본은 페이퍼 (주문 안 냄). --real 로 실주문
sell  : 다음 거래일 08:35 께 실행. 보유 종목 전량 장전 시장가 매도 (시가 체결)
status: 잔고와 예수금 출력

python -m overnight.live buy            # 페이퍼: 후보와 참고가만 기록
python -m overnight.live buy --real     # 실주문
python -m overnight.live sell --real
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

log = logging.getLogger("overnight")
RESULTS = Path(__file__).resolve().parent.parent / "results"
PAPER = RESULTS / "overnight_paper.csv"
LOG = RESULTS / "overnight_log.csv"


def intraday_flow(client: KiwoomClient, invsr: str, market: str = "000") -> pd.DataFrame:
    """ka10063. invsr 7 기관계 / 6 외국인. 순매수금액 단위 백만원."""
    body = {"mrkt_tp": market, "amt_qty_tp": "1", "invsr": invsr, "frgn_all": "0",
            "smtm_netprps_tp": "0", "stex_tp": "1"}
    rows: list[dict] = []
    for page in client.pages("ka10063", "/api/dostk/mrkcond", body, 10):
        rows.extend(page.get("opmr_invsr_trde") or [])
    if not rows:
        return pd.DataFrame(columns=["code", "name", "price", "chg", "net"])
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "code": df["stk_cd"].astype(str).str.replace("A", "", regex=False).str[:6],
        "name": df["stk_nm"],
        "price": df["cur_prc"].map(_signed).abs(),
        "chg": df["flu_rt"].map(_signed) / 100.0,
        "net": df["netprps_amt"].map(_signed),
    })
    return out.drop_duplicates("code").set_index("code")


def select(client: KiwoomClient, top: int, min_chg: float, min_price: float) -> pd.DataFrame:
    """기관과 외국인 모두 순매수 + 등락률 필터 -> 합계 금액 상위 top."""
    inst = intraday_flow(client, "7")
    frgn = intraday_flow(client, "6")
    both = inst.join(frgn[["net"]].rename(columns={"net": "net_f"}), how="inner")
    both = both.rename(columns={"net": "net_i"})
    both = both[(both["net_i"] > 0) & (both["net_f"] > 0) & (both["chg"] >= min_chg) & (both["price"] >= min_price)]
    both["score"] = both["net_i"] + both["net_f"]
    return both.sort_values("score", ascending=False).head(top)


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
    picks = select(client, a.top, a.min_chg, a.min_price)
    if picks.empty:
        log.warning("후보 없음")
        return
    if a.real:
        capital = a.capital or client.deposit()["orderable"]
    else:
        capital = a.capital or 10_000_000
    per = capital / a.top
    log.info("자본 %.0f 원 / 종목당 %.0f 원 / 후보 %d 종목 (%s)", capital, per, len(picks), "실주문" if a.real else "페이퍼")
    print(picks[["name", "price", "chg", "net_i", "net_f"]].to_string())
    for code, r in picks.iterrows():
        qty = int(math.floor(per / r["price"]))
        if qty <= 0:
            continue
        ord_no = ""
        if a.real:
            try:
                ord_no = client.buy(code, qty)  # 시장가. 15:20 이후면 동시호가 -> 종가 체결
            except Exception as e:  # noqa: BLE001
                log.error("매수 실패 %s: %s", code, e)
                continue
        _append(PAPER if not a.real else LOG, {
            "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"), "code": code, "name": r["name"],
            "side": "buy", "qty": qty, "price": r["price"], "chg": round(r["chg"], 4),
            "net_i": r["net_i"], "net_f": r["net_f"], "ord_no": ord_no,
        })
    log.info("매수 %d 종목 기록", len(picks))
    head = f"[aut.stock] {now:%m/%d} {'실주문' if a.real else '페이퍼'} 매수 {len(picks)}종목 (종목당 {per/10000:.0f}만원)"
    body = "\n".join(f"{r['name']} {r['price']:,.0f} {r['chg']*100:+.1f}%" for _, r in picks.iterrows())
    kakao(head + "\n" + body)


def cmd_sell(client: KiwoomClient, a) -> None:
    now = datetime.now(KST)
    if a.real:
        _, pos = client.balance()
        if pos.empty:
            log.info("보유 종목 없음")
            return
        for r in pos.itertuples(index=False):
            qty = int(r.trde_able_qty if r.trde_able_qty == r.trde_able_qty else r.rmnd_qty)
            if qty <= 0:
                continue
            try:
                ord_no = client.sell(r.stk_cd, qty)  # 장전 시장가 -> 시가 체결
            except Exception as e:  # noqa: BLE001
                log.error("매도 실패 %s: %s", r.stk_cd, e)
                continue
            _append(LOG, {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"), "code": r.stk_cd,
                          "name": r.stk_nm, "side": "sell", "qty": qty, "price": r.cur_prc, "chg": "",
                          "net_i": "", "net_f": "", "ord_no": ord_no})
        log.info("매도 주문 %d 종목", len(pos))
        kakao(f"[aut.stock] {now:%m/%d} 시가 매도 주문 {len(pos)}종목. 결과는 잔고 조회로 확인")
        return
    # 페이퍼: 어제 기록한 후보의 오늘 시가로 평가
    if not PAPER.exists():
        log.info("페이퍼 기록 없음")
        return
    df = pd.read_csv(PAPER, dtype={"code": str})
    open_rows = df[(df["side"] == "buy") & (df.get("exit", pd.Series(dtype=float)).isna() if "exit" in df else True)]
    if open_rows.empty:
        log.info("평가할 페이퍼 포지션 없음")
        return
    today = now.strftime("%Y%m%d")
    exits = {}
    for code in open_rows["code"].unique():
        try:
            d = client.daily_chart(code, base_dt=today, max_pages=1)
            if not d.empty and d.index[-1].strftime("%Y%m%d") == today:
                exits[code] = float(d["open"].iloc[-1])
        except Exception as e:  # noqa: BLE001
            log.warning("%s 시가 조회 실패: %s", code, e)
    if "exit" not in df:
        df["exit"] = float("nan")
        df["ret"] = float("nan")
    m = df["code"].isin(exits) & (df["side"] == "buy") & df["exit"].isna()
    df.loc[m, "exit"] = df.loc[m, "code"].map(exits)
    df.loc[m, "ret"] = df.loc[m, "exit"] / df.loc[m, "price"] - 1 - a.cost_bps / 1e4
    df.to_csv(PAPER, index=False)
    done = df[m]
    if not done.empty:
        log.info("페이퍼 청산 %d 종목: 평균 %+.3f%% 승률 %.0f%%", len(done), done["ret"].mean() * 100, (done["ret"] > 0).mean() * 100)
        print(done[["date", "code", "name", "price", "exit", "ret"]].to_string())
    allp = df[df["ret"].notna()]
    if not allp.empty:
        daily = allp.groupby("date")["ret"].mean()
        log.info("페이퍼 누적: %d 일 일평균 %+.3f%% 일승률 %.0f%% 누적 %+.1f%%", len(daily), daily.mean() * 100,
                 (daily > 0).mean() * 100, ((1 + daily).prod() - 1) * 100)
        if not done.empty:
            best = done.nlargest(3, "ret"); worst = done.nsmallest(3, "ret")
            msg = (f"[aut.stock] {now:%m/%d} 페이퍼 결과 {len(done)}종목 평균 {done['ret'].mean()*100:+.2f}% "
                   f"승률 {(done['ret']>0).mean()*100:.0f}%\n"
                   + "상승: " + " ".join(f"{r['name']} {r['ret']*100:+.1f}%" for _, r in best.iterrows()) + "\n"
                   + "하락: " + " ".join(f"{r['name']} {r['ret']*100:+.1f}%" for _, r in worst.iterrows()) + "\n"
                   + f"누적 {len(daily)}일 일평균 {daily.mean()*100:+.2f}% 누적 {((1+daily).prod()-1)*100:+.1f}%")
            kakao(msg)


def cmd_status(client: KiwoomClient, a) -> None:
    dep = client.deposit()
    summ, pos = client.balance()
    print(f"예수금 {dep['cash']:,.0f} 주문가능 {dep['orderable']:,.0f}")
    print({k: v for k, v in summ.items()})
    if not pos.empty:
        print(pos[["stk_cd", "stk_nm", "rmnd_qty", "pur_pric", "cur_prc", "evltv_prft", "prft_rt"]].to_string())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["buy", "sell", "status", "select"])
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--min-chg", type=float, default=0.03)
    ap.add_argument("--min-price", type=float, default=1000.0)
    ap.add_argument("--capital", type=float, default=0.0)
    ap.add_argument("--cost-bps", type=float, default=18.0)
    ap.add_argument("--mode-env", dest="kmode")
    a = ap.parse_args()
    try:
        client = KiwoomClient(mode=a.kmode)
        if a.mode == "buy":
            cmd_buy(client, a)
        elif a.mode == "sell":
            cmd_sell(client, a)
        elif a.mode == "select":
            print(select(client, a.top, a.min_chg, a.min_price).to_string())
        else:
            cmd_status(client, a)
    except Exception as e:  # noqa: BLE001
        log.exception("실행 실패")
        kakao(f"[aut.stock] {a.mode} 실패: {type(e).__name__}: {str(e)[:150]}")
        raise


if __name__ == "__main__":
    main()
