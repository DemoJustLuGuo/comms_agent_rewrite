# bin/

## matlab-mcp-server.exe

- 来源：MathWorks 官方 MATLAB MCP Server，server 自报标识为
  `github.com/matlab/matlab-mcp-server v0.11.1`。
- 用途：为 pi 提供 MATLAB MCP 工具。由 `pi-mcp-extension`（`.pi/mcp.json` 的
  `matlab` server）经跨平台包装脚本 `scripts/start_matlab_mcp.py` 拉起，
  注册为 `mcp_matlab_*` 工具（如 `mcp_matlab_evaluate_matlab_code`；
  MCP 协议原生名为 `evaluate_matlab_code`）。
- MATLAB 安装位置自动发现（优先级：`MATLAB_ROOT` 环境变量 → PATH 上的 matlab →
  Windows 注册表），一般无需手工设置。
- 该 exe 约 19 MB，不入 git（见仓库根目录 `.gitignore`）。文件缺失时，
  从 MathWorks 官方渠道重新下载 v0.11.1（或更新版本）放入本目录，然后运行
  `scripts/check-runtime.sh` 验证（MATLAB 段四项应为 PASS）。
