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
KAKAO_REST_KEY=카카오앱REST키            # 카톡 알림 (선택)
KRX_ID=KRX아이디                          # 일봉 자동 갱신 (16:40)
KRX_PW=KRX비밀번호
KAKAO_CLIENT_SECRET=클라이언트시크릿코드   # 플랫폼 키 > 클라이언트 시크릿 활성화 시
OVERNIGHT_ARGS="--top 30 --min-chg 0.03"  # 따옴표 필수. 실주문은 안에 --real 추가
X
chmod 600 .env

# 장중에 후보 확인
set -a; source .env; set +a
python -m overnight.live select

# 매일 자동 실행 (15:21 매수 / 08:35 매도)
sudo cp deploy/aut-*.service deploy/aut-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aut-buy.timer aut-sell.timer aut-eval.timer aut-update.timer
systemctl list-timers 'aut-*'
```

- 페이퍼 (기본): `results/overnight_paper.csv` 에 후보와 15:21 가격을 적고 다음날 08:35 에 시가로 평가해 수익률을 채운다
- 09:36 eval: 같은 종목을 09:30 에 팔았다면 얼마였는지도 기록한다 (분봉 60일 기준 시가 매도보다 +0.19% 유리했던 변형. 페이퍼로 검증 중)
- 실주문 (`--real`): 15:21 시장가 매수 (동시호가라 종가 체결) / 08:35 시장가 매도 (장전 동시호가라 시가 체결). 기록은 `results/overnight_log.csv`
- 로그: `logs/overnight_YYYYMMDD.log`

휴장일에는 후보가 비거나 주문이 거부되므로 자연히 건너뛴다. 모의투자로 2주 이상 돌려 백테스트와 차이를 확인한 뒤 실계좌로 옮긴다.

## 카카오톡 알림

1. https://developers.kakao.com → 내 애플리케이션 → 애플리케이션 추가 (이름 아무거나)
2. 앱 설정 → 플랫폼 → Web 플랫폼 등록: `https://localhost`
3. 제품 설정 → 카카오 로그인 → 활성화 ON. Redirect URI 에 `https://localhost/kakao` 등록
4. 카카오 로그인 → 동의항목 → "카카오톡 메시지 전송 (talk_message)" 을 선택 동의로 설정
5. 앱 키 → **REST API 키** 를 `.env` 의 `KAKAO_REST_KEY` 에 넣는다
6. 서버에서 인증 (1회)

```bash
set -a; source .env; set +a
python -m notify.kakao auth
```

출력된 주소를 휴대폰 브라우저에서 열어 로그인하고 동의하면 `https://localhost/kakao?code=...` 로 이동한다.
페이지는 안 열려도 되니 주소창의 `code=` 뒤 값을 복사해 터미널에 붙여넣는다. 카톡으로 "연결 완료" 가 오면 끝.

- 매수 직후: 종목 목록과 가격
- 다음날 08:35: 결과 (평균 수익률 상승/하락 상위 누적)
- 실행 실패 시: 오류 내용

## 웹 대시보드 (도메인 연결)

매 실행 후 `dashboard/index.html` 이 갱신된다. nginx 로 그대로 서빙한다.

```bash
sudo apt install -y nginx
sudo cp deploy/nginx-aut.conf /etc/nginx/sites-available/aut
sudo ln -sf /etc/nginx/sites-available/aut /etc/nginx/sites-enabled/aut
sudo rm -f /etc/nginx/sites-enabled/default
sudo chmod o+x /home/ubuntu                    # nginx 가 홈 아래를 읽을 수 있게
python -m dashboard.build                      # 첫 페이지 생성
sudo nginx -t && sudo systemctl restart nginx

# 오라클 VM 은 OS 방화벽이 80 을 막고 있다
sudo iptables -I INPUT 6 -p tcp --dport 80 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || sudo apt install -y iptables-persistent
```

오라클 클라우드 콘솔에서도 열어야 한다: 인스턴스 → 서브넷 → 보안 목록 → 수신 규칙 추가 (소스 0.0.0.0/0 TCP 포트 80).

도메인: DNS 에 A 레코드 `stock` -> VM 공인 IP 를 추가하고 `nginx-aut.conf` 의 `server_name` 을 맞춘다.
https: `sudo certbot --nginx -d ab.usb.kr` (certbot 이 없으면 `sudo apt install -y certbot python3-certbot-nginx`).

## 일봉 자동 갱신

`aut-update.timer` 가 평일 16:40 에 `update_daily.py` 를 돌려 그날 확정 시세와 기관·외국인 순매수를 `data/panel.parquet` 에 덧붙인다.
하루 요청 6번이라 KRX 차단 걱정이 없다. 대시보드에 데이터 기간과 "잠정 선정 vs 확정 후보 겹침" 이 표시된다.
백테스트를 최신으로 다시 돌리려면 `python -m overnight.backtest` 를 실행한다.
