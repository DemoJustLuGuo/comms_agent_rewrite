#!/usr/bin/env bash
# 运行环境自检：依赖、隔离配置、扩展冒烟一次跑完。
# 用法：scripts/check-runtime.sh [--full]   # --full 额外跑 87+11 条 Python 单测
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

FAIL=0
ok()   { printf '[PASS] %s\n' "$1"; }
bad()  { printf '[FAIL] %s\n' "$1"; FAIL=1; }
warn() { printf '[WARN] %s\n' "$1"; }

# 1) 基础依赖
command -v git  >/dev/null 2>&1 && ok "git $(git --version | cut -d' ' -f3)"   || bad "缺 git"
command -v node >/dev/null 2>&1 && ok "node $(node --version)"                 || bad "缺 node（pi 运行时需要）"
command -v bun  >/dev/null 2>&1 && ok "bun $(bun --version)"                   || bad "缺 bun（扩展冒烟/生成 models.json 需要）"
command -v uv   >/dev/null 2>&1 && ok "uv $(uv --version | cut -d' ' -f2)"     || warn "缺 uv（重建 .venv 时需要）"

# 2) pi / pi-web（项目内锁定版本，不依赖全局）
if [ -x "$ROOT/node_modules/.bin/pi" ]; then
  ok "pi $("$ROOT/node_modules/.bin/pi" --version 2>/dev/null | head -1)（项目内锁定）"
else
  bad "缺项目内 pi：请运行 bun install"
fi
[ -x "$ROOT/node_modules/.bin/pi-web" ] && ok "pi-web（项目内锁定）" || warn "缺项目内 pi-web：bun install"

# 3) Python venv（域工具计算核）
# shellcheck source=/dev/null
if . "$SCRIPT_DIR/venv-python.sh" && set_comms_python_bin 2>/dev/null; then
  ok "venv 解释器 $("$PYTHON_BIN" --version 2>&1)"
else
  bad "缺 .venv：请运行 uv sync"
fi

# 4) 凭据与隔离配置
if [ -f "$ROOT/.env" ]; then
  ok ".env 存在（OPENAI_BASE_URL / OPENAI_API_KEY）"
else
  warn "缺 .env：模型对话不可用（工具冒烟不受影响）。格式见 scripts/comms-env.sh 报错提示"
fi
[ -f "$ROOT/agent-home/models.json" ] && ok "agent-home/models.json 存在" \
  || warn "agent-home/models.json 未生成（首次运行 comms-qa.sh/comms-optimize.sh 时自动生成）"
[ -f "$ROOT/.pi/settings.json" ] && ok ".pi/settings.json（默认模型 comms-gateway/deepseek-v4-flash）" || bad "缺 .pi/settings.json"

# 5) MATLAB（可选自备；缺失只 WARN 不 FAIL）
if [ -n "${PYTHON_BIN:-}" ]; then
  # Windows Python 不认 MSYS 的 /f/... 路径，sys.path 须用 Windows 形态
  ROOT_W="$(cygpath -m "$ROOT" 2>/dev/null || echo "$ROOT")"
  MATLAB_ROOT_FOUND="$("$PYTHON_BIN" -c "import sys; sys.path.insert(0, r'$ROOT_W/scripts'); import start_matlab_mcp as m; print(m.discover_matlab_root())" 2>/dev/null || true)"
  if [ -n "$MATLAB_ROOT_FOUND" ]; then
    ok "MATLAB 发现：$MATLAB_ROOT_FOUND"
    [ -f "$ROOT/bin/matlab-mcp-server.exe" ] || [ -f "$ROOT/bin/matlab-mcp-server" ] \
      && ok "matlab-mcp-server 二进制存在" || warn "缺 bin/matlab-mcp-server（获取方式见 bin/README.md），MATLAB 工具不可用"
    [ -f "$ROOT/.pi/mcp.json" ] && ok ".pi/mcp.json（matlab server 配置）" || bad "缺 .pi/mcp.json"
    grep -q "pi-mcp-extension" "$ROOT/.pi/settings.json" 2>/dev/null \
      && ok "pi-mcp-extension 已在项目 packages" || bad ".pi/settings.json 缺 pi-mcp-extension"
  else
    warn "未发现 MATLAB（MATLAB_ROOT/PATH/注册表均无）——MATLAB 工具自动不可用，不影响其他功能"
  fi
fi

# 6) 扩展冒烟（15 域工具桥 + 审批门 + 回滚）
echo "--- 扩展冒烟 ---"
bun "$ROOT/scripts/dev/smoke_extension.ts"  >/tmp/ck_ext.log 2>&1 && ok "域工具冒烟 16/16"   || { bad "域工具冒烟失败（详见 /tmp/ck_ext.log）"; }
bun "$ROOT/scripts/dev/smoke_gate.ts"       >/tmp/ck_gate.log 2>&1 && ok "审批门单测 8/8"     || { bad "审批门单测失败（详见 /tmp/ck_gate.log）"; }
bun "$ROOT/scripts/dev/smoke_checkpoint.ts" >/tmp/ck_ckpt.log 2>&1 && ok "回滚扩展冒烟 3/3"   || { bad "回滚冒烟失败（详见 /tmp/ck_ckpt.log）"; }

# 6) --full：完整 Python 单测（87 + 11）
if [ "${1:-}" = "--full" ]; then
  echo "--- Python 单测（--full）---"
  "$PYTHON_BIN" -X utf8 "$ROOT/scripts/tests/test_domain_tools.py"    >/tmp/ck_py1.log 2>&1 && ok "域工具单测 87 条" || bad "域工具单测失败（/tmp/ck_py1.log）"
  "$PYTHON_BIN" -X utf8 "$ROOT/scripts/tests/test_online_knowledge.py" >/tmp/ck_py2.log 2>&1 && ok "在线知识单测 11 条" || bad "在线知识单测失败（/tmp/ck_py2.log）"
fi

echo "---"
if [ "$FAIL" -eq 0 ]; then
  echo "自检通过。启动入口：scripts/comms-qa.sh · scripts/comms-optimize.sh · scripts/comms-web.sh"
else
  echo "自检存在 FAIL 项，请按提示修复。"
  exit 1
fi
