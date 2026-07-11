# 通信系统智能体（pi 运行时）

基于 [pi coding agent](https://github.com/earendil-works/pi)（项目内锁定 0.80.6）重写的通信系统智能体。
从 OpenCode 版（`../agent_rewrite/comms-agent/`）迁移而来：Python 计算核与知识库原样平移，
桥接层收敛为单个声明式扩展，审批与回滚改用 pi 官方扩展机制实现。

## 快速开始

```bash
# 0) 依赖：git + node ≥22 + bun + uv +（Windows 需 Git Bash）
bun install          # 安装项目内 pi / pi-web（锁定版本，不依赖全局）
uv sync              # 创建 .venv 并装齐 numpy/scipy/matplotlib/scikit-commpy/reedsolo

# 1) 凭据（不入库）：项目根创建 .env
#    OPENAI_BASE_URL=https://你的网关/v1
#    OPENAI_API_KEY=你的key

# 2) 自检
scripts/check-runtime.sh --full

# 3) 启动（三选一）
scripts/comms-qa.sh          # 问答模式：只读，无 bash/edit/write
scripts/comms-optimize.sh    # 优化模式：可改码可验证，写入/命令经审批弹窗
scripts/comms-web.sh         # Web UI：http://127.0.0.1:30190
```

## 目录结构

```
.pi/
├── extensions/comms-tools/   # 20 个域工具：defs.ts 声明表 + runner.ts 公共桥（spawn Python）
├── extensions/approval-gate.ts   # 审批门：bash/edit/write/equivalence_check 执行前须确认，无 UI 时 fail-closed
├── extensions/git-checkpoint.ts  # 回滚：每次 edit/write 前按文件所属仓库打快照，/rollback 恢复
├── prompts/                  # 12 个 /命令 模板（/term /rf-calc /fec /diagnose /report /optimize-loop …）
├── mcp.json                  # MCP server：matlab（mcp_matlab_*）+ fetch（mcp_fetch_fetch，网页抓取，对应旧栈 webfetch）
└── settings.json             # 默认模型 + 项目级 pi 包（pi-mcp-extension）
config/
├── models.template.json      # provider 模板（baseUrl 来自 .env；key 只走 $OPENAI_API_KEY）
└── prompts/                  # qa / optimize 双模式人设（经 --append-system-prompt 注入）
tools/                        # 20 个 Python 计算核（numpy/scipy，与运行时无关）
knowledge/                    # 术语速查 / 原理100问 / 工程评估速查 / 故障特征速查（grep/read 检索）
scripts/                      # 启动入口 / 自检 / 真实项目验证 / dev 冒烟
agent-home/                   # pi 配置与会话（PI_CODING_AGENT_DIR 指向，gitignored）
real_projects/ModulationPy/   # 优化目标（独立 git 仓库，gitignored）
```

## 与个人 pi 的隔离

启动脚本把 `PI_CODING_AGENT_DIR` 指向项目内 `agent-home/`——models.json、auth、会话
全部落在项目里；扩展/模板只放项目级 `.pi/`（经 trust 加载）。你的全局 `~/.pi` 不被读写
（已知上游 0.80.6 瑕疵：会在 `~/.pi/agent/` 落一个空 auth.json，无害）。

## 双模式与安全

- **双模式均为 `--tools` 正向白名单**（清单集中在 `scripts/comms-env.sh`；pi 的 `--tools` 全局过滤内建/扩展/MCP 工具）：
  - **comms-qa**：只读面——read + grep/find/ls（知识检索）+ 19 个计算/绘图/诊断域工具 + fetch；无 bash/edit/write/equivalence_check/MATLAB，模型根本没有执行面工具。
  - **comms-optimize**：全能力面（33 工具，含内建 grep/find/ls 免审批检索），审批门扩展在高危工具执行前弹确认（TUI 原生弹窗；pi-web 经
    `extension_ui_request/response` 透传到浏览器）；每次写入前自动打 git 快照，`/rollback` 一键回退。
  - 新增域工具或 MCP server 时**必须同步 comms-env.sh 的白名单**，否则新工具静默不可见。
- 密钥只走环境变量；`equivalence_check` 会执行传入命令，已纳入审批门管控。

## 验证

```bash
scripts/check-runtime.sh --full        # 依赖 + 隔离配置 + 扩展冒烟(21/8/3) + Python 单测(106+11)，离线
scripts/validate-tool-routing.sh       # 模型端路由验证：21 例逐个真实调用（走 deepseek，需 .env；--quick 跳过联网/MATLAB 例）
scripts/check-real-project.sh          # ModulationPy tests.py（优化闭环的行为等价基线）
```

## 已知边界

- **MATLAB**：经 `pi-mcp-extension`（项目级锁定 1.5.0）+ MathWorks 官方 matlab-mcp-server 接入，
  注册为 `mcp_matlab_*` 五个工具（evaluate / check / run_file / run_test_file / detect_toolboxes），
  全部过审批门；MATLAB 安装自动发现（MATLAB_ROOT → PATH → 注册表），本机无 MATLAB 时自动降级为不可用
  （自检 WARN 不 FAIL）。二进制不入 git，获取方式见 `bin/README.md`。
- pi/pi-web 均为 pre-1.0，版本已在 package.json / .pi/settings.json 精确锁定，升级需重跑自检。
