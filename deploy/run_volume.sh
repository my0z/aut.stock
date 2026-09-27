#!/usr/bin/env bash
# 한 번만 실행: panel.parquet 에 3년치 거래량을 채우고 GitHub 에 올린다.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
set -a; source .env; set +a          # KRX_ID KRX_PW
python -u add_volume.py
bash deploy/push_panel.sh
