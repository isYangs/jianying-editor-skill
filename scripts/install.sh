#!/bin/bash
# jianying-editor-skill 安装脚本
set -e

INSTALL_DIR="${HOME}/.openclaw/skills"
SKILL_NAME="jianying-editor-skill"

echo "=== 安装 $SKILL_NAME ==="

mkdir -p "$INSTALL_DIR"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
rsync -avz --delete "$SCRIPT_DIR/../" "$INSTALL_DIR/$SKILL_NAME/"

echo "✅ 安装完成: $INSTALL_DIR/$SKILL_NAME"
echo "重启 OpenClaw 后即可使用"
