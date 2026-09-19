# 오라클 VM 배포

```bash
# 1. 코드와 환경
cd ~ && git clone https://github.com/my0z/aut.stock && cd aut.stock
git checkout claude/work-session-38u6d5
sudo apt install -y python3-venv
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. 키 (파일 권한 600. 절대 커밋하지 않는다)
cat > .env <<'X'
KIWOOM_MODE=demo            # 모의투자. 실계좌는 real
KIWOOM_APPKEY=발급받은앱키
KIWOOM_SECRET=발급받은시크릿
LIVE_ARGS=--top 30 --max-pos 5   # 실주문은 여기에 --real 추가
X
chmod 600 .env

# 3. 동작 확인 (장중에)
set -a; source .env; set +a
python -m intraday.live --codes 005930,000660 --until 09:10

# 4. 매일 자동 실행
sudo cp deploy/aut-live.service deploy/aut-live.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aut-live.timer
systemctl list-timers aut-live.timer
```

로그는 `logs/` 와 `results/live_YYYYMMDD.csv` 에 쌓인다. 분봉은 `data/minute/` 에 날짜별 parquet 로 쌓인다.

모의투자에서 최소 2주 페이퍼 결과를 보고 `--real` 을 붙인다.
