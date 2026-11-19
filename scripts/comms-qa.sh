#!/usr/bin/env bash
# 通信问答（只读）模式：无 bash/edit/write 工具，equivalence_check 与 MATLAB（MCP）禁用。
# 用法：scripts/comms-qa.sh [初始问题]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/comms-env.sh"

# 初始 prompt 经 @file 传入，规避 Windows argv 码页损坏（详见 comms-env.sh）。
# 不能用 exec：exec 会替换 shell 进程、丢失清理临时文件的 EXIT trap。
build_prompt_file_args "$@"

# 正向白名单（清单集中维护在 comms-env.sh 的 COMMS_QA_TOOLS）：
# 只读边界靠"名单里没有执行面工具"保证——未来新增工具默认不进 qa，比黑名单更安全。
"$ROOT/node_modules/.bin/pi" --approve \
  --tools "$COMMS_QA_TOOLS" \
  --append-system-prompt "$ROOT_W/config/prompts/qa-mode.md" \
  "${pi_args[@]}"
