"""미국 시장 유니버스.

KRX 와 달리 미국은 종목별 기관/외국인 순매수 같은 무료 일별 수급 데이터가 없다.
그래서 국내 전략과 같은 신호를 쓸 수 없고 v1 은 '당일 등락률 상위 + 거래량' 을 대체 신호로 쓴다.
백테스트용 종목 목록은 유동성 높은 대형주 위주로 curated 한 것이라 실제 상장 전 종목이 아니다.
`kiwoom.client.KiwoomClient.us_price_surge` 로 실시간 상위 종목을 긁어와 확장할 수 있다 (usa20930).
"""
from __future__ import annotations

# 거래소 표기: NY(NYSE) ND(NASDAQ) NA(AMEX). (ticker, exchange) 튜플.
LARGE_CAP = [
    ("AAPL", "ND"), ("MSFT", "ND"), ("GOOGL", "ND"), ("GOOG", "ND"), ("AMZN", "ND"), ("NVDA", "ND"),
    ("META", "ND"), ("TSLA", "ND"), ("AVGO", "ND"), ("COST", "ND"), ("NFLX", "ND"), ("AMD", "ND"),
    ("PEP", "ND"), ("ADBE", "ND"), ("CSCO", "ND"), ("INTC", "ND"), ("QCOM", "ND"), ("TXN", "ND"),
    ("AMGN", "ND"), ("INTU", "ND"), ("ISRG", "ND"), ("BKNG", "ND"), ("VRTX", "ND"), ("REGN", "ND"),
    ("PANW", "ND"), ("SBUX", "ND"), ("GILD", "ND"), ("MU", "ND"), ("ADI", "ND"), ("LRCX", "ND"),
    ("KLAC", "ND"), ("SNPS", "ND"), ("CDNS", "ND"), ("MELI", "ND"), ("PDD", "ND"), ("ASML", "ND"),
    ("MRVL", "ND"), ("PYPL", "ND"), ("CRWD", "ND"), ("ABNB", "ND"), ("MDLZ", "ND"), ("ADP", "ND"),
    ("FTNT", "ND"), ("ORLY", "ND"), ("CTAS", "ND"), ("MNST", "ND"), ("KDP", "ND"), ("PCAR", "ND"),
    ("ROST", "ND"), ("IDXX", "ND"), ("EA", "ND"), ("DXCM", "ND"), ("WDAY", "ND"), ("ZS", "ND"),
    ("DDOG", "ND"), ("MDB", "ND"), ("TEAM", "ND"), ("ANSS", "ND"), ("FANG", "ND"), ("CEG", "ND"),
    ("BRK.B", "NY"), ("JPM", "NY"), ("V", "NY"), ("MA", "NY"), ("UNH", "NY"), ("JNJ", "NY"),
    ("XOM", "NY"), ("WMT", "NY"), ("PG", "NY"), ("HD", "NY"), ("CVX", "NY"), ("MRK", "NY"),
    ("ABBV", "NY"), ("KO", "NY"), ("BAC", "NY"), ("CRM", "NY"), ("TMO", "NY"), ("MCD", "NY"),
    ("ABT", "NY"), ("WFC", "NY"), ("DIS", "NY"), ("ACN", "NY"), ("LIN", "NY"), ("DHR", "NY"),
    ("VZ", "NY"), ("CMCSA", "NY"), ("NKE", "NY"), ("PM", "NY"), ("TXT", "NY"), ("ORCL", "NY"),
    ("NEE", "NY"), ("RTX", "NY"), ("UPS", "NY"), ("COP", "NY"), ("UNP", "NY"), ("LOW", "NY"),
    ("IBM", "NY"), ("SPGI", "NY"), ("CAT", "NY"), ("HON", "NY"), ("GS", "NY"), ("BA", "NY"),
    ("ELV", "NY"), ("DE", "NY"), ("AXP", "NY"), ("BLK", "NY"), ("SYK", "NY"), ("MS", "NY"),
    ("SCHW", "NY"), ("MDT", "NY"), ("GE", "NY"), ("PLD", "NY"), ("C", "NY"),
    ("LMT", "NY"), ("T", "NY"), ("MMC", "NY"), ("BSX", "NY"), ("SO", "NY"), ("CB", "NY"),
    ("ETN", "NY"), ("DUK", "NY"), ("AMT", "NY"), ("BMY", "NY"), ("PGR", "NY"), ("MO", "NY"),
    ("TJX", "NY"), ("CI", "NY"), ("ITW", "NY"), ("NOC", "NY"), ("EOG", "NY"), ("CVS", "NY"),
    ("SLB", "NY"), ("APD", "NY"), ("FDX", "NY"), ("EMR", "NY"), ("GD", "NY"), ("PSA", "NY"),
    ("MMM", "NY"), ("F", "NY"), ("GM", "NY"), ("DOW", "NY"), ("OXY", "NY"), ("HAL", "NY"),
    ("DAL", "NY"), ("UAL", "NY"), ("AAL", "NY"), ("CCL", "NY"), ("RCL", "NY"), ("NCLH", "NY"),
    ("UBER", "NY"), ("LYFT", "ND"), ("SNAP", "NY"), ("PINS", "NY"), ("ROKU", "ND"), ("SPOT", "NY"),
    ("SHOP", "NY"), ("SQ", "NY"), ("COIN", "ND"), ("HOOD", "ND"), ("SOFI", "ND"), ("PLTR", "NY"),
    ("SNOW", "NY"), ("NET", "NY"), ("RBLX", "NY"), ("U", "NY"), ("DKNG", "ND"), ("RIVN", "ND"),
    ("LCID", "ND"), ("NIO", "NY"), ("XPEV", "NY"), ("LI", "ND"), ("BABA", "NY"), ("JD", "ND"),
    ("MRNA", "ND"), ("BNTX", "ND"), ("PFE", "NY"), ("LLY", "NY"), ("NVO", "NY"), ("BIIB", "ND"),
]


def all_tickers() -> list[tuple[str, str]]:
    return list(dict.fromkeys(LARGE_CAP))
