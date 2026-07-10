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
├── extensions/comms-tools/   # 15 个域工具：defs.ts 声明表 + runner.ts 公共桥（spawn Python）
├── extensions/approval-gate.ts   # 审批门：bash/edit/write/equivalence_check 执行前须确认，无 UI 时 fail-closed
├── extensions/git-checkpoint.ts  # 回滚：每次 edit/write 前按文件所属仓库打快照，/rollback 恢复
├── prompts/                  # 10 个 /命令 模板（/term /rf-calc /fec /ofdm /optimize-loop …）
└── settings.json             # 默认模型 comms-gateway/deepseek-v4-flash
config/
├── models.template.json      # provider 模板（baseUrl 来自 .env；key 只走 $OPENAI_API_KEY）
└── prompts/                  # qa / optimize 双模式人设（经 --append-system-prompt 注入）
tools/                        # 15 个 Python 计算核（numpy/scipy，与运行时无关）
knowledge/                    # 通信术语速查 + 通信原理知识100问（grep/read 检索）
scripts/                      # 启动入口 / 自检 / 真实项目验证 / dev 冒烟
agent-home/                   # pi 配置与会话（PI_CODING_AGENT_DIR 指向，gitignored）
real_projects/ModulationPy/   # 优化目标（独立 git 仓库，gitignored）
```

## 与个人 pi 的隔离

启动脚本把 `PI_CODING_AGENT_DIR` 指向项目内 `agent-home/`——models.json、auth、会话
全部落在项目里；扩展/模板只放项目级 `.pi/`（经 trust 加载）。你的全局 `~/.pi` 不被读写
（已知上游 0.80.6 瑕疵：会在 `~/.pi/agent/` 落一个空 auth.json，无害）。

## 双模式与安全

- **comms-qa**：启动时 `--exclude-tools bash,edit,write,equivalence_check`——能力级隔离，模型根本没有写工具。
- **comms-optimize**：全部工具可用，但审批门扩展在执行前弹确认（TUI 原生弹窗；pi-web 经
  `extension_ui_request/response` 透传到浏览器）；每次写入前自动打 git 快照，`/rollback` 一键回退。
- 密钥只走环境变量；`equivalence_check` 会执行传入命令，已纳入审批门管控。

## 验证

```bash
scripts/check-runtime.sh --full   # 依赖 + 隔离配置 + 扩展冒烟(16/7/3) + Python 单测(87+11)
scripts/check-real-project.sh     # ModulationPy tests.py（优化闭环的行为等价基线）
```

## 已知边界

- MATLAB 能力暂未接入（规划：Python `matlab.engine` 直包为域工具，MATLAB 可选自备）。
- pi/pi-web 均为 pre-1.0，版本已在 package.json 精确锁定，升级需重跑自检。
