#!/usr/bin/env bash
# 오버나이트 수급 전략. systemd 타이머가 평일 15:21 (buy) 와 08:35 (sell) 에 호출한다.
# 사용법: run_overnight.sh buy | sell
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
set -a; source .env; set +a          # KIWOOM_MODE KIWOOM_APPKEY KIWOOM_SECRET KAKAO_* (+ OVERNIGHT_ARGS)
export TZ=Asia/Seoul
mkdir -p logs
python -u -m overnight.live "$1" ${OVERNIGHT_ARGS:-} 2>&1 | tee -a "logs/overnight_$(date +%Y%m%d).log"
python -m dashboard.build >/dev/null 2>&1 || true   # 웹 대시보드 갱신
