"""데이 단타 웹 대시보드 (dd.usb.kr). 기록 파일을 읽어 daytrade/web/index.html 한 장을 만든다.

입력 results/daytrade_paper.csv (페이퍼) results/daytrade_log.csv (실주문) data/daytrade/minute/ (분봉)
출력 daytrade/web/index.html  (다른 전략 대시보드 dashboard/ 와 폴더도 주소도 따로다)

python -m daytrade.web        # 한 번 생성
러너 (deploy/run_daytrade.sh) 가 buy sell eval 뒤에 자동으로 부른다.
"""
from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"
OUT_DIR = Path(__file__).resolve().parent / "web"
KST = timezone(timedelta(hours=9))
DOW = "월화수목금토일"
HERO_URL = "heromts://heromtshost"  # 영웅문S# 앱 스킴 (안드로이드 실기기 검증값. 앱만 열리고 종목 화면은 안 열린다)
BACKTEST_NOTE = "백테스트 3년 (비용 18bp) 일평균 +0.66% 승률 59% 샤프 4.2"
NUM = ["price", "prev_close", "gap", "liq20", "exit", "ret", "qty"]

CSS = """
:root{--bg:#f6f7f9;--fg:#111827;--muted:#6b7280;--line:#e5e7eb;--card:#fff;--up:#e5484d;--down:#2f6fed}
@media(prefers-color-scheme:dark){:root{--bg:#0e1116;--fg:#eceff4;--muted:#98a2b3;--line:#252b35;--card:#161a21;--up:#ff6b6b;--down:#6aa5ff}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 -apple-system,"Apple SD Gothic Neo","Noto Sans KR",system-ui,sans-serif;-webkit-text-size-adjust:100%}
main{max-width:760px;margin:0 auto;padding:16px 16px 48px}
h1{font-size:21px;margin:4px 0 2px}
h2{font-size:16px;margin:28px 0 8px}
.muted{color:var(--muted);font-size:13px}
.up{color:var(--up)}.down{color:var(--down)}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;margin-top:12px}
@media(min-width:520px){.cards{grid-template-columns:repeat(3,1fr)}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:10px 12px}
.k{font-size:12px;color:var(--muted)}
.v{font-size:23px;font-weight:650;letter-spacing:-.3px}
.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:4px 10px}
.wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:9px 6px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}
tr:last-child td{border-bottom:0}
th:first-child,td:first-child{text-align:left}
thead th{color:var(--muted);font-weight:500;font-size:12px}
tr.pick{cursor:pointer}
tr.pick:active{background:var(--line)}
.code{display:block;color:var(--muted);font-size:11px;line-height:1.2}
.badge{display:inline-block;font-size:11px;padding:0 6px;border-radius:8px;background:var(--line);color:var(--muted);margin-left:4px}
.chart{width:100%;height:auto;display:block}
.chart text{fill:var(--muted);font-size:11px}
.chart .zero{stroke:var(--line);stroke-width:1;stroke-dasharray:4 4}
.chart .mark{stroke:var(--muted);stroke-width:1;stroke-dasharray:2 3;opacity:.55}
.chart polyline{fill:none;stroke-width:2.2;stroke-linejoin:round;stroke-linecap:round}
.chart polyline.pos{stroke:var(--up)}
.chart polyline.neg{stroke:var(--down)}
.chart circle{stroke:none}
.chart circle.pos{fill:var(--up)}
.chart circle.neg{fill:var(--down)}
.two{display:grid;grid-template-columns:1fr;gap:10px}
@media(min-width:620px){.two{grid-template-columns:1fr 1fr}}
#toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:var(--fg);color:var(--bg);padding:8px 14px;border-radius:8px;font-size:14px;opacity:0;transition:opacity .2s;pointer-events:none}
#toast.on{opacity:.92}
"""

JS = """
const HERO_URL = "heromts://heromtshost";
function toast(t) { const e = document.getElementById("toast"); e.textContent = t; e.classList.add("on"); setTimeout(() => e.classList.remove("on"), 1800); }
async function copy(t) {
  try { await navigator.clipboard.writeText(t); return true; } catch (_) {}
  const a = document.createElement("textarea"); a.value = t; a.style.position = "fixed"; a.style.opacity = "0";
  document.body.appendChild(a); a.select(); let ok = false; try { ok = document.execCommand("copy"); } catch (_) {}
  a.remove(); return ok;
}
document.addEventListener("click", async (ev) => {
  const tr = ev.target.closest("tr.pick"); if (!tr) return;
  const code = tr.dataset.code; const ok = await copy(code);
  toast(ok ? code + " 복사됨" : "복사 실패 " + code);
  if (!/Android/i.test(navigator.userAgent)) return;
  setTimeout(() => { location.href = HERO_URL; }, 300);
});
"""


# ---------- 데이터 ----------
def load_trades(results: Path) -> pd.DataFrame:
    """페이퍼와 실주문 매수 기록을 합친다. ret 는 15:45 평가 뒤에 채워진다."""
    frames = []
    for name, src in (("daytrade_paper.csv", "페이퍼"), ("daytrade_log.csv", "실주문")):
        p = results / name
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p, dtype={"code": str})
        except Exception:  # noqa: BLE001  빈 파일이나 깨진 줄은 건너뛴다
            continue
        if df.empty or "side" not in df or "date" not in df:
            continue
        df = df[df["side"] == "buy"].copy()
        df["src"] = src
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    t = pd.concat(frames, ignore_index=True)
    for c in NUM:
        t[c] = pd.to_numeric(t[c], errors="coerce") if c in t else np.nan
    t["date"] = t["date"].astype(str)
    t["name"] = t["name"].fillna(t["code"]) if "name" in t else t["code"]
    return t


def daily_table(t: pd.DataFrame) -> pd.DataFrame:
    cols = ["n", "mean", "win", "best", "worst"]
    d = t[t["ret"].notna()] if not t.empty else t
    if d.empty:
        return pd.DataFrame(columns=cols)
    g = d.groupby("date")["ret"]
    out = pd.DataFrame({"n": g.size(), "mean": g.mean(), "win": g.apply(lambda s: float((s > 0).mean())),
                        "best": g.max(), "worst": g.min()})
    return out.sort_index()


def minute_path(minutes: pd.DataFrame | None) -> tuple[pd.Series, int, int] | None:
    """후보 종목의 시가 대비 평균 경로. (시각별 평균 수익률 / 일수 / 종목-일 수). 분봉이 없으면 None."""
    try:
        if minutes is None:
            from daytrade.collect import load_minutes

            minutes = load_minutes()
        if minutes is None or minutes.empty:
            return None
        from daytrade.minute_analysis import paths

        wide, _ = paths(minutes)
        avg = wide.mean(axis=0).dropna()
        if len(avg) < 5:
            return None
        return avg, int(wide.index.get_level_values("day").nunique()), int(len(wide))
    except Exception:  # noqa: BLE001  분봉 문제로 페이지 전체가 죽지 않게 한다
        return None


# ---------- 표기 ----------
def ok(x) -> bool:
    return x is not None and bool(np.isfinite(x))


def pct(x, d: int = 2) -> str:
    return f"{x * 100:+.{d}f}%" if ok(x) else "-"


def cls(x) -> str:
    return "up" if ok(x) and x > 0 else "down" if ok(x) and x < 0 else ""


def span(x, d: int = 2) -> str:
    return f'<span class="{cls(x)}">{pct(x, d)}</span>'


def day_label(s: str) -> str:
    ts = pd.Timestamp(s)
    return f"{ts:%m/%d}({DOW[ts.dayofweek]})"


def esc(x) -> str:
    return html.escape(str(x), quote=True)


# ---------- 차트 (SVG) ----------
def svg_line(ys, xlabels: dict[int, str] | None = None, marks: list[tuple[int, str]] | None = None,
             w: int = 640, h: int = 210) -> str:
    """수익률 (소수) 목록을 꺾은선으로. xlabels 는 {위치: 글자} marks 는 [(위치 글자)] 세로 안내선."""
    ys = [float(v) for v in ys]
    if len(ys) < 2:
        return '<p class="muted">데이터가 더 쌓이면 그려집니다</p>'
    left, right, top, bottom = 48, 12, 18, 26
    dmin, dmax = min(ys), max(ys)
    lo, hi = min(dmin, 0.0), max(dmax, 0.0)
    if hi - lo < 1e-9:
        hi = lo + 0.01
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    n = len(ys)

    def X(i):
        return left + (w - left - right) * i / (n - 1)

    def Y(v):
        return top + (h - top - bottom) * (hi - v) / (hi - lo)

    side = "pos" if ys[-1] >= 0 else "neg"
    out = [f'<svg viewBox="0 0 {w} {h}" class="chart" role="img">']
    out.append(f'<line class="zero" x1="{left}" x2="{w - right}" y1="{Y(0):.1f}" y2="{Y(0):.1f}"/>')
    rng = hi - lo
    for v in (dmin, 0.0, dmax):  # 값 라벨 (0 선과 너무 가까운 것은 뺀다)
        if v != 0.0 and abs(v) < rng * 0.09:
            continue
        out.append(f'<text x="{left - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v * 100:+.1f}%</text>')
    for i, label in (marks or []):
        out.append(f'<line class="mark" x1="{X(i):.1f}" x2="{X(i):.1f}" y1="{top}" y2="{h - bottom}"/>')
        out.append(f'<text x="{X(i):.1f}" y="{top - 5}" text-anchor="middle">{esc(label)}</text>')
    pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(ys))
    out.append(f'<polyline class="{side}" points="{pts}"/>')
    out.append(f'<circle class="{side}" cx="{X(n - 1):.1f}" cy="{Y(ys[-1]):.1f}" r="3.5"/>')
    for i, label in (xlabels or {}).items():
        anchor = "start" if i == 0 else "end" if i == n - 1 else "middle"
        out.append(f'<text x="{X(i):.1f}" y="{h - 6}" text-anchor="{anchor}">{esc(label)}</text>')
    out.append("</svg>")
    return "".join(out)


# ---------- 구획 ----------
def cards(daily: pd.DataFrame, t: pd.DataFrame) -> str:
    if daily.empty:
        return ""
    means = daily["mean"]
    equity = float((1 + means).prod() - 1)
    trade_win = float((t.loc[t["ret"].notna(), "ret"] > 0).mean())
    items = [
        ("일평균", span(float(means.mean()))),
        ("일 승률", f"{(means > 0).mean() * 100:.0f}%"),
        ("누적 수익", span(equity, 1)),
        ("종목 승률", f"{trade_win * 100:.0f}%"),
        ("평가한 날", f"{len(daily)}일"),
        ("최악의 날", span(float(means.min()))),
    ]
    body = "".join(f'<div class="card"><div class="k">{k}</div><div class="v">{v}</div></div>' for k, v in items)
    return f'<div class="cards">{body}</div><p class="muted">참고 {BACKTEST_NOTE}</p>'


def picks_section(t: pd.DataFrame) -> str:
    last = t["date"].max()
    d = t[t["date"] == last]
    done = d["ret"].dropna()
    head = f"<h2>최근 매수 종목 {day_label(last)} {len(d)}개</h2>"
    if len(done):
        head += (f'<p class="muted">결과 평균 {span(float(done.mean()))} 승률 {(done > 0).mean() * 100:.0f}%'
                 f' (종가 평가 {len(done)}개)</p>')
    else:
        head += '<p class="muted">종가 평가 전입니다 (15:45 에 채워집니다)</p>'
    head += '<p class="muted">줄을 누르면 종목코드가 복사되고 영웅문S# 이 열립니다 (안드로이드)</p>'
    rows = []
    for r in d.itertuples(index=False):
        badge = '<span class="badge">실</span>' if getattr(r, "src", "") == "실주문" else ""
        price = f"{r.price:.0f}" if ok(r.price) else "-"
        rows.append(f'<tr class="pick" data-code="{esc(r.code)}"><td>{esc(r.name)}{badge}<span class="code">{esc(r.code)}</span></td>'
                    f'<td>{price}</td><td>{span(r.gap, 1)}</td><td>{span(r.ret) if ok(r.ret) else "-"}</td></tr>')
    table = ('<div class="box wrap"><table><thead><tr><th>종목</th><th>예상가</th><th>갭</th><th>결과</th></tr></thead><tbody>'
             + "".join(rows) + "</tbody></table></div>")
    return head + table


def equity_section(daily: pd.DataFrame) -> str:
    if len(daily) < 2:
        return ""
    eq = (1 + daily["mean"]).cumprod() - 1
    idx = list(eq.index)
    labels = {0: day_label(idx[0]), len(idx) - 1: day_label(idx[-1])}
    if len(idx) >= 5:
        labels[len(idx) // 2] = day_label(idx[len(idx) // 2])
    return f'<h2>누적 수익 곡선</h2><div class="box">{svg_line(eq.tolist(), labels)}</div>'


def daily_section(daily: pd.DataFrame) -> str:
    if daily.empty:
        return ""
    rows = []
    for date, r in daily.iloc[::-1].head(30).iterrows():
        rows.append(f"<tr><td>{day_label(date)}</td><td>{int(r['n'])}</td><td>{span(r['mean'])}</td>"
                    f"<td>{r['win'] * 100:.0f}%</td><td>{span(r['best'], 1)}</td><td>{span(r['worst'], 1)}</td></tr>")
    return ('<h2>일별 결과</h2><div class="box wrap"><table><thead><tr><th>날짜</th><th>종목</th><th>평균</th><th>승률</th>'
            '<th>최고</th><th>최악</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>")


def minute_section(info: tuple[pd.Series, int, int] | None) -> str:
    if info is None:
        return ""
    avg, n_days, n_obs = info
    cols = list(avg.index)
    peak = avg.idxmax()
    parts = [f"고점 {peak} {pct(float(avg[peak]))}"]
    if "15:20" in avg.index:
        parts.append(f"15:20 {pct(float(avg['15:20']))}")
    elif cols:
        parts.append(f"마감 {cols[-1]} {pct(float(avg.iloc[-1]))}")
    marks = [(cols.index(t), t) for t in ("09:30", "15:20") if t in cols]
    xl = {cols.index(f"{h:02d}:00"): f"{h}시" for h in range(9, 16) if f"{h:02d}:00" in cols}
    chart = svg_line(avg.tolist(), xl, marks)
    return (f'<h2>시간대별 평균 경로 (시가 매수 기준)</h2><p class="muted">평균 {" · ".join(parts)} — 후보 {n_obs}건 {n_days}일</p>'
            f'<div class="box">{chart}</div><p class="muted">고점과 마감의 차이가 매도 시각을 정하는 근거입니다</p>')


def bin_table(d: pd.DataFrame, col: str, edges: list[float], labels: list[str], title: str) -> str:
    x = d[d["ret"].notna() & d[col].notna()].copy()
    if x.empty:
        return ""
    x["bin"] = pd.cut(x[col], edges, labels=labels)
    g = x.groupby("bin", observed=True)["ret"].agg(["size", "mean", lambda s: float((s > 0).mean())])
    g.columns = ["n", "mean", "win"]
    rows = "".join(f"<tr><td>{esc(i)}</td><td>{int(r['n'])}</td><td>{span(r['mean'])}</td><td>{r['win'] * 100:.0f}%</td></tr>"
                   for i, r in g.iterrows() if r["n"] > 0)
    return (f'<div><div class="k">{title}</div><div class="box wrap"><table><thead><tr><th>구간</th><th>건수</th>'
            f'<th>평균</th><th>승률</th></tr></thead><tbody>{rows}</tbody></table></div></div>')


def bins_section(t: pd.DataFrame) -> str:
    gap = bin_table(t, "gap", [-1, -0.10, -0.05, -0.03, 0], ["-10% 이하", "-10~-5%", "-5~-3%", "-3~-2%"], "갭 크기별")
    liq = bin_table(t, "liq20", [-1e-9, 0.1, 1, 5, 1e9], ["0.1억 미만", "0.1~1억", "1~5억", "5억 이상"], "유동성별 (20일 평균 기관+외인 금액)")
    if not (gap or liq):
        return ""
    return f'<h2>구간별 성과</h2><div class="two">{gap}{liq}</div>'


def build(results: Path = RESULTS, out_dir: Path = OUT_DIR, minutes: pd.DataFrame | None = None,
          now: datetime | None = None) -> Path:
    now = now or datetime.now(KST)
    t = load_trades(results)
    daily = daily_table(t)
    n_days = t["date"].nunique() if not t.empty else 0
    sections = [f"<h1>데이 단타</h1><p class=\"muted\">소형주 갭 하락 반등 · 시가 매수 후 15:20 매도 · 갱신 {now:%m/%d %H:%M}</p>"]
    if t.empty:
        sections.append('<h2>아직 기록이 없습니다</h2><p class="muted">평일 08:58 첫 실행 뒤에 매수 종목이 채워지고 15:45 에 수익률이 채워집니다</p>')
    else:
        srcs = " ".join(sorted(t["src"].unique()))
        sections.append(f'<p class="muted">기록 {n_days}일 · {srcs}</p>')
        sections += [cards(daily, t), picks_section(t), equity_section(daily), daily_section(daily)]
    sections += [minute_section(minute_path(minutes)), bins_section(t) if not t.empty else ""]
    sections.append('<p class="muted" style="margin-top:28px">규칙 전일 기관 외인 동시 순매도가 아닌 소형주 중 시가 갭 -2% 이하를 갭 큰 순 30개 장전 시장가 매수 '
                    '(08:58:30) → 15:20 시장가 매도. 수익률은 비용 18bp 반영. 페이퍼 매수가는 예상체결가입니다</p>')
    page = ('<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>데이 단타</title><style>{CSS}</style></head><body><main>' + "".join(sections)
            + f'</main><div id="toast"></div><script>{JS}</script></body></html>')
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(page, encoding="utf-8")
    return out


def main() -> None:
    print(build())


if __name__ == "__main__":
    main()
