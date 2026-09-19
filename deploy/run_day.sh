#!/usr/bin/env bash
# 오라클 VM 에서 매 거래일 08:50 KST 에 systemd 타이머로 실행된다.
# 1) 페이퍼 또는 실주문 ORB 러너를 장 마감까지 돌리고
# 2) 마감 후 오늘 분봉을 REST 로 다시 받아 누락을 보정한다
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
set -a; source .env; set +a          # KIWOOM_MODE KIWOOM_APPKEY KIWOOM_SECRET (+ LIVE_ARGS)
export TZ=Asia/Seoul
dow=$(date +%u)
if [ "$dow" -ge 6 ]; then echo "주말. 건너뜀"; exit 0; fi
mkdir -p logs
python -m intraday.live ${LIVE_ARGS:-} 2>&1 | tee -a "logs/live_$(date +%Y%m%d).log"
python -m intraday.collect today 2>&1 | tee -a "logs/collect_$(date +%Y%m%d).log"
