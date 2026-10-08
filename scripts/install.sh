#!/usr/bin/env bash
# sub2api-manager 安装器：把本仓库安装到 agent 的 skills 目录。
# 用法: bash install.sh [目标skills目录]
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)"
NAME="sub2api-manager"

pick_dir() {
  if [ -n "${1:-}" ]; then
    echo "$1"
    return
  fi
  for d in "$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.zcode/skills"; do
    if [ -d "$d" ]; then
      echo "$d"
      return
    fi
  done
  echo "$HOME/.agents/skills" # 标准默认
}

DEST_ROOT="$(pick_dir "${1:-}")"
DEST="$DEST_ROOT/$NAME"

if [ -d "$DEST/.git" ]; then
  echo "已存在 $DEST，执行 git pull 更新..."
  git -C "$DEST" pull --ff-only
elif [ -f "$DEST/SKILL.md" ]; then
  cp -R "$SRC/." "$DEST/"
  echo "已覆盖安装到 $DEST"
else
  mkdir -p "$DEST_ROOT"
  cp -R "$SRC/." "$DEST/"
  echo "已安装到 $DEST"
fi

chmod +x "$DEST/scripts/sub2api.py" 2>/dev/null || true
echo
echo "完成。配置一步（Agent 请直接执行并引导用户提供凭据）:"
echo "  python3 \"$DEST/scripts/sub2api.py\" login --email <邮箱> --password <密码>"
echo "  # 或: python3 \"$DEST/scripts/sub2api.py\" set-token --token <浏览器复制的Bearer token>"
