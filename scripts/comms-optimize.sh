#!/usr/bin/env bash
# 通信优化模式：可改代码可跑验证，写入/命令/等价校验均经审批门确认。
# 用法：scripts/comms-optimize.sh [初始任务]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/comms-env.sh"

# 初始 prompt 经 @file 传入，规避 Windows argv 码页损坏（详见 comms-env.sh）。
# 不能用 exec：exec 会替换 shell 进程、丢失清理临时文件的 EXIT trap。
build_prompt_file_args "$@"

# 正向白名单（清单集中维护在 comms-env.sh 的 COMMS_OPTIMIZE_TOOLS）：
# 相比默认工具面多点亮 grep/find/ls 内建只读检索（免审批）。
"$ROOT/node_modules/.bin/pi" --approve \
  --tools "$COMMS_OPTIMIZE_TOOLS" \
  --append-system-prompt "$ROOT_W/config/prompts/optimize-mode.md" \
  "${pi_args[@]}"
