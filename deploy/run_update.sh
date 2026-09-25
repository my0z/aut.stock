#!/usr/bin/env bash
# 장 마감 후 그날 일봉과 수급을 KRX 에서 받아 data/panel.parquet 에 덧붙이고 대시보드를 갱신한다.
# 이어서 panel.parquet 를 기본 브랜치 (PANEL_BRANCH) 에 커밋/푸시해 다른 세션도 최신 수급을 쓰게 한다.
# 서버 체크아웃이 다른 브랜치여도 되도록 별도 worktree 에서 푸시한다.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
source .venv/bin/activate
set -a; source .env; set +a          # KRX_ID KRX_PW (+ PANEL_BRANCH)
export TZ=Asia/Seoul
mkdir -p logs
LOG="$REPO/logs/update_$(date +%Y%m%d).log"
python -u update_daily.py 2>&1 | tee -a "$LOG"
python -m dashboard.build >/dev/null 2>&1 || true

bash deploy/push_panel.sh >> "$LOG" 2>&1 || echo "panel 푸시 실패" >> "$LOG"
