#!/usr/bin/env bash
# daytrade 러너. 사용: run_daytrade.sh buy|sell|eval  (.env 의 DAYTRADE_ARGS 에 --real 등)
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; [ -f .env ] && source .env; set +a
source .venv/bin/activate
mkdir -p logs
# shellcheck disable=SC2086
exec python -m daytrade.live "$1" ${DAYTRADE_ARGS:-} >> "logs/daytrade_$(date +%Y%m%d).log" 2>&1
