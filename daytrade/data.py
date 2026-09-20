"""데이 단타 전용 데이터.

기존 data/panel.parquet 는 다른 전략이 매일 갱신해 쓰는 파일이라 건드리지 않는다.
여기서는 그 파일을 읽기 전용으로 참고해 daytrade 전용 스냅샷 data/daytrade/daily.parquet 를 따로 만든다.
스냅샷은 float32 로 저장해 크기를 줄이고 수집 구간을 파일 안에 기록해 백테스트가 재현되게 한다.

python -m daytrade.data build     # 스냅샷 생성
python -m daytrade.data info      # 스냅샷 정보
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "panel.parquet"           # 읽기 전용 참고
DATA_DIR = ROOT / "data" / "daytrade"
SNAPSHOT = DATA_DIR / "daily.parquet"
COLS = ["open", "close", "inst", "foreign"]


def build(source: Path = SOURCE, out: Path = SNAPSHOT) -> Path:
    """panel.parquet 를 읽어 daytrade 스냅샷을 만든다. 원본은 수정하지 않는다."""
    pn = pd.read_parquet(source, columns=COLS)
    pn = pn.sort_index()
    # 시가 0 은 거래 없음 -> 결측 처리. 종가 0 도 같다
    for c in ("open", "close"):
        pn[c] = pn[c].where(pn[c] > 0)
    snap = pn.astype({c: "float32" for c in COLS})
    out.parent.mkdir(parents=True, exist_ok=True)
    snap.to_parquet(out, compression="zstd")
    return out


def load(path: Path = SNAPSHOT) -> dict[str, pd.DataFrame]:
    """스냅샷을 읽어 date x ticker 와이드 프레임 dict 로 돌려준다.

    키: open close inst foreign 그리고 파생 피처
    - ret      당일 장중 수익률 close/open - 1 (목표 변수)
    - gap      시가 갭 open/prev_close - 1 (09:00 에 알 수 있음. 08:59 예상체결가로 근사)
    - prev_chg 전일 등락률
    - prev_inst prev_foreign 전일 기관/외국인 순매수 금액
    - liq20    전일까지 20일 평균 |기관|+|외국인| 순매수 금액 (유동성 대용)
    - prev_close 전일 종가 (가격 필터용)
    """
    if not path.exists():
        raise FileNotFoundError(f"{path} 가 없다. 먼저 python -m daytrade.data build")
    pn = pd.read_parquet(path)
    w = {c: pn[c].unstack("ticker").sort_index().astype("float64") for c in COLS}
    O, C, I, F = w["open"], w["close"], w["inst"], w["foreign"]
    prev_close = C.shift(1)
    w["prev_close"] = prev_close
    w["ret"] = C / O - 1
    w["gap"] = O / prev_close - 1
    w["prev_chg"] = (C / prev_close - 1).shift(1)
    w["prev_inst"] = I.shift(1)
    w["prev_foreign"] = F.shift(1)
    w["liq20"] = (I.abs() + F.abs()).rolling(20, min_periods=10).mean().shift(1)
    return w


def info(path: Path = SNAPSHOT) -> str:
    pn = pd.read_parquet(path)
    d = pn.index.get_level_values("date")
    return (f"{path.relative_to(ROOT)}: {len(pn):,} 행 {path.stat().st_size/1e6:.1f} MB "
            f"{d.min().date()}~{d.max().date()} {d.nunique()} 거래일 {pn.index.get_level_values('ticker').nunique()} 종목")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
    if cmd == "build":
        out = build()
        print("생성:", info(out))
    elif cmd == "info":
        print(info())
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
