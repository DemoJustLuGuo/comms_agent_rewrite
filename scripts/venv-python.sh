#!/usr/bin/env bash
# 共享助手：定位本项目 uv 虚拟环境解释器，并 export PYTHON_BIN。
# 供 comms-qa.sh / comms-optimize.sh / comms-web.sh / check-*.sh source 使用：
#   . "$SCRIPT_DIR/venv-python.sh"
#   set_comms_python_bin           # 缺 .venv 时报错引导 uv sync 并 exit 1
#
# 为什么必须显式 export PYTHON_BIN：pi 扩展经 spawn 拉起域工具时用
# process.env.PYTHON_BIN 优先选解释器（见 .pi/extensions/comms-tools/runner.ts）。
# 不设则退回探测 .venv；两处都指向同一 venv，保证工具/测试/验证用同一装齐依赖的解释器。

set_comms_python_bin() {
    local helper_dir project_root candidate
    helper_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    project_root="$(cd "$helper_dir/.." && pwd)"
    # Windows venv 布局在前（Git Bash），POSIX 布局在后
    for candidate in "$project_root/.venv/Scripts/python.exe" "$project_root/.venv/bin/python"; do
        if [ -x "$candidate" ]; then
            # 关键：node（pi 扩展）spawn 不认 MSYS 的 /f/... 路径，必须导出 Windows 形态
            # （F:/...）。真正的 Linux/macOS 没有 cygpath，回退原样。
            PYTHON_BIN="$(cygpath -m "$candidate" 2>/dev/null || echo "$candidate")"
            export PYTHON_BIN
            return 0
        fi
    done
    echo "错误: 未找到虚拟环境解释器（.venv/Scripts/python.exe 或 .venv/bin/python）" >&2
    echo "本智能体依赖项目 .venv 运行。请先在项目根目录执行：" >&2
    echo "  uv sync" >&2
    echo "（uv 会按 pyproject.toml/uv.lock 创建 .venv 并装齐 numpy/scipy/matplotlib/scikit-commpy/reedsolo）" >&2
    exit 1
}
