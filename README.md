# 기관 연속 순매수 백테스트

최근 3년간 기관이 3일 연속 순매수한 종목을 다음 거래일에 매수해 5거래일 보유했을 때의
승률과 평균 수익률을 계산한다. 시나리오 B 는 같은 기간 외국인도 매일 순매수한 조건을 추가한다.

## 실행 순서

```bash
pip install -r requirements.txt
export KRX_ID=...   # KRX 데이터포털 계정 (pykrx 1.2.x 는 로그인이 필요할 수 있음)
export KRX_PW=...
python fetch_data.py            # 코스피 + 코스닥 전 종목 3년치 수집 -> data/ 캐시
python backtest.py --cost-bps 24
```

빠른 확인용:

```bash
python fetch_data.py --limit 30   # 30종목만
python backtest.py
python test_backtest.py           # 합성 데이터 로직 검증
```

## 규칙

| 항목 | 기본값 | 옵션 |
|---|---|---|
| 시그널 | 기관합계 순매수 금액 > 0 이 3거래일 연속 | `--streak N` |
| 진입 | 시그널 다음 거래일 시가 | `--entry close` |
| 청산 | 진입일 + 5거래일 종가 | `--hold H` |
| 비용 | 0bp | `--cost-bps 24` (수수료 0.03%×2 + 거래세 0.18%) |
| 겹치는 시그널 | 매일 독립 트레이드로 집계 | `--exclusive` (연속 구간 첫날만) |
| 저가주 필터 | 없음 | `--min-price 1000` |

시나리오 B 는 외국인합계 순매수도 같은 3일 동안 매일 양수인 경우다.

## 출력

- 콘솔: 시나리오별 트레이드 수 / 승률 / 평균 / 중앙값 / 표준편차 / 평균 승·패 / 손익비 / t 통계량 / 연도별 분해
- `results/trades_*.csv`: 개별 트레이드 (시그널일 진입일 청산일 진입가 청산가 수익률)

## 주의

- 순매수는 금액 기준이다. 수량 기준을 원하면 `fetch_data.py` 의 `get_market_trading_value_by_date` 를
  `get_market_trading_volume_by_date` 로 바꾼다.
- 현재 상장 종목 기준으로 유니버스를 잡으므로 상장폐지 종목이 빠지는 생존 편향이 있다.
- 3년 전 종목 코드 목록을 함께 쓰려면 `ticker_universe(start)` 결과를 합치면 된다.
- 전 종목 수집은 종목당 2회 요청이라 약 2500종목 기준 30분 안팎 걸린다. 재실행 시 캐시된 종목은 건너뛴다.

## 수집한 데이터를 저장소에 올려 세션에서 결과를 받는 방법

```bash
python fetch_data.py                 # 1. 수집 (data/price data/flow)
python pack_data.py                  # 2. data/panel.parquet 한 파일로 압축
git add data/panel.parquet  # 3. 이 파일만 커밋 (나머지 data/ 는 gitignore)
git commit -m "Add KRX panel data"
git push
```

푸시 후 세션에 알려주면 `python backtest.py --cost-bps 24` 를 실행해 두 시나리오 결과를 산출한다.
