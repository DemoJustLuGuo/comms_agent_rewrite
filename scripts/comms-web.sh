#!/usr/bin/env bash
# Web UI（pi-web）：浏览器访问 http://127.0.0.1:${COMMS_WEB_PORT:-30190}
# 会话数据与个人 pi 隔离（PI_CODING_AGENT_DIR → agent-home/）。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/comms-env.sh"

# pi-web 已从锁版 npm 依赖改为项目内 vendored 源码（vendor/pi-web，bun workspace 软链
# 进 node_modules）。构建产物 .next/ 不入库（gitignored），全新克隆需先构建一次；
# 改过 vendor/pi-web 源码后删掉 .next 即可触发重建。
#
# 构建走 Turbopack（next build，Next 16 默认），不用 package.json 的 `build` 脚本——
# 后者带 --webpack，其文件追踪会扫到 Windows 遗留 junction `%USERPROFILE%\Application Data`
# 并因 EPERM 失败（所有 Windows 机器都有该 junction，非本机特例）。Turbopack 无此问题。
PIWEB_DIR="$ROOT/vendor/pi-web"
if [ ! -f "$PIWEB_DIR/.next/BUILD_ID" ]; then
  echo "首次运行（或源码已改）：构建 pi-web（vendor/pi-web），耗时约 1~2 分钟……" >&2
  ( cd "$PIWEB_DIR" && "$ROOT/node_modules/.bin/next" build ) \
    || { echo "错误: pi-web 构建失败。请检查 vendor/pi-web 源码与依赖（bun install）。" >&2; exit 1; }
  echo "pi-web 构建完成。" >&2
fi

exec "$ROOT/node_modules/.bin/pi-web" --port "${COMMS_WEB_PORT:-30190}" --hostname 127.0.0.1 "$@"
