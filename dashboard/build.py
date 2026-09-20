"""results/ 의 기록으로 정적 대시보드 (dashboard/index.html) 를 만든다. 매 실행 후 run_overnight.sh 가 호출한다.

python -m dashboard.build
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
OUT = Path(__file__).resolve().parent / "index.html"
KST = timezone(timedelta(hours=9))


def _read(name: str) -> pd.DataFrame:
    p = RESULTS / name
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, dtype={"code": str})


def _pct(v) -> str:
    try:
        return f"{float(v)*100:+.2f}%"
    except (TypeError, ValueError):
        return "-"


def _table(df: pd.DataFrame, cols: dict[str, str], fmt: dict | None = None, cls: str = "") -> str:
    fmt = fmt or {}
    if df.empty:
        return "<p class='muted'>기록 없음</p>"
    head = "".join(f"<th>{html.escape(t)}</th>" for t in cols.values())
    rows = []
    for _, r in df.iterrows():
        tds = []
        for c in cols:
            v = r.get(c, "")
            s = fmt[c](v) if c in fmt else ("" if pd.isna(v) else str(v))
            klass = ""
            if c in fmt and s.startswith("+"):
                klass = " class='up'"
            elif c in fmt and s.startswith("-"):
                klass = " class='down'"
            tds.append(f"<td{klass}>{html.escape(s)}</td>")
        rows.append("<tr>" + "".join(tds) + "</tr>")
    return f"<table class='{cls}'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def build() -> Path:
    paper = _read("overnight_paper.csv")
    if not paper.empty:
        if "variant" not in paper:
            paper["variant"] = "base"
        paper["variant"] = paper["variant"].fillna("base")
    allpaper = paper
    paper = paper[paper["variant"] == "base"] if not paper.empty else paper
    live = _read("overnight_log.csv")
    now = datetime.now(KST)
    parts = [f"<p class='muted'>갱신 {now:%Y-%m-%d %H:%M} KST</p>"]

    # 누적 성적
    if not paper.empty and "ret" in paper:
        done = paper[paper["ret"].notna()]
        if not done.empty:
            daily = done.groupby("date")["ret"].mean().sort_index()
            eq = (1 + daily).cumprod()
            dd = (eq / eq.cummax() - 1).min()
            alt = ""
            if "ret_0930" in done and done["ret_0930"].notna().any():
                both = done[done["ret_0930"].notna()]
                d0 = both.groupby("date")["ret"].mean(); d9 = both.groupby("date")["ret_0930"].mean()
                alt = (f"<p class='muted'>같은 종목을 09:30 에 팔았다면: 일평균 {_pct(d9.mean())} (시가 매도 {_pct(d0.mean())}) "
                       f"{len(d9)}일 비교</p>")
            parts.append("<h2>페이퍼 누적</h2>" + alt)
            parts.append("<div class='cards'>"
                         f"<div class='card'><div class='k'>거래일</div><div class='v'>{len(daily)}</div></div>"
                         f"<div class='card'><div class='k'>일평균</div><div class='v {'up' if daily.mean()>0 else 'down'}'>{_pct(daily.mean())}</div></div>"
                         f"<div class='card'><div class='k'>누적</div><div class='v {'up' if eq.iloc[-1]>1 else 'down'}'>{_pct(eq.iloc[-1]-1)}</div></div>"
                         f"<div class='card'><div class='k'>일승률</div><div class='v'>{(daily>0).mean()*100:.0f}%</div></div>"
                         f"<div class='card'><div class='k'>최대낙폭</div><div class='v down'>{_pct(dd)}</div></div>"
                         "</div>")
            dtab = pd.DataFrame({"date": daily.index, "ret": daily.values,
                                 "n": done.groupby("date").size().reindex(daily.index).values,
                                 "win": done.groupby("date")["ret"].apply(lambda s: (s > 0).mean()).reindex(daily.index).values,
                                 "cum": eq.values - 1}).sort_values("date", ascending=False)
            parts.append("<h3>일별</h3>" + _table(dtab, {"date": "날짜", "n": "종목", "win": "승률", "ret": "일수익", "cum": "누적"},
                                                {"ret": _pct, "cum": _pct, "win": lambda v: f"{float(v)*100:.0f}%"}))

    # 최근 후보 (오늘 또는 마지막 매수일)
    if not paper.empty:
        days = sorted(paper["date"].unique(), reverse=True)[:2]  # 오늘 후보 + 직전일 결과
        for day in days:
            rows = paper[paper["date"] == day].copy()
            evaluated = "exit" in rows and rows["exit"].notna().any()
            parts.append(f"<h2>{'결과' if evaluated else '후보'} {html.escape(str(day))}</h2>")
            cols = {"name": "종목", "code": "코드", "price": "매수가", "chg": "당일등락", "net_i": "기관(백만)", "net_f": "외인(백만)"}
            fmt = {"chg": _pct, "price": lambda v: f"{float(v):,.0f}", "net_i": lambda v: f"{float(v):,.0f}", "net_f": lambda v: f"{float(v):,.0f}"}
            if evaluated:
                cols.update({"exit": "익일시가", "ret": "수익률"})
                fmt.update({"exit": lambda v: f"{float(v):,.0f}" if pd.notna(v) else "-", "ret": _pct})
                if "ret_0930" in rows and rows["ret_0930"].notna().any():
                    cols.update({"ret_0930": "09:30매도"})
                    fmt.update({"ret_0930": _pct})
                rows = rows.sort_values("ret", ascending=False)
            parts.append(_table(rows, cols, fmt))

    # 실주문 기록
    if not live.empty:
        parts.append("<h2>실주문 기록 (최근 60건)</h2>")
        parts.append(_table(live.tail(60).iloc[::-1], {"date": "날짜", "time": "시각", "side": "구분", "name": "종목", "qty": "수량", "price": "가격", "ord_no": "주문번호"}))

    # 변형 비교
    if not allpaper.empty and "ret" in allpaper and allpaper["variant"].nunique() > 1:
        ev = allpaper[allpaper["ret"].notna()]
        if not ev.empty:
            g = ev.groupby(["variant", "date"])["ret"].mean().groupby("variant")
            vt = pd.DataFrame({"days": g.size(), "avg": g.mean(), "win": g.apply(lambda s: (s > 0).mean()),
                               "cum": g.apply(lambda s: (1 + s).prod() - 1)}).reset_index().sort_values("avg", ascending=False)
            names = {"base": "채택안 (동시순매수 +3% 상위30)", "surge": "급등 10%+", "small": "소형주 가중", "sellside": "동시 순매도 +3%", "top50": "상위 50"}
            vt["variant"] = vt["variant"].map(lambda v: names.get(v, v))
            parts.append("<h2>변형 비교 (페이퍼)</h2>" + _table(vt, {"variant": "변형", "days": "일수", "avg": "일평균", "win": "일승률", "cum": "누적"},
                                                          {"avg": _pct, "cum": _pct, "win": lambda v: f"{float(v)*100:.0f}%"}))

    # KRX 확정 데이터와 잠정 선정 비교
    panel = ROOT / "data" / "panel.parquet"
    if panel.exists() and not paper.empty:
        try:
            pn = pd.read_parquet(panel)
            dates = pn.index.get_level_values("date")
            last = dates.max()
            parts.append(f"<h2>일봉 데이터</h2><p class='muted'>{dates.min().date()} ~ {last.date()} / {dates.nunique()} 거래일 / {pn.index.get_level_values('ticker').nunique()} 종목</p>")
            day_str = last.strftime("%Y-%m-%d")
            picks = paper[paper["date"] == day_str]
            if not picks.empty:
                import sys
                sys.path.insert(0, str(ROOT))
                from overnight.backtest import OvernightParams, candidates
                C = pn["close"].unstack("ticker").sort_index(); I = pn["inst"].unstack("ticker").reindex(C.index); F = pn["foreign"].unstack("ticker").reindex(C.index)
                sel = candidates(C, I, F, OvernightParams(top=30, min_chg=0.03)).loc[last]
                final = set(sel[sel].index); live_set = set(picks["code"])
                parts.append(f"<p>{day_str} 잠정 선정 {len(live_set)} 종목 중 확정 데이터 기준 후보와 겹침 <b>{len(final & live_set)}</b> 개</p>")
        except Exception as e:  # noqa: BLE001
            parts.append(f"<p class='muted'>패널 비교 실패: {html.escape(str(e))}</p>")

    # 백테스트 참고
    bt = RESULTS / "overnight" / "daily.csv"
    if bt.exists():
        d = pd.read_csv(bt, index_col=0, parse_dates=True)["ret"]
        eq = (1 + d).cumprod()
        parts.append("<h2>백테스트 참고 (2023-09~2026-09 비용 18bp)</h2>"
                     f"<p>일평균 {_pct(d.mean())} 일승률 {(d>0).mean()*100:.0f}% 누적 {_pct(eq.iloc[-1]-1)} 최대낙폭 {_pct((eq/eq.cummax()-1).min())}</p>")

    body = "\n".join(parts)
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>aut.stock</title>
<style>
:root{{--bg:#fff;--fg:#111;--muted:#777;--line:#e5e5e5;--up:#d1242f;--down:#1a5fd0;--card:#f6f6f6}}
@media(prefers-color-scheme:dark){{:root{{--bg:#121212;--fg:#eee;--muted:#999;--line:#333;--card:#1e1e1e;--up:#ff6b6b;--down:#6ea8ff}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,system-ui,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}}
h1{{font-size:20px;margin:0 0 4px}}h2{{font-size:17px;margin:24px 0 8px}}h3{{font-size:15px;margin:16px 0 6px}}
.muted{{color:var(--muted)}}.up{{color:var(--up)}}.down{{color:var(--down)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px}}
.card{{background:var(--card);border-radius:8px;padding:10px}}.card .k{{font-size:12px;color:var(--muted)}}.card .v{{font-size:20px;font-weight:600}}
table{{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap;display:block;overflow-x:auto}}
th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right}}th:first-child,td:first-child{{text-align:left}}
thead th{{color:var(--muted);font-weight:500}}
</style></head><body>
<h1>aut.stock 오버나이트 수급</h1>
<p class="muted">당일 기관+외인 동시 순매수 상위 30 종가 매수 → 익일 시가 매도</p>
{body}
</body></html>"""
    OUT.write_text(page, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print(build())
