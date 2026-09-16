#!/bin/bash
# 安装/更新 investment-ai 的 launchd 调度（TASK-024）
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$PROJECT_DIR/launchd/com.investment-ai.daily.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.investment-ai.daily.plist"
LABEL="com.investment-ai.daily"

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/logs"

# 先卸载旧版本（不存在时忽略）
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl unload "$PLIST_DST" 2>/dev/null || true

cp "$PLIST_SRC" "$PLIST_DST"
# 若项目路径变化，这里可加 sed 替换绝对路径（当前按本机路径生成）

launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
launchctl enable "gui/$(id -u)/$LABEL"

echo "已安装: $LABEL"
echo "下次触发: 每天 20:00（睡眠错过则唤醒后补跑）"
echo "手动触发: launchctl kickstart gui/$(id -u)/$LABEL"
echo "查看状态: launchctl list | grep investment-ai"
