"""웹 대시보드 생성을 가짜 기록으로 검증한다 (키움 없음). python -m daytrade.test_web"""
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from daytrade import web

NOW = datetime(2026, 11, 23, 9, 0)
NO_MIN = pd.DataFrame(columns=["code", "time", "open", "high", "low", "close", "volume"])
COLS = ["date", "time", "code", "name", "side", "qty", "price", "prev_close", "gap", "liq20", "ord_no"]


def row(date, code, name, price=1000.0, gap=-0.03, liq=0.5, **extra):
    return {"date": date, "time": "08:58:40", "code": code, "name": name, "side": "buy", "qty": 10, "price": price,
            "prev_close": price / (1 + gap), "gap": gap, "liq20": liq, "ord_no": "", **extra}


def build(rows_paper=None, rows_log=None, minutes=NO_MIN, raw_paper=None):
    d = Path(tempfile.mkdtemp())
    res = d / "results"
    res.mkdir()
    if rows_paper is not None:
        pd.DataFrame(rows_paper).to_csv(res / "daytrade_paper.csv", index=False)
    if raw_paper is not None:
        (res / "daytrade_paper.csv").write_text(raw_paper)
    if rows_log is not None:
        pd.DataFrame(rows_log).to_csv(res / "daytrade_log.csv", index=False)
    out = web.build(results=res, out_dir=d / "web", minutes=minutes, now=NOW)
    return out.read_text(encoding="utf-8")


# 1) 기록이 없어도 페이지는 만들어진다
h = build()
assert h.startswith("<!doctype html>") and "아직 기록이 없습니다" in h and "11/23 09:00" in h

# 2) 빈 파일이나 깨진 파일에도 죽지 않는다
assert "아직 기록이 없습니다" in build(raw_paper="")
assert "아직 기록이 없습니다" in build(raw_paper="date,side\n")

# 3) 평가 전 (ret 열이 아직 없음): 종목 표만 나오고 평가 전 안내가 뜬다
h = build([row("2026-11-20", "000020", "가나다"), row("2026-11-20", "000040", "라마바", gap=-0.05)])
assert 'data-code="000020"' in h and "종가 평가 전입니다" in h and "-3.0%" in h and "-5.0%" in h
assert "누적 수익 곡선" not in h and "일별 결과" not in h

# 4) 평가된 두 날과 평가 전인 마지막 날: 요약과 곡선과 일별 표. 이름의 태그 문자는 이스케이프된다
rows = [row("2026-11-18", "000020", "가나다", ret=0.04, exit=1040), row("2026-11-18", "000040", "라마바", ret=-0.02, exit=980),
        row("2026-11-19", "000020", "가나다", ret=0.02, exit=1020), row("2026-11-19", "000040", "라마바", ret=0.04, exit=1040),
        row("2026-11-20", "000060", "<b>사아</b>")]
h = build(rows)
m1, m2 = (0.04 - 0.02) / 2, (0.02 + 0.04) / 2
assert f"{(m1 + m2) / 2 * 100:+.2f}%" in h, "일평균"
assert f"{((1 + m1) * (1 + m2) - 1) * 100:+.1f}%" in h, "누적"
assert "&lt;b&gt;사아" in h and "<b>사아" not in h
assert "누적 수익 곡선" in h and "<polyline" in h and "일별 결과" in h and "11/19(목)" in h and "11/20(금)" in h
assert "평가한 날" in h and "2일" in h

# 5) 실주문 기록이 있으면 배지가 붙고 합쳐서 센다
h = build([row("2026-11-18", "000020", "가나다", ret=0.01)], [row("2026-11-19", "000040", "라마바", ret=0.03)])
assert '<span class="badge">실</span>' in h and "실주문 페이퍼" in h

# 6) 분봉이 있으면 시간대별 평균 경로가 그려진다
times = pd.date_range("2026-11-19 09:00", "2026-11-19 15:30", freq="1min")
mins = []
for code in ("000020", "000040"):
    for i, t in enumerate(times):
        p = 100 + min(i, 30) * 0.1 - max(i - 30, 0) * 0.002
        mins.append({"code": code, "time": t, "open": p, "high": p, "low": p, "close": p, "volume": 1})
full = pd.DataFrame(mins)
h = build([row("2026-11-19", "000020", "가나다", ret=0.01)], minutes=full)
assert "시간대별 평균 경로" in h and "고점 09:30" in h and "15:20 +" in h, "15:20 봉이 있으면 15:20 값"
# 실제 키움 분봉은 15:20~15:29 봉이 없다 (동시호가) -> 마감 15:30 값으로 대신한다
hm = pd.to_datetime(full["time"]).dt.strftime("%H:%M")
nogap = full[~((hm >= "15:20") & (hm < "15:30"))]
h = build([row("2026-11-19", "000020", "가나다", ret=0.01)], minutes=nogap)
assert "고점 09:30" in h and "마감 15:30" in h and "15:20 +" not in h

# 7) 구간별 표
rows = [row("2026-11-18", f"0000{i}0", f"종목{i}", gap=g, liq=l, ret=r) for i, (g, l, r) in
        enumerate([(-0.12, 0.05, 0.06), (-0.04, 0.5, 0.01), (-0.025, 2.0, -0.01)])]
h = build(rows)
assert "구간별 성과" in h and "-10% 이하" in h and "-5~-3%" in h and "0.1억 미만" in h and "1~5억" in h

# 8) 영웅문 스킴이 들어 있다
assert "heromts://heromtshost" in h
print("웹 대시보드 테스트 통과")
