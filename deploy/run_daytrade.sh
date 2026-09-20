#!/usr/bin/env bash
# daytrade 러너. 사용: run_daytrade.sh buy|sell|eval  (.env 의 DAYTRADE_ARGS 에 --real 등)
# eval 뒤에는 오늘 매수 종목의 1분봉도 받아 둔다 (daytrade.collect today)
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && source .env; set +a
source .venv/bin/activate
mkdir -p logs
LOG="logs/daytrade_$(date +%Y%m%d).log"
# shellcheck disable=SC2086
python -m daytrade.live "$1" ${DAYTRADE_ARGS:-} >> "$LOG" 2>&1
if [ "$1" = "eval" ]; then
  python -m daytrade.collect today >> "$LOG" 2>&1 || true
fi
