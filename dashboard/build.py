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
        f = float(v)
        return "-" if pd.isna(f) else f"{f*100:+.2f}%"
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
        code = str(r.get("code", "")) if "code" in cols else ""
        attr = f" class='pick' data-code='{html.escape(code)}'" if code.isdigit() else ""
        rows.append(f"<tr{attr}>" + "".join(tds) + "</tr>")
    return f"<table class='{cls}'><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _vol(v) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "-"
    if pd.isna(f):
        return "-"
    return f"{f/1e4:,.0f}만" if f >= 1e4 else f"{f:,.0f}"


def _cell(r, c, fmt) -> str:
    if not c:
        return "<td></td>"
    v = r.get(c, "")
    s = fmt[c](v) if c in fmt else ("" if pd.isna(v) else str(v))
    klass = ""
    if c in fmt and s.startswith("+"):
        klass = " class='up'"
    elif c in fmt and s.startswith("-") and s != "-":
        klass = " class='down'"
    return f"<td{klass}>{html.escape(s)}</td>"


def _table2(df: pd.DataFrame, line1: dict[str, str], line2: dict[str, str], fmt: dict) -> str:
    """종목당 두 줄. 한 화면에 가로 스크롤 없이 보이게. 종목 묶음(tbody)을 누르면 코드 복사."""
    if df.empty:
        return "<p class='muted'>기록 없음</p>"
    n = max(len(line1), len(line2))
    k1 = list(line1) + [""] * (n - len(line1)); k2 = list(line2) + [""] * (n - len(line2))
    t1 = list(line1.values()) + [""] * (n - len(line1)); t2 = list(line2.values()) + [""] * (n - len(line2))
    head = ("<thead><tr>" + "".join(f"<th>{html.escape(t)}</th>" for t in t1) + "</tr>"
            "<tr class='l2'>" + "".join(f"<th>{html.escape(t)}</th>" for t in t2) + "</tr></thead>")
    bodies = []
    for _, r in df.iterrows():
        code = str(r.get("code", ""))
        hot = " hot" if r.get("_star") is True else ""
        attr = f" class='pick{hot}' data-code='{html.escape(code)}'" if code.isdigit() else ""
        cells = [_cell(r, c, fmt) for c in k1]
        color = r.get("_color")
        if isinstance(color, str) and color and k1 and k1[0] == "name":  # 두 날짜에 모두 있는 종목은 이름에 같은 색 배지
            cells[0] = f"<td><span class='same' style='background:{color}'>{html.escape(str(r.get('name', '')))}</span></td>"
        bodies.append(f"<tbody{attr}><tr>" + "".join(cells) + "</tr>"
                      "<tr class='l2'>" + "".join(_cell(r, c, fmt) for c in k2) + "</tr></tbody>")
    return f"<table class='two'>{head}{''.join(bodies)}</table>"


def _mark_star(rows: pd.DataFrame, frac: float = 0.4) -> pd.DataFrame:
    """overnight.live.star_codes 와 같은 기준. share (순매수/거래대금) 가 그날 후보 중 낮은 쪽 40% 면 _star."""
    rows = rows.copy()
    sh = pd.to_numeric(rows["share"], errors="coerce") if "share" in rows else pd.Series(float("nan"), index=rows.index)
    rk = sh.rank(pct=True)
    rows["_star"] = (rk <= frac).fillna(False).astype(bool)
    return rows


def _fill_chg2(paper: pd.DataFrame, panel_path: Path) -> pd.DataFrame:
    """chg2 (전전일 종가 대비) 가 비어 있는 행을 패널로 채운다. 전일 종가가 0.5% 안에서 맞을 때만."""
    if paper.empty:
        return paper
    paper = paper.copy()
    if "chg2" not in paper:
        paper["chg2"] = float("nan")
    paper["chg2"] = pd.to_numeric(paper["chg2"], errors="coerce")
    miss = paper["chg2"].isna()
    if not miss.any() or not panel_path.exists():
        return paper
    try:
        C = pd.read_parquet(panel_path, columns=["close"])["close"].unstack("ticker").sort_index()
    except Exception:  # noqa: BLE001
        return paper
    for i, r in paper[miss].iterrows():
        try:
            code, price, chg = r["code"], float(r["price"]), float(r["chg"])
            if code not in C:
                continue
            hist = C[code][C.index < pd.Timestamp(r["date"])].dropna()
            if len(hist) < 2:
                continue
            prev, before = float(hist.iloc[-1]), float(hist.iloc[-2])
            if prev > 0 and before > 0 and abs(prev / (price / (1 + chg)) - 1) <= 0.005:
                paper.at[i, "chg2"] = price / before - 1
        except (TypeError, ValueError):
            continue
    return paper


def _fill_volume(paper: pd.DataFrame, panel_path: Path) -> pd.DataFrame:
    """volume 이 비어 있는 행 (거래량 기록 전 매수분) 을 패널의 그날 확정 거래량으로 채우고 share 도 계산한다."""
    if paper.empty or not panel_path.exists():
        return paper
    paper = paper.copy()
    for c in ("volume", "share"):
        paper[c] = pd.to_numeric(paper[c], errors="coerce") if c in paper else float("nan")
    miss = paper["volume"].isna()
    if miss.any():
        try:
            vol = pd.read_parquet(panel_path, columns=["volume"])["volume"]
        except Exception:  # noqa: BLE001
            vol = None
        if vol is not None:
            # pandas 버전마다 날짜 단위와 문자열 타입이 달라 MultiIndex 매칭이 조용히 빗나간다. 문자열 키로 맞춘다
            vd = vol.reset_index()
            vd.columns = ["date", "ticker", "volume"]
            lut = dict(zip(pd.to_datetime(vd["date"]).dt.strftime("%Y-%m-%d") + "|" + vd["ticker"].astype(str).str.zfill(6), vd["volume"]))
            keys = pd.to_datetime(paper.loc[miss, "date"]).dt.strftime("%Y-%m-%d") + "|" + paper.loc[miss, "code"].astype(str).str.zfill(6)
            paper.loc[miss, "volume"] = [lut.get(k, float("nan")) for k in keys]
            print(f"거래량 채움 {paper.loc[miss, 'volume'].notna().sum()}/{int(miss.sum())} 행 (패널)")
    net = (pd.to_numeric(paper.get("net_i"), errors="coerce") + pd.to_numeric(paper.get("net_f"), errors="coerce")) * 1e6
    calc = net / (paper["volume"] * pd.to_numeric(paper["price"], errors="coerce"))
    paper["share"] = paper["share"].fillna(calc.where(paper["volume"] > 0))
    return paper


def build() -> Path:
    paper = _read("overnight_paper.csv")
    if not paper.empty:
        if "variant" not in paper:
            paper["variant"] = "base"
        paper["variant"] = paper["variant"].fillna("base")
    panel = ROOT / "data" / "panel.parquet"
    paper = _fill_volume(_fill_chg2(paper, panel), panel)
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
            if "share" in done:
                sd = pd.concat([_mark_star(g) for _, g in done.groupby("date")])  # 날짜별로 따로 순위
                st = sd[sd["_star"]]
                if not st.empty:
                    ds = st.groupby("date")["ret"].mean(); da = done[done["date"].isin(ds.index)].groupby("date")["ret"].mean()
                    alt += (f"<p class='muted'>★ 종목만 샀다면: 일평균 {_pct(ds.mean())} (전체 {_pct(da.mean())}) {len(ds)}일 비교</p>")
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
        # 두 날짜 목록에 모두 있는 종목: 종목마다 다른 색. 흰 글씨가 잘 보이는 진한 색만 쓴다
        same_colors = ["#e03131", "#1971c2", "#2f9e44", "#f08c00", "#7048e8", "#0c8599", "#c2255c", "#5c940d", "#9c36b5", "#364fc7", "#d9480f", "#087f5b"]
        common = sorted(set.intersection(*[set(paper.loc[paper["date"] == d, "code"]) for d in days])) if len(days) == 2 else []
        color_of = {c: same_colors[i % len(same_colors)] for i, c in enumerate(common)}
        for day in days:
            rows = _mark_star(paper[paper["date"] == day].copy())
            rows["_color"] = rows["code"].map(color_of)
            evaluated = "exit" in rows and rows["exit"].notna().any()
            parts.append(f"<h2>{'결과' if evaluated else '후보'} {html.escape(str(day))}</h2>")
            line1 = {"name": "종목", "price": "매수가", "chg": "전일비", "chg2": "전전일비"}
            line2 = {"code": "코드", "net_i": "기관", "net_f": "외인", "volume": "거래량"}
            num = lambda v: "-" if pd.isna(pd.to_numeric(v, errors="coerce")) else f"{float(v):,.0f}"
            fmt = {"chg": _pct, "chg2": _pct, "price": num, "net_i": num, "net_f": num, "volume": _vol}
            if evaluated:
                line1["ret"] = "시가매도"  # 익일 시가 매도 수익률
                fmt["ret"] = _pct
                if "ret_0930" in rows and rows["ret_0930"].notna().any():
                    line2["ret_0930"] = "09:30매도"
                    fmt["ret_0930"] = _pct
                rows = rows.sort_values("ret", ascending=False)
            else:  # 후보는 별표 먼저 그다음 거래량 많은 순
                rows = rows.assign(_v=pd.to_numeric(rows.get("volume"), errors="coerce")).sort_values(["_star", "_v"], ascending=[False, False], na_position="last")
            legend = "윗줄 매수가 전일비 전전일비 / 아랫줄 기관 외인 순매수 (백만원) 거래량 (15:21 매수 시점 누적. 거래량 기록 전 날짜는 KRX 확정 거래량)"
            if rows["_star"].any():
                legend += ("<br><span class='hotkey'>색칠</span> 내일 시가 상승 가능성 높은 종목. 순매수가 거래대금에서 차지하는 비중이 낮은 쪽 40%. "
                           "3년 백테스트 익일 시가 일평균 +0.36% (전체 +0.20%) 비용 18bp 후")
            if color_of:
                legend += f"<br><span class='same' style='background:{same_colors[0]}'>색 배지</span> {html.escape(days[1])} 와 {html.escape(days[0])} 두 날 모두 후보인 종목 {len(color_of)}개. 같은 종목은 같은 색"
            parts.append(f"<p class='muted'>{legend}</p>")
            parts.append(_table2(rows, line1, line2, fmt))

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
:root{{--bg:#fff;--fg:#111;--muted:#777;--line:#e5e5e5;--up:#d1242f;--down:#1a5fd0;--card:#f6f6f6;--hot:#fff4c2}}
@media(prefers-color-scheme:dark){{:root{{--bg:#121212;--fg:#eee;--muted:#999;--line:#333;--card:#1e1e1e;--up:#ff6b6b;--down:#6ea8ff;--hot:#3a3312}}}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,system-ui,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}}
h1{{font-size:20px;margin:0 0 4px}}h2{{font-size:17px;margin:24px 0 8px}}h3{{font-size:15px;margin:16px 0 6px}}
.muted{{color:var(--muted)}}.up{{color:var(--up)}}.down{{color:var(--down)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px}}
.card{{background:var(--card);border-radius:8px;padding:10px}}.card .k{{font-size:12px;color:var(--muted)}}.card .v{{font-size:20px;font-weight:600}}
table{{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap;display:block;overflow-x:auto}}
th,td{{padding:6px 8px;border-bottom:1px solid var(--line);text-align:right}}th:first-child,td:first-child{{text-align:left}}
thead th{{color:var(--muted);font-weight:500}}
body>p:first-child{{margin-top:0}}
.pick{{cursor:pointer}}.pick:active{{background:var(--card)}}
tbody.hot td{{background:var(--hot)}}.same{{color:#fff;padding:1px 6px;border-radius:4px;font-weight:600}}.hotkey{{background:var(--hot);color:var(--fg);padding:0 4px;border-radius:3px}}
table.two{{white-space:normal;display:table}}table.two td,table.two th{{padding:4px 6px}}
table.two tr:not(.l2) td{{border-bottom:none;padding-top:8px}}table.two tr.l2 td{{font-size:12px;color:var(--muted);padding-bottom:8px}}
table.two thead tr:not(.l2) th{{border-bottom:none}}table.two tr.l2 td.up{{color:var(--up)}}table.two tr.l2 td.down{{color:var(--down)}}
table.two tr:not(.l2) td:first-child{{font-weight:600;white-space:nowrap;max-width:7.5em;overflow:hidden;text-overflow:ellipsis}}
table.two th{{white-space:nowrap}}
#toast{{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--fg);color:var(--bg);padding:8px 14px;border-radius:8px;font-size:14px;opacity:0;transition:opacity .2s;pointer-events:none}}
#toast.on{{opacity:.92}}
</style></head><body>
{body}
<div id="toast"></div>
<script>
// 영웅문S# 앱 스킴. zerozistocks 블로그에서 실기기로 검증된 값 (intent 패키지 호출은 플레이스토어로 빠짐)
const HERO_URL = "heromts://heromtshost";
function toast(t) {{ const e = document.getElementById("toast"); e.textContent = t; e.classList.add("on"); setTimeout(() => e.classList.remove("on"), 1800); }}
async function copy(t) {{
  try {{ await navigator.clipboard.writeText(t); return true; }} catch (_) {{}}
  const a = document.createElement("textarea"); a.value = t; a.style.position = "fixed"; a.style.opacity = "0";
  document.body.appendChild(a); a.select(); let ok = false; try {{ ok = document.execCommand("copy"); }} catch (_) {{}}
  a.remove(); return ok;
}}
document.addEventListener("click", async (ev) => {{
  const tr = ev.target.closest(".pick"); if (!tr) return;
  const code = tr.dataset.code; const ok = await copy(code);
  toast(ok ? code + " 복사됨" : "복사 실패 " + code);
  if (!/Android|iPhone|iPad/i.test(navigator.userAgent)) return;
  setTimeout(() => {{ location.href = HERO_URL; }}, 300);
}});
</script>
</body></html>"""
    OUT.write_text(page, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    print(build())
