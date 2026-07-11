#!/usr/bin/env bash
# 共享环境装配：三个启动入口（comms-qa / comms-optimize / comms-web）source 本文件。
#   . "$SCRIPT_DIR/comms-env.sh"   # 之后 $ROOT 可用，env 已就绪
#
# 职责：定位项目根、加载 .env（密钥只走环境变量，不入库）、隔离 pi 配置目录、
# 指定 venv 解释器、按模板确保 agent-home/models.json 存在。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# .env：OPENAI_BASE_URL / OPENAI_API_KEY（gitignored，本机自备）
set -a
# shellcheck source=/dev/null
[ -f "$ROOT/.env" ] && . "$ROOT/.env"
set +a
if [ -z "${OPENAI_BASE_URL:-}" ] || [ -z "${OPENAI_API_KEY:-}" ]; then
  echo "错误: 未设置 OPENAI_BASE_URL / OPENAI_API_KEY。" >&2
  echo "请在项目根目录创建 .env（不入库）：" >&2
  echo "  OPENAI_BASE_URL=https://你的网关/v1" >&2
  echo "  OPENAI_API_KEY=你的key" >&2
  exit 1
fi

# Windows 形态的项目根（F:/...）：Git Bash 下 $ROOT 是 /f/... MSYS 路径，
# node/pi 无法解析；凡是传给 pi 的路径（env 与参数）一律用这个形态。
# 真正的 Linux/macOS 没有 cygpath，回退为原样。
ROOT_W="$(cygpath -m "$ROOT" 2>/dev/null || echo "$ROOT")"

# 与个人 pi 完全隔离：配置/会话/凭据全部落在项目内 agent-home/
export PI_CODING_AGENT_DIR="$ROOT_W/agent-home"
mkdir -p "$ROOT/agent-home"

# Git Bash（MSYS）会把以 / 开头的参数当 POSIX 路径转换成 Windows 路径，
# 导致 "/term FSPL" 变成 "F:/Git/term FSPL"、提示词模板无法展开——禁用该转换。
# 我们自己传给 pi 的路径已经过 cygpath 转成 Windows 形态，不受影响。
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

# 域工具统一使用项目 .venv 解释器
# shellcheck source=/dev/null
. "$SCRIPT_DIR/venv-python.sh"
set_comms_python_bin

# ---- 工具白名单（--tools 正向白名单）----
# pi 的 --tools 是全局 allowlist：内建、扩展、MCP 工具全部经它过滤（源码
# agent-session.js _refreshToolRegistry / isAllowedTool），不在名单里的工具即使
# 注册也不会出现。因此新增域工具（defs.ts）或 MCP server（.pi/mcp.json）后，
# 必须同步下面的清单，否则新工具在双模式下静默不可见。
#
# 内建工具共 7 个：read/bash/edit/write（默认启用）+ grep/find/ls（默认关闭，
# 白名单点亮，qa 靠它们检索 knowledge/）。
COMMS_DOMAIN_TOOLS="link_budget,path_loss,ber_snr,modulation,channel,channel_coding,capacity,pulse_shaping,ofdm,signal_analysis,frame_parser,comms_lint,online_knowledge,plot"
# equivalence_check 单列：会执行传入命令，qa 禁用、optimize 过审批门
COMMS_MATLAB_TOOLS="mcp_matlab_check_matlab_code,mcp_matlab_detect_matlab_toolboxes,mcp_matlab_evaluate_matlab_code,mcp_matlab_run_matlab_file,mcp_matlab_run_matlab_test_file"
COMMS_FETCH_TOOLS="mcp_fetch_fetch"
# qa：只读检索 + 计算/绘图域工具 + 网页抓取（fetch 过审批门）；无 bash/edit/write/等价校验/MATLAB
COMMS_QA_TOOLS="read,grep,find,ls,$COMMS_DOMAIN_TOOLS,$COMMS_FETCH_TOOLS"
# optimize：全能力面（grep/find/ls 免审批检索；bash/edit/write/equivalence_check/MCP 过审批门）
COMMS_OPTIMIZE_TOOLS="read,bash,edit,write,grep,find,ls,$COMMS_DOMAIN_TOOLS,equivalence_check,$COMMS_FETCH_TOOLS,$COMMS_MATLAB_TOOLS"

# models.json：按模板生成（baseUrl 来自 .env；apiKey 保持 $OPENAI_API_KEY 引用，不落盘）
if [ ! -f "$ROOT/agent-home/models.json" ]; then
  bun -e 'const fs=require("fs");const t=JSON.parse(fs.readFileSync("config/models.template.json","utf8"));t.providers["comms-gateway"].baseUrl=process.env.OPENAI_BASE_URL;fs.writeFileSync("agent-home/models.json",JSON.stringify(t,null,2));' \
    || { echo "错误: 生成 agent-home/models.json 失败（需要 bun）。" >&2; exit 1; }
  echo "已按模板生成 agent-home/models.json"
fi
