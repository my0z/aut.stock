#!/usr/bin/env bash
# 미국주식 오버나이트 (실험). 사용법: run_overseas.sh buy | sell
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
set -a; source .env; set +a
mkdir -p logs
python -u -m overseas.live "$1" ${OVERSEAS_ARGS:-} 2>&1 | tee -a "logs/overseas_$(date -u +%Y%m%d).log"
