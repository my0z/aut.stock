"""페이퍼 기록에서 휴장일 행을 지운다. 휴장일에 매수가 돌면 직전 거래일 수급으로 가짜 후보가 기록된다.

거래일은 KRX 패널 날짜와 키움 삼성전자 일봉 날짜 (오늘까지) 를 합쳐서 정한다.
그 기간 안인데 거래일이 아닌 날짜 = 휴장일로 보고 지운다. 원본은 overnight_paper.bak.csv 로 남긴다.
서버에서 .env 를 읽은 뒤 실행: python -m overnight.clean_holidays
"""
from __future__ import annotations

import shutil
from datetime import datetime

import pandas as pd

from .live import KST, PANEL, PAPER


def trading_days(client=None) -> set[str]:
    dates = pd.read_parquet(PANEL, columns=["close"]).index.get_level_values("date").unique()
    days = set(pd.to_datetime(dates).strftime("%Y-%m-%d"))
    try:
        if client is None:
            from kiwoom import KiwoomClient
            client = KiwoomClient()
        d = client.daily_chart("005930", max_pages=1)
        days |= set(d.index.strftime("%Y-%m-%d"))
    except Exception as e:  # noqa: BLE001
        print(f"키움 일봉 조회 실패. 패널 날짜만 쓴다: {e}")
    return days


def main(client=None) -> None:
    if not PAPER.exists():
        print("페이퍼 기록 없음")
        return
    trading = trading_days(client)
    today = datetime.now(KST).strftime("%Y-%m-%d")  # 오늘까지의 날짜 중 거래일이 아닌 것 (오늘 장중이면 오늘 일봉이 있다)
    df = pd.read_csv(PAPER, dtype=str, keep_default_na=False)
    bad = df["date"].le(today) & ~df["date"].isin(trading)
    print("날짜별 행 수:", df.groupby("date").size().to_dict())
    if not bad.any():
        print("휴장일 기록 없음")
        return
    shutil.copy(PAPER, PAPER.with_suffix(".bak.csv"))
    print("지우는 휴장일:", df[bad].groupby("date").size().to_dict())
    df[~bad].to_csv(PAPER, index=False)
    print(f"완료. 남은 행 {int((~bad).sum())} / 백업 {PAPER.with_suffix('.bak.csv')}")


if __name__ == "__main__":
    main()
