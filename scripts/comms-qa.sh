#!/usr/bin/env bash
# 通信问答（只读）模式：无 bash/edit/write 工具，equivalence_check 禁用。
# 用法：scripts/comms-qa.sh [初始问题]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/comms-env.sh"

exec "$ROOT/node_modules/.bin/pi" --approve \
  --exclude-tools bash,edit,write,equivalence_check \
  --append-system-prompt "$ROOT_W/config/prompts/qa-mode.md" \
  "$@"
