#!/bin/bash
# 安装/更新 investment-ai 的 launchd 调度（TASK-024 + V0.5 weekly）
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/logs"

install_one() {
    local name="$1"
    local src="$PROJECT_DIR/launchd/com.investment-ai.${name}.plist"
    local dst="$HOME/Library/LaunchAgents/com.investment-ai.${name}.plist"
    local label="com.investment-ai.${name}"

    launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
    launchctl unload "$dst" 2>/dev/null || true

    cp "$src" "$dst"
    launchctl bootstrap "gui/$(id -u)" "$dst"
    launchctl enable "gui/$(id -u)/$label"
    echo "已安装: $label"
}

install_one daily
install_one weekly

echo "daily : 每天 09:00 与 22:00（--force 穿透 skip 门，靠 UNIQUE 缓存幂等）"
echo "weekly: 每周日 21:30（本周已生成则幂等跳过 L3 调用）"
echo "手动触发: launchctl kickstart gui/$(id -u)/com.investment-ai.daily"
echo "查看状态: launchctl list | grep investment-ai"
