#!/usr/bin/env bash
# daytrade 러너. 사용: run_daytrade.sh buy|sell|eval  (.env 의 DAYTRADE_ARGS 에 --real 등)
# eval 뒤에는 오늘 매수 종목의 1분봉도 받아 둔다 (daytrade.collect today)
# 끝나면 웹 대시보드 (dd.usb.kr) 를 다시 만든다. 러너가 실패해도 페이지는 갱신하고 종료 코드는 그대로 돌려준다
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && source .env; set +a
source .venv/bin/activate
mkdir -p logs
LOG="logs/daytrade_$(date +%Y%m%d).log"
rc=0
# shellcheck disable=SC2086
python -m daytrade.live "$1" ${DAYTRADE_ARGS:-} >> "$LOG" 2>&1 || rc=$?
if [ "$1" = "eval" ]; then
  python -m daytrade.collect today >> "$LOG" 2>&1 || true
fi
python -m daytrade.web >> "$LOG" 2>&1 || true
exit "$rc"
