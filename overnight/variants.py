"""페이퍼로 동시에 추적하는 선정 변형들.

입력: 키움 장중투자자별매매를 기관/외국인으로 합친 표 (index=code, columns name price chg net_i net_f)
출력: 선정된 행 (score 컬럼 포함)
"""
from __future__ import annotations

import pandas as pd

BASE = "base"


def _rank(df: pd.DataFrame, score: pd.Series, top: int) -> pd.DataFrame:
    out = df.assign(score=score).sort_values("score", ascending=False)
    return out.head(top)


def base(df, top=30, min_chg=0.03, min_price=1000.0):
    """채택안: 기관+외인 동시 순매수. 당일 +3% 이상. 금액 합계 상위."""
    m = (df.net_i > 0) & (df.net_f > 0) & (df.chg >= min_chg) & (df.chg < 0.29) & (df.price >= min_price)
    return _rank(df[m], df.net_i + df.net_f, top)


def surge(df, top=30, min_price=1000.0):
    """급등주: 동시 순매수 + 당일 +10% 이상 (상한가 제외)."""
    m = (df.net_i > 0) & (df.net_f > 0) & (df.chg >= 0.10) & (df.chg < 0.29) & (df.price >= min_price)
    return _rank(df[m], df.net_i + df.net_f, top)


def small(df, top=30, min_chg=0.03, min_price=1000.0):
    """소형주 가중: 순매수 금액을 주가로 나눠 정렬 (주식 수 기준)."""
    m = (df.net_i > 0) & (df.net_f > 0) & (df.chg >= min_chg) & (df.chg < 0.29) & (df.price >= min_price)
    return _rank(df[m], (df.net_i + df.net_f) / df.price, top)


def sellside(df, top=30, min_chg=0.03, min_price=1000.0):
    """동시 순매도 + 당일 +3% 이상. 수급 방향이 반대인데도 백테스트가 좋았던 변형."""
    m = (df.net_i < 0) & (df.net_f < 0) & (df.chg >= min_chg) & (df.chg < 0.29) & (df.price >= min_price)
    return _rank(df[m], -(df.net_i + df.net_f), top)


def top50(df, min_chg=0.03, min_price=1000.0):
    return base(df, top=50, min_chg=min_chg, min_price=min_price)


VARIANTS = {"surge": surge, "small": small, "sellside": sellside, "top50": top50}
