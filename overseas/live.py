"""미국주식 오버나이트 러너 (실험 단계).

국내 전략과 달리 기관/외국인 수급 데이터가 없어 '당일 등락률 상위' 를 대체 신호로 쓴다.
아직 실데이터 백테스트가 없다. overseas/backtest.py 로 먼저 검증한 뒤 페이퍼로 돌린다.

buy   : 미국 장 마감 10분 전 (15:50 America/New_York) 실행. 당일 등락률 상위 종목을 LOC(종가지정가)
        로 매수 (페이퍼 기본, --real 로 실주문)
sell  : 다음 장 개장 직후 (09:31 America/New_York) 실행. 보유 종목 시장가 전량 매도
select: 지금 후보 확인

python -m overseas.live buy
python -m overseas.live sell
python -m overseas.live buy --real
"""
from __future__ import annotations

import argparse
import csv
import logging
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from kiwoom import KiwoomClient
from notify.kakao import send as kakao

log = logging.getLogger("overseas")
RESULTS = Path(__file__).resolve().parent.parent / "results"
PAPER = RESULTS / "overseas_paper.csv"
LOG = RESULTS / "overseas_log.csv"
ET = ZoneInfo("America/New_York")


def select(client: KiwoomClient, top: int, min_chg: float, min_price: float) -> pd.DataFrame:
    df = client.us_price_surge(exch="0", flu_tp="1", tm_tp="2", tm="1")
    if df.empty:
        return df
    m = (df["chg"] >= min_chg) & (df["price"] >= min_price)
    return df[m].sort_values("chg", ascending=False).head(top)


def _append(path: Path, row: dict) -> None:
    RESULTS.mkdir(exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def cmd_buy(client: KiwoomClient, a) -> None:
    now = datetime.now(ET)
    picks = select(client, a.top, a.min_chg, a.min_price)
    if picks.empty:
        log.warning("후보 없음")
        kakao(f"[aut.stock-us] {now:%m/%d} 후보 없음")
        return
    if a.real:
        dep = client.us_deposit()
        capital = a.capital or dep["orderable"]
    else:
        capital = a.capital or 10_000.0  # USD
    per = capital / a.top
    log.info("자본 $%.0f / 종목당 $%.0f / 후보 %d 종목 (%s)", capital, per, len(picks), "실주문" if a.real else "페이퍼")
    print(picks[["name", "stex_tp", "price", "chg"]].to_string())
    for code, r in picks.iterrows():
        qty = int(math.floor(per / r["price"]))
        if qty <= 0:
            continue
        ord_no = ""
        if a.real:
            try:
                ord_no = client.buy_us(code, qty, r["stex_tp"], price=r["price"] * 1.05, order_type="30")
            except Exception as e:  # noqa: BLE001
                log.error("매수 실패 %s: %s", code, e)
                continue
        _append(PAPER, {
            "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"), "code": code, "name": r["name"],
            "exch": r["stex_tp"], "side": "buy", "qty": qty, "price": r["price"], "chg": round(r["chg"], 4),
            "ord_no": ord_no, "exit": "", "ret": "",
        })
    log.info("매수 %d 종목 기록", len(picks))
    head = f"[aut.stock-us] {now:%m/%d} {'실주문' if a.real else '페이퍼'} 매수 {len(picks)}종목 (종목당 ${per:.0f})"
    body = "\n".join(f"{r['name']} ${r['price']:,.2f} {r['chg']*100:+.1f}%" for _, r in picks.iterrows())
    kakao(head + "\n" + body)


def cmd_sell(client: KiwoomClient, a) -> None:
    now = datetime.now(ET)
    if a.real:
        pos = client.us_balance()
        if pos.empty:
            log.info("보유 종목 없음")
            return
        for r in pos.itertuples(index=False):
            qty = int(r.sell_alowq if r.sell_alowq == r.sell_alowq else r.poss_qty)
            if qty <= 0:
                continue
            try:
                ord_no = client.sell_us(r.stk_cd, qty, r.stex_tp, order_type="03")
            except Exception as e:  # noqa: BLE001
                log.error("매도 실패 %s: %s", r.stk_cd, e)
                continue
            _append(LOG, {"date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"), "code": r.stk_cd,
                          "name": getattr(r, "frgn_stk_nm", r.stk_cd), "side": "sell", "qty": qty, "ord_no": ord_no})
        log.info("매도 주문 %d 종목", len(pos))
        kakao(f"[aut.stock-us] {now:%m/%d} 시장가 매도 주문 {len(pos)}종목")
        return
    if not PAPER.exists():
        log.info("페이퍼 기록 없음")
        return
    df = pd.read_csv(PAPER, dtype={"code": str})
    df["exit"] = pd.to_numeric(df.get("exit"), errors="coerce")
    df["ret"] = pd.to_numeric(df.get("ret"), errors="coerce")
    open_rows = df[(df["side"] == "buy") & df["exit"].isna()]
    if open_rows.empty:
        log.info("평가할 페이퍼 포지션 없음")
        return
    today = now.strftime("%Y%m%d")
    exits = {}
    for _, row in open_rows.drop_duplicates("code").iterrows():
        try:
            d = client.us_daily_chart(row["code"], exch=row["exch"], start=today, max_pages=1)
            if not d.empty and d.index[-1].strftime("%Y%m%d") == today:
                exits[row["code"]] = float(d["open"].iloc[-1])
        except Exception as e:  # noqa: BLE001
            log.warning("%s 시가 조회 실패: %s", row["code"], e)
    m = df["code"].isin(exits) & (df["side"] == "buy") & df["exit"].isna()
    df.loc[m, "exit"] = df.loc[m, "code"].map(exits)
    df.loc[m, "ret"] = df.loc[m, "exit"] / df.loc[m, "price"] - 1 - a.cost_bps / 1e4
    df.to_csv(PAPER, index=False)
    done = df[m]
    allp = df[df["ret"].notna()]
    if not done.empty:
        log.info("페이퍼 청산 %d 종목: 평균 %+.3f%% 승률 %.0f%%", len(done), done["ret"].mean() * 100, (done["ret"] > 0).mean() * 100)
        print(done[["date", "code", "name", "price", "exit", "ret"]].to_string())
    if not allp.empty:
        daily = allp.groupby("date")["ret"].mean()
        best = done.nlargest(3, "ret") if not done.empty else done
        worst = done.nsmallest(3, "ret") if not done.empty else done
        msg = (f"[aut.stock-us] {now:%m/%d} 페이퍼 결과 {len(done)}종목 평균 {done['ret'].mean()*100:+.2f}% "
               f"승률 {(done['ret']>0).mean()*100:.0f}%\n" if not done.empty else f"[aut.stock-us] {now:%m/%d} 평가할 포지션 없음\n")
        if not done.empty:
            msg += ("상승: " + " ".join(f"{r['name']} {r['ret']*100:+.1f}%" for _, r in best.iterrows()) + "\n"
                   + "하락: " + " ".join(f"{r['name']} {r['ret']*100:+.1f}%" for _, r in worst.iterrows()) + "\n")
        msg += f"누적 {len(daily)}일 일평균 {daily.mean()*100:+.2f}% 누적 {((1+daily).prod()-1)*100:+.1f}%"
        kakao(msg)


def cmd_status(client: KiwoomClient, a) -> None:
    dep = client.us_deposit()
    print(f"외화예수금 ${dep['cash']:,.2f} 주문가능 ${dep['orderable']:,.2f}")
    pos = client.us_balance()
    if not pos.empty:
        print(pos[["stk_cd", "frgn_stk_nm", "poss_qty", "frgn_stk_book_uv", "now_pric", "pl_rt"]].to_string())


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["buy", "sell", "select", "status"])
    ap.add_argument("--real", action="store_true")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--min-chg", type=float, default=0.03)
    ap.add_argument("--min-price", type=float, default=3.0)
    ap.add_argument("--capital", type=float, default=0.0, help="USD. 0 이면 주문가능금액 또는 페이퍼 1만불")
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--mode-env", dest="kmode")
    a = ap.parse_args()
    client = KiwoomClient(mode=a.kmode)
    try:
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
        kakao(f"[aut.stock-us] {a.mode} 실패: {type(e).__name__}: {str(e)[:150]}")
        raise


if __name__ == "__main__":
    main()
