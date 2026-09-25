# aut.stock

한국 주식 자동매매 연구/운용 저장소. 답변은 한국어. 쉼표 없이 쓴다. 코드 생성 전 `date` 로 시간 확인.

## 데이터 (data/)
- `panel.parquet` KRX 일봉+수급 패널. index (date ticker) columns open close inst foreign. 2023-09-20 ~ 최근 (서버가 매일 16:40 갱신 후 `deploy/push_panel.sh` 로 이 브랜치에 자동 커밋. 작업 전 `git pull` 하면 최신). 코스피+코스닥 약 2,760 종목. inst/foreign 은 기관합계/외국인합계 순매수 금액 (원)
  - 읽기: `from fetch_data import load_panel; O, C, I, F = load_panel()` -> 각각 date x ticker 와이드 DataFrame
- `minute/YYYYMMDD.parquet` 키움 1분봉 (정규장 09:00~15:30). columns code time open high low close volume. 2026-06-25 부터 날짜별 후보 30종목만
  - 읽기: `from intraday.bars import load_days; m = load_days()`
- 원본 캐시 `price/` `flow/` 는 서버에만 있고 git 에는 없다

## 핵심 결론 (3년 일봉 검증)
- 한국 시장은 장중 (시가->종가) 평균 마이너스 오버나이트 (종가->익일 시가) 평균 플러스
- 채택 전략: 당일 기관+외국인 동시 순매수 & 당일 +3% 이상 & 금액 상위 30 을 종가 매수 -> 익일 시가 매도. 비용 18bp 후 일평균 +0.28% 샤프 3.7 (`python -m overnight.backtest`)
- 장중 롱 단타 (ORB) 는 108개 조합 전부 손실 -> 기각 (`intraday/`)
- 시가 대신 09:30 매도가 +0.19% 유리할 가능성 (분봉 60일. 페이퍼로 검증 중)

## 코드
- `kiwoom/` 키움 REST/웹소켓 클라이언트 (초당 1건 제한 자동 대기). 환경변수 KIWOOM_MODE KIWOOM_APPKEY KIWOOM_SECRET
- `overnight/` 채택 전략. `live.py buy|sell|eval|select|status`. 변형 4개를 페이퍼로 병행 기록 (`variants.py`)
- `backtest.py` 기관 연속 순매수 일봉 백테스트 (원래 질문. 결과: 단독으론 수익 없음)
- `fetch_data.py` KRX 전 종목 수집 (프로세스 하나만. --sleep 1. 차단되면 blockError). `update_daily.py` 하루치 증분
- `dashboard/build.py` -> https://ab.usb.kr 정적 페이지. `notify/kakao.py` 카톡 알림
- `deploy/` 오라클 VM systemd 타이머 (08:35 매도 / 09:36 eval / 15:21 매수 / 16:40 패널 갱신)

## 운용 상태
- 서버: 오라클 VM (ubuntu@relay, ~/aut.stock, venv ~/.venv). 키는 서버 .env 에만 둔다. 채팅에 키를 올리지 않는다
- 모의투자 페이퍼 모드. `results/overnight_paper.csv` 에 매일 기록. 실주문은 .env OVERNIGHT_ARGS 에 --real

## 미국주식 (overseas/) — 검증 완료, 기각

166종목 3년치 (`data/us_panel.parquet`) 로 검증한 결과 "당일 등락률 상위 + 거래량" 신호는 기각한다.
페이퍼/실전에 쓰지 않는다. 타이머 (`deploy/aut-us-*.timer`) 를 설치하지 않는다.

- 5bp (낙관) 비용: 일평균 +0.12% 샤프 1.40 -- 국내 (+0.28% 샤프 3.7) 보다 훨씬 약함
- 20bp (현실적 미국 환전+수수료) 비용: 일평균 -0.03% 연환산 -10% -- 이미 마이너스
- 30bp 비용: 연환산 -30% 최대낙폭 -67%
- 근본 원인: 미국은 국내와 달리 장중도 평균 플러스 (+0.024%/일) 라 "오버나이트만 골라야 한다"는
  전제가 국내만큼 강하지 않다. 오버나이트 기준선 자체도 +0.050%/일로 20bp 비용을 못 넘는다.
  "당일 급등주 고르기" 가 시장 평균 대비 알파를 주지 못한다는 뜻
- 재현: `python -m overseas.backtest --top 20 --min-chg 0.03 --cost-bps 20`
- 코드 (`kiwoom.client.us_*`, `overseas/`) 는 남겨둔다. 다른 신호 (예: 실제 미국 수수료 확인 후 재검증,
  다른 유니버스, 다른 필터) 를 시도할 때 재사용한다. 지금 신호 그대로 재시도하지 않는다

## 테스트
`python test_backtest.py && python -m intraday.test_intraday && python -m overseas.test_overseas`
