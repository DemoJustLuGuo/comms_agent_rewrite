#!/usr/bin/env bash
# 通信优化模式：可改代码可跑验证，写入/命令/等价校验均经审批门确认。
# 用法：scripts/comms-optimize.sh [初始任务]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/comms-env.sh"

exec "$ROOT/node_modules/.bin/pi" --approve \
  --append-system-prompt "$ROOT_W/config/prompts/optimize-mode.md" \
  "$@"
