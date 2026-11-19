#!/usr/bin/env bash
# 真实项目验证入口（Git Bash / Linux / macOS 通用）。
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REAL_PROJECT="$PROJECT_ROOT/real_projects/ModulationPy"
if [ "$#" -gt 0 ]; then
  if [ "$#" -ne 2 ] || [ "$1" != "--project" ]; then
    echo "用法: bash scripts/check-real-project.sh [--project 工作区目录]" >&2
    exit 2
  fi
  REAL_PROJECT="$2"
fi
# 定位 uv 虚拟环境解释器并 export PYTHON_BIN（缺 .venv 时报错引导 uv sync 并退出）。
# shellcheck source=/dev/null
. "$SCRIPT_DIR/venv-python.sh"
set_comms_python_bin
PYTHON="$PYTHON_BIN"
if [ ! -d "$REAL_PROJECT" ]; then
  echo "错误: 未找到真实通信项目 real_projects/ModulationPy。" >&2
  echo "请先从 GitHub clone ModulationPy 到该目录。" >&2
  exit 1
fi
if command -v git >/dev/null 2>&1; then
  if ! GIT_OUTPUT="$(git -C "$REAL_PROJECT" status --short 2>&1)"; then
    echo "警告: 真实项目 Git 状态不可读，后续优化后可能无法审阅 diff。" >&2
    echo "$GIT_OUTPUT" >&2
    if printf '%s' "$GIT_OUTPUT" | grep -q "dubious ownership"; then
      echo "处理方式: 确认该目录可信后运行:" >&2
      echo "  git config --global --add safe.directory $REAL_PROJECT" >&2
    fi
    echo "" >&2
  fi
else
  echo "警告: 未找到 git，优化后将无法用 git diff/status 审阅真实项目改动。" >&2
  echo "" >&2
fi
cd "$REAL_PROJECT"
echo "Validation target: $(pwd)"
echo "Running ModulationPy tests..."
"$PYTHON" -m unittest tests.py
echo "ModulationPy real project check passed."
