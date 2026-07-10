#!/usr/bin/env bash
# Web UI（pi-web）：浏览器访问 http://127.0.0.1:${COMMS_WEB_PORT:-30190}
# 会话数据与个人 pi 隔离（PI_CODING_AGENT_DIR → agent-home/）。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/comms-env.sh"

exec "$ROOT/node_modules/.bin/pi-web" --port "${COMMS_WEB_PORT:-30190}" --hostname 127.0.0.1 "$@"
