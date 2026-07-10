#!/usr/bin/env bash
# 通信问答（只读）模式：无 bash/edit/write 工具，equivalence_check 与 MATLAB（MCP）禁用。
# 用法：scripts/comms-qa.sh [初始问题]
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/comms-env.sh"

# MATLAB MCP 工具名单与 .pi/mcp.json 的 matlab server 对应（mcp_<server>_<tool>）。
# 新增 MCP server / server 工具变化时，需同步此排除名单（qa 是只读边界，禁一切执行面）。
MATLAB_TOOLS="mcp_matlab_check_matlab_code,mcp_matlab_detect_matlab_toolboxes,mcp_matlab_evaluate_matlab_code,mcp_matlab_run_matlab_file,mcp_matlab_run_matlab_test_file"

exec "$ROOT/node_modules/.bin/pi" --approve \
  --exclude-tools "bash,edit,write,equivalence_check,$MATLAB_TOOLS" \
  --append-system-prompt "$ROOT_W/config/prompts/qa-mode.md" \
  "$@"
