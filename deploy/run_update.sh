#!/usr/bin/env bash
# 장 마감 후 그날 일봉과 수급을 KRX 에서 받아 data/panel.parquet 에 덧붙이고 대시보드를 갱신한다.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
set -a; source .env; set +a          # KRX_ID KRX_PW
export TZ=Asia/Seoul
mkdir -p logs
python -u update_daily.py 2>&1 | tee -a "logs/update_$(date +%Y%m%d).log"
python -m dashboard.build >/dev/null 2>&1 || true
