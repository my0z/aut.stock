#!/usr/bin/env bash
# 장 마감 후 그날 일봉과 수급을 KRX 에서 받아 data/panel.parquet 에 덧붙이고 대시보드를 갱신한다.
# 이어서 panel.parquet 를 커밋/푸시해 GitHub 도 매일 최신 수급을 반영하게 한다.
set -euo pipefail
cd "$(dirname "$0")/.."
source .venv/bin/activate
set -a; source .env; set +a          # KRX_ID KRX_PW
export TZ=Asia/Seoul
mkdir -p logs
LOG="logs/update_$(date +%Y%m%d).log"
python -u update_daily.py 2>&1 | tee -a "$LOG"
python -m dashboard.build >/dev/null 2>&1 || true

if ! git diff --quiet -- data/panel.parquet || ! git diff --cached --quiet -- data/panel.parquet; then
    git add data/panel.parquet
    git -c user.name="aut.stock bot" -c user.email="noreply@anthropic.com" \
        commit -m "Update KRX panel: $(date +%Y-%m-%d)" >> "$LOG" 2>&1
    for i in 1 2 3 4; do
        if git push >> "$LOG" 2>&1; then
            break
        fi
        echo "push 실패, 재시도 $i" >> "$LOG"
        sleep $((i * 5))
        git pull --rebase >> "$LOG" 2>&1 || true
    done
else
    echo "panel.parquet 변경 없음 (휴장 또는 이미 반영됨)" >> "$LOG"
fi
