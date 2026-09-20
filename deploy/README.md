# 오라클 VM 배포 (오버나이트 수급 전략)

```bash
cd ~/aut.stock && git pull
source ~/.venv/bin/activate && pip install -r requirements.txt
ln -sfn ~/.venv .venv                 # run_overnight.sh 가 .venv 를 찾는다

# 키 (파일 권한 600. 절대 커밋하지 않는다)
cat > .env <<'X'
KIWOOM_MODE=demo                       # 모의투자. 실계좌는 real
KIWOOM_APPKEY=발급받은앱키
KIWOOM_SECRET=발급받은시크릿
OVERNIGHT_ARGS=--top 30 --min-chg 0.03  # 실주문은 여기에 --real 추가
X
chmod 600 .env

# 장중에 후보 확인
set -a; source .env; set +a
python -m overnight.live select

# 매일 자동 실행 (15:21 매수 / 08:35 매도)
sudo cp deploy/aut-buy.service deploy/aut-buy.timer deploy/aut-sell.service deploy/aut-sell.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aut-buy.timer aut-sell.timer
systemctl list-timers 'aut-*'
```

- 페이퍼 (기본): `results/overnight_paper.csv` 에 후보와 15:21 가격을 적고 다음날 08:35 에 시가로 평가해 수익률을 채운다
- 실주문 (`--real`): 15:21 시장가 매수 (동시호가라 종가 체결) / 08:35 시장가 매도 (장전 동시호가라 시가 체결). 기록은 `results/overnight_log.csv`
- 로그: `logs/overnight_YYYYMMDD.log`

휴장일에는 후보가 비거나 주문이 거부되므로 자연히 건너뛴다. 모의투자로 2주 이상 돌려 백테스트와 차이를 확인한 뒤 실계좌로 옮긴다.
