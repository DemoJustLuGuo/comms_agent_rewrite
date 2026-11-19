"""共享路径解析助手：信号类工具读取会话工作区文件用。

背景（2026-11-19 Web 工作台改造）：runner.ts 把子进程 cwd 固定为智能体仓库根
（防产物写进 node_modules），Web 会话的工作区（用户在侧栏选的目录）经
COMMS_WORKSPACE_ROOT 环境变量传递。工具收到相对路径时若只按 cwd 解析，
工作区里的文件会找不到——与 plot.py / comms_lint.py 的写路径是同一问题族的读方向。

约定：绝对路径原样使用；相对路径先按 COMMS_WORKSPACE_ROOT 解析，文件不存在
再回退智能体仓库根（兼容 TUI/脚本旧行为，仓库根 == 无 env 时的两个解析目标）。
"""
import os
from pathlib import Path

_AGENT_ROOT = Path(__file__).resolve().parent.parent


def workspace_root() -> Path:
    """会话工作区根；未注入 COMMS_WORKSPACE_ROOT 时为智能体仓库根。"""
    env_root = os.environ.get("COMMS_WORKSPACE_ROOT")
    return Path(env_root) if env_root else _AGENT_ROOT


def resolve_input_path(raw: str) -> Path:
    """解析工具入参里的文件路径：绝对路径原样；相对路径工作区优先、仓库兜底。"""
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    in_workspace = workspace_root() / candidate
    if in_workspace.exists():
        return in_workspace
    return _AGENT_ROOT / candidate
