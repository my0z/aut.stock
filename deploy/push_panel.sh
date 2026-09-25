#!/usr/bin/env bash
# data/panel.parquet 를 기본 브랜치 (PANEL_BRANCH) 에 커밋/푸시한다.
# 서버 체크아웃이 다른 브랜치여도 되도록 형제 폴더의 worktree 에서 작업한다.
set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
BRANCH="${PANEL_BRANCH:-claude/work-session-38u6d5}"
WT="$REPO/../aut.stock-panel-sync"
git fetch -q origin "$BRANCH" || exit 1
if [ ! -d "$WT/.git" ] && [ ! -f "$WT/.git" ]; then
    git worktree add -f --detach "$WT" "origin/$BRANCH"
fi
git -C "$WT" checkout -q --detach "origin/$BRANCH"
cp "$REPO/data/panel.parquet" "$WT/data/panel.parquet"
if git -C "$WT" diff --quiet -- data/panel.parquet; then
    echo "panel.parquet 변경 없음 (휴장 또는 이미 반영됨)"
    exit 0
fi
git -C "$WT" add data/panel.parquet
git -C "$WT" -c user.name="aut.stock bot" -c user.email="noreply@anthropic.com" \
    commit -q -m "Update KRX panel: $(date +%Y-%m-%d)"
for i in 1 2 3 4; do
    if git -C "$WT" push origin "HEAD:$BRANCH"; then
        echo "panel.parquet 푸시 완료 -> $BRANCH"
        exit 0
    fi
    echo "push 실패, 재시도 $i"
    sleep $((i * 5))
    git -C "$WT" fetch origin "$BRANCH"
    git -C "$WT" rebase "origin/$BRANCH" || { git -C "$WT" rebase --abort; git -C "$WT" checkout -q --detach "origin/$BRANCH"; cp "$REPO/data/panel.parquet" "$WT/data/panel.parquet"; git -C "$WT" add data/panel.parquet; git -C "$WT" -c user.name="aut.stock bot" -c user.email="noreply@anthropic.com" commit -q -m "Update KRX panel: $(date +%Y-%m-%d)"; }
done
echo "panel.parquet 푸시 최종 실패" 
exit 1
