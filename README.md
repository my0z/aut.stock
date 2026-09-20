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

### KRX 가 IP 를 차단했을 때 (blockError)

투자자 데이터는 키움 REST API 로도 받을 수 있다. 키움 앱키가 있으면 KRX 없이 빠진 종목을 채운다.

```bash
export KIWOOM_MODE=demo KIWOOM_APPKEY=... KIWOOM_SECRET=...
python fetch_data_kiwoom.py          # data/flow 가 없는 종목만
python pack_data.py
```

KRX 와 키움의 금액 단위가 다를 수 있다. 일봉 백테스트는 부호만 쓰므로 영향이 없고
유니버스 정렬만 섞인다. 통일하려면 `python fetch_data_kiwoom.py --all` 로 전부 키움 기준으로 받는다.

---

# 오버나이트 수급 전략 (채택)

3년 KRX 데이터로 확인한 사실: 한국 시장은 장중 (시가->종가) 이 평균 마이너스이고 오버나이트 (종가->익일 시가) 가 플러스다.
당일 매수 당일 매도 롱 단타는 이 역풍을 맞는다. 그래서 종가에 사서 익일 시가에 파는 전략을 채택했다.

| 항목 | 규칙 |
|---|---|
| 후보 | 당일 기관합계와 외국인합계 모두 순매수 (금액) |
| 필터 | 당일 등락률 +3% 이상. 가격 1,000원 이상 |
| 선정 | 기관+외국인 순매수 금액 합계 상위 30 균등 배분 |
| 진입 | 15:21 시장가 -> 동시호가 종가 체결 |
| 청산 | 익일 08:35 시장가 -> 장전 동시호가 시가 체결 |

백테스트 (2023-09~2026-09 비용 18bp): 일평균 +0.28% 일승률 65% 샤프 3.7 최대낙폭 -12.7% 연도별 전부 플러스.
`python -m overnight.backtest` 로 재현한다. 주의: 백테스트는 마감 후 확정 수급을 쓰지만 실전은 15:20 잠정치를 쓴다.
그 차이는 모의투자 페이퍼 기록으로 확인한다.

```bash
python -m overnight.backtest --top 30 --min-chg 0.03   # 백테스트
python -m overnight.live select                        # 지금 후보 보기 (장중)
python -m overnight.live buy                           # 페이퍼 매수 기록 (15:20 께)
python -m overnight.live sell                          # 페이퍼 평가 (다음날 08:35 께)
python -m overnight.live buy --real                    # 실주문
```

VM 자동 실행은 `deploy/README.md`.

# 시가 범위 돌파 단타 (검증 결과 기각)

`intraday/` 의 ORB 전략은 60거래일 1분봉으로 108개 파라미터 조합을 돌렸으나 전부 손실이었다 (평균 -0.4%/트레이드).
같은 유니버스를 09:30 에 사서 15:10 에 팔기만 해도 하루 -0.7% 였다. 코드는 분봉 수집기와 함께 남겨 둔다.

## (참고) ORB 구성

전략은 **시가 범위 돌파 (ORB)** 다. 자세한 규칙과 근거는 `intraday/strategy.py` 상단 주석에 있다.

| 항목 | 기본값 |
|---|---|
| 유니버스 | 전일 기관+외국인 동시 순매수 종목 중 거래대금 상위 30 |
| 시가 범위 | 09:00~09:30 1분봉 고가/저가 |
| 진입 | 09:30~14:00 에 종가가 범위 고가 돌파 + 거래량 1.5배 + VWAP 위 |
| 손절 / 익절 | -2% (또는 범위 저가) / +3% |
| 시간 청산 | 15:10 |
| 보유 한도 | 5 종목 균등. 일일 손실 -3% 면 신규 진입 중단 |

## 구성

```
kiwoom/client.py        토큰 발급 / REST 호출 / 분봉·일봉 / 주문 / 잔고
kiwoom/stream.py        웹소켓 체결(0B) 스트림. 재접속 포함
intraday/bars.py        틱 -> 1분봉. data/minute/YYYYMMDD.parquet
intraday/strategy.py    ORB 엔진 (백테스트와 실전이 같은 코드)
intraday/universe.py    유니버스 선정 (키움 API / KRX 패널)
intraday/collect.py     분봉 수집 (history / today / stream)
intraday/backtest_intraday.py  분봉 백테스트
intraday/live.py        실시간 러너 (페이퍼 기본. --real 로 실주문)
deploy/                 오라클 VM systemd 타이머
```

## 순서

```bash
export KIWOOM_MODE=demo KIWOOM_APPKEY=... KIWOOM_SECRET=...
python -m intraday.test_intraday                    # 로직 검증
python -m intraday.collect history --days 60        # 과거 분봉 수집 (KRX 패널 필요)
python -m intraday.backtest_intraday --cost-bps 28  # 분봉 백테스트
python -m intraday.live                             # 장중 페이퍼 트레이딩
python -m intraday.live --real                      # 모의투자 계좌 실주문 (KIWOOM_MODE=demo)
```

VM 상시 실행은 `deploy/README.md` 를 본다.
