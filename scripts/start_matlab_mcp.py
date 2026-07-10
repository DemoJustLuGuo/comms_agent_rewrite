"""跨平台 MATLAB MCP 启动包装。

被两处以完全相同的方式拉起，保证「自检」与「pi 实际启动」路径一致：
  · .pi/mcp.json（pi-mcp-extension）的 matlab server：`python scripts/start_matlab_mcp.py`
  · scripts/check-runtime.sh 的 MATLAB 自检

为什么用 Python 包装，而不是在 mcp.json 里写死 MATLAB 路径：
MATLAB 安装位置因机而异；本包装按 MATLAB_ROOT / PATH / Windows 注册表的
优先级自动发现安装根目录，天然跨平台（Windows / Linux / macOS 共用一份启动逻辑）。

stdio 直通：本包装以「继承」的 stdin/stdout/stderr 启动真正的 MCP server，
不做任何捕获，因此 MCP 宿主 <-> server 的 stdio 管道透明传递。
POSIX 上用 os.execv 直接把本进程替换为 server（无残留子进程）；
Windows 上 execv 语义不可靠，改用 subprocess 继承 stdio 并等待。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def server_binary() -> Path:
    # Windows 为 .exe；Linux/macOS 为无扩展名同名可执行文件，同样放在 bin/。
    name = "matlab-mcp-server.exe" if os.name == "nt" else "matlab-mcp-server"
    return ROOT / "bin" / name


def _root_from_path() -> str:
    """PATH 上有 matlab 时，从 <root>/bin/matlab(.exe) 反推安装根目录。跨平台。"""
    exe = shutil.which("matlab")
    if not exe:
        return ""
    # <root>/bin/matlab → parents[1] 即 <root>；解析 symlink 以拿到真实安装位置。
    resolved = Path(exe).resolve()
    if resolved.parent.name.lower() == "bin":
        return str(resolved.parents[1])
    return ""


def _root_from_registry() -> str:
    """Windows 注册表 HKLM\\SOFTWARE\\MathWorks\\MATLAB\\<ver>\\MATLABROOT。仅 nt。

    存在多版本时选版本号最大的一个。非 Windows 或无注册表项返回空串。
    """
    if os.name != "nt":
        return ""
    try:
        import winreg
    except ImportError:
        return ""
    best_ver = None
    best_root = ""
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            base = winreg.OpenKey(hive, r"SOFTWARE\MathWorks\MATLAB")
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    ver = winreg.EnumKey(base, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(base, ver) as vkey:
                        root, _ = winreg.QueryValueEx(vkey, "MATLABROOT")
                except OSError:
                    continue
                if not root or not Path(root).exists():
                    continue
                # 版本号形如 "24.1"；按数值元组比较，取最大。
                try:
                    parsed = tuple(int(x) for x in ver.split("."))
                except ValueError:
                    parsed = (0,)
                if best_ver is None or parsed > best_ver:
                    best_ver = parsed
                    best_root = root
        finally:
            base.Close()
    return best_root


def discover_matlab_root() -> str:
    """按优先级发现 MATLAB 安装根目录：
      1. MATLAB_ROOT 环境变量（显式覆盖，最高优先）
      2. PATH 上的 matlab（跨平台）
      3. Windows 注册表 MATLABROOT（仅 nt）
    找不到返回空串。除 (1) 外都会校验目录存在。
    """
    env_root = os.environ.get("MATLAB_ROOT", "").strip()
    if env_root:
        return env_root
    for candidate in (_root_from_path(), _root_from_registry()):
        if candidate and Path(candidate).exists():
            return candidate
    return ""


def build_command() -> list:
    """返回启动命令，或在前置条件不满足时向 stderr 写原因并抛 SystemExit。"""
    matlab_root = discover_matlab_root()
    if not matlab_root:
        sys.stderr.write(
            "MATLAB_ROOT is not set and MATLAB was not auto-detected (PATH / Windows "
            "registry). Set MATLAB_ROOT to your MATLAB install dir, e.g. "
            "F:\\matlabR2024 (Windows) or /usr/local/MATLAB/R2024a (Linux).\n"
        )
        raise SystemExit(1)
    if not Path(matlab_root).exists():
        sys.stderr.write(f"MATLAB_ROOT points to a missing directory: {matlab_root}\n")
        raise SystemExit(1)
    exe = server_binary()
    if not exe.exists():
        sys.stderr.write(f"missing server executable: {exe}\n")
        raise SystemExit(1)
    return [str(exe), f"--matlab-root={matlab_root}",
            "--matlab-display-mode=nodesktop", "--disable-telemetry=true"]


def main() -> int:
    cmd = build_command()
    if os.name == "nt":
        # 继承 stdio（不重定向），MCP stdio 透传给 OpenCode。
        return subprocess.run(cmd, cwd=str(ROOT)).returncode
    os.chdir(str(ROOT))
    os.execv(cmd[0], cmd)  # 替换本进程；正常情况下不返回
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
