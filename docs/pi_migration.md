# OpenCode → pi 迁移记录

**日期**：2026-07-10（Phase A/B/C 单日完成）
**结论**：迁移成功。通信智能体自本日起以本仓库（pi 运行时）为唯一活跃开发线；
旧 OpenCode 栈（`../agent_rewrite/comms-agent/` 与 `workbench/`）转只读参照。

## 背景与决策

- 旧栈痛点：workbench（OpenChamber 整库 fork）需要"从四端全功能产品做减法"才能可用，UI 改造成本失控；15 份 TS 工具桥复制粘贴；`equivalence_check`/`online_knowledge` 存在绕过审批的缺陷（提示词软约束）。
- pi 关键机制（实测确认）：extension `tool_call` 拦截可 `{block:true}` + `ctx.ui.confirm` → 审批门是官方机制；RPC 模式 `extension_ui_request/response` 子协议 → 审批可透传到 pi-web；`models.json` 自定义 provider（`openai-completions`）→ deepseek 接入且解除旧栈 `/v1/responses` 模型锁定。
- 隔离：`PI_CODING_AGENT_DIR` 重定向整个配置目录到项目内 `agent-home/`，与个人全局 pi 零共享。

## 验证证据（Phase A spike）

| 项 | 结果 |
|---|---|
| A0 隔离 | models/auth/sessions 全部落 agent-home ✔；已知上游瑕疵：`~/.pi/agent/` 仍会落一个**空** auth.json（无害） |
| A1 模型通路（一票否决） | deepseek-v4-flash × `openai-completions`：link_budget 工具调用（-65.04 dBm 精确）、read→write 落盘、bash 执行 venv python，全过；期间两次 500 为网关瞬时抖动（复测通过） |
| A2 工具桥 | runner 工厂 + argv/stdin 双桥型，离线冒烟 + 模型端 plot 出 PNG（plots/a2_qpsk.png） |
| A3 审批门 | 单测 7/7（放行/拒绝/fail-closed/allow-all/白名单外直放/equivalence_check 纳管/摘要） |
| A4 pi-web | 会话建立→prompt→工具调用（会话 jsonl 有 `"toolName":"link_budget"`）；PNG 经 `/api/files/...?type=download` 200 image/png；**审批全链路**：SSE 收到 `extension_ui_request(method=confirm, title=审批：bash)` → API 回 `confirmed:true` → bash 放行执行 ✔ |

pi-web 集成形态：spawn 自带打包的 pi（RPC 模式），不用项目 pin 的二进制 → 项目 pin 已对齐其内嵌版本 0.80.6。

## Phase B 交付

- **B1**：15 域工具全量迁移（`.pi/extensions/comms-tools/defs.ts` 单表 + `runner.ts` 公共桥）；路由知识内聚 `promptSnippet`；冒烟 16/16。
- **B2**：10 个 `/命令` 模板（`.pi/prompts/`）；qa/optimize 双模式 = 启动脚本（qa 用 `--exclude-tools` 能力级隔离）+ `--append-system-prompt` 人设；`/term FSPL` 端到端验证知识检索闭环。
- **B3**：git-checkpoint 回滚扩展（按被改文件**所属仓库**打 stash 快照；`/rollback` 单文件恢复/新建删除）；真实仓库冒烟 3/3。
- **B4**：`scripts/check-runtime.sh --full` 一键自检（依赖/隔离/16+8+3 冒烟/87+11 单测）全绿。
- **B5**（2026-07-10 补完）：**MATLAB 经 MCP 迁移**——沿用旧栈原物（MathWorks 官方 matlab-mcp-server v0.11.1 二进制 + `start_matlab_mcp.py` 三级发现包装），宿主从 opencode.json 的 `mcp` 块换成 **pi-mcp-extension**（社区成熟 MCP 客户端，项目级锁定 1.5.0，装于 `.pi/npm/`）。配置 `.pi/mcp.json`（stdio、eager、120s 超时）。注册为 `mcp_matlab_*` 五工具；审批门以 `mcp_` 前缀统一纳管（对应旧栈 `matlab* = ask`）；comms-qa 启动脚本精确排除五个工具名（只读边界）。**E2E 实测**：deepseek 调 `mcp_matlab_evaluate_matlab_code` 算 FSPL 得 120.0460 dB，并自发用 `link_budget` 域工具交叉验证——MCP 工具与域工具同会话协同。无 MATLAB 的机器自动降级（自检 WARN 不 FAIL）。
  - 决策注记：原计划方案②（`matlab.engine` 直包）被否——用户判断"沿用 MCP 设定"正确且成本更低：pi 生态已有生产级 MCP 客户端扩展，旧 server 二进制与发现逻辑零改动复用；`matlab.engine` 反而要求 venv 匹配 MATLAB 版本安装引擎包。

## 踩坑记录（换机/复现必读）

1. **MSYS 参数路径转换**：Git Bash 会把 `/term` 转成 `F:/Git/term`、模板无法展开；但一刀切 `MSYS_NO_PATHCONV=1` 又会让 env 里的 `/f/...` 路径失效（pi 找不到 models.json → 回落官方 OpenAI → 401）。定式：自己构造的路径先 `cygpath -m` 转 Windows 形态，再禁用转换（见 `scripts/comms-env.sh`，勿动）。
2. **`pi.exec` 非零退出不抛异常**，看 `ExecResult.code`（git-checkpoint 曾因此误判 tracked）。
3. **`core.autocrlf` 环境**下 git checkout 恢复文本为 CRLF，测试断言需归一化行尾。
4. **`-p` 单轮模式**下模型可能在对话层征求确认而停住（提示词里的"等用户同意"）；脚本化验收用 `-c -p "同意…"` 续行，或在 `/optimize-loop` 的额外要求里声明免确认。
5. pi-web 的 `/api/agent/new` 请求体：`{cwd, type:"ensure_session", provider, modelId, toolNames?}`；会话内命令为 RPC envelope（`{"type":"prompt"|"get_state"|...}`）。
6. **PYTHON_BIN 必须是 Windows 形态**：venv-python.sh 曾导出 `/f/.../python.exe`（MSYS 形态），bash 里能跑、但 pi 扩展（node）spawn 时 ENOENT——凡经启动脚本的会话，15 个 Python 域工具全部静默失败、模型退化为 bash 手算。该 bug 由路由验证 harness 首跑抓获（旧栈 validate-tool-routing 值得迁移的活证据），已在 venv-python.sh 用 cygpath -m 修复。

## 能力审计（2026-07-10，迁移完成后全量对照）

对旧栈能力面逐项核对后补齐 4 个缺口：①AGENTS.md 项目规则（pi 自动加载；含 MATLAB 定位决策、equivalence_check/online_knowledge 安全口径）；②`scripts/validate-tool-routing.sh` 模型端路由验证 harness（16 工具逐个真实调用，断言 toolName 事件 + 结果锚点）；③agent-facing 文档旧栈残留清理（real_project_integration.md 重写为 .sh 命令，optimize_loop_validation.md 加历史注记）；④optimize 提示词补 pyright CLI 降级说明（pi 无 LSP）。

**路由验证结果：16/16 全 PASS**（15 域工具 + mcp_matlab_evaluate_matlab_code；comms_lint 首跑遇网关限流"total request limit reached"，配额恢复后复跑通过——跑批时的限流属网关侧用量窗口，与栈无关）。

### opencode 内建工具的 pi 平替（2026-07-10 调研+实证）

| opencode 内建 | pi 平替 | 状态 |
|---|---|---|
| `webfetch`（ask 门控） | 官方 MCP fetch server（`uvx mcp-server-fetch`）经 pi-mcp-extension 挂载，注册为 `mcp_fetch_fetch`，自动落审批门 `mcp_` 前缀 | ✅ 已落地，E2E 实测抓取 example.com 成功；审批语义与旧栈 `webfetch: ask` 精确对齐 |
| `grep` / `glob` / `list` | **pi 原生就有** `grep`/`find`/`ls` 内建工具，默认未启用；`--tools` 白名单可点亮（实测模型自报可用） | ✅ 机制实证；启用方式待定（建议双模式改 `--tools` 正向白名单，顺带让 qa 获得知识检索能力） |
| `todowrite` / `todoread` | 官方示例 `examples/extensions/todo.ts`（297 行，拷入 .pi/extensions 即用） | 📦 备选未装（当前工作流未用到） |
| `task`（子代理） | 官方示例 `examples/extensions/subagent/`（完整包结构） | 📦 备选未装（旧栈也未启用） |
| `patch` | pi 的 `edit` 覆盖 | — 无需 |
| LSP 诊断 | `npx pyright` CLI 降级（已写入 optimize 提示词） | ✅ 已处理 |

有意不迁（记录在案）：`small_model`（pi 无此概念）；`shell: pwsh` 本机覆盖（pi 统一 Git Bash）；`sync_opencode_profile.py`（opencode 专属）；workbench 中文工具名 hack（pi 工具原生 `label` 字段承载）。

## C1 优化闭环重演验收（ModulationPy）

**结论：通过。** pi 运行时下完整跑通「读懂 → 提方案 → 审批 → 改码 → 验证 → 等价结论」闭环。

- **目标**：`real_projects/ModulationPy/ModulationPy/ModulationPy.py`
- **改动**：34 行 diff（+23/-11）——修 2 处拼写（`possition`→`position`、`denum`→`denom`，含全部引用同步）、补单位/通信含义注释（区分标注 无量纲 / 线性功率 / dB / rad，未臆造物理单位）、QAM 星座明确标注「非单位能量归一化，间距=2」。仅注释与内部变量名，公开 API 零改动。
- **验证**：`scripts/check-real-project.sh` → `tests.py` 2/2 通过；模型自评行为等价（变量重命名经 diff 确认无残留引用）。
- **模型自评结论**：建议保留 🟢（改动边界/行为等价/单位术语/可审阅性四项全过）。
- **交互说明**：本次为脚本化验收（`COMMS_APPROVAL=allow-all`），TUI 原生审批弹窗此前已由用户手动目验（放行/拒绝/rollback）。
- **验收后处置**：改动已 `git checkout` 恢复，ModulationPy 保持干净基线（验收目的是验证闭环能力，非向第三方项目提交改动）。

## C2 pi-web fork 决策

**决定：暂不 fork。** 依据：
- 原三大动机中，审批 UI（A4 实证已内置）与 PNG 预览（文件预览自带）已消失；仅剩**界面中文化**与 **plots 画廊聚合页**，均为体验增强而非功能缺口。
- pi-web 上游活跃（v0.7.x 高频发版）；现在 hard fork 意味着立刻接下全部维护面，换取两个 nice-to-have。
- npm 包只含构建产物，fork 须从 GitHub 源码起步（MIT，无法律障碍）。

**重新评估的触发条件**（满足其一再议）：① 日常使用中中文化成为真实阻力（非审美偏好）；② 需要 plots 时间线/对比画廊这类 pi-web 结构性没有的视图；③ 上游断更且累积了必须自修的 bug。届时按「加法 fork」路径执行：clone agegr/pi-web → 锁 tag → 只叠中文化与画廊路由。

## 旧栈退役

- 旧仓三个入口文档（根 `CLAUDE.md`、`docs/PROGRESS.md`、`comms-agent/CLAUDE.md`）已加迁移横幅（提交 0886c6d）；`workbench/` 随旧仓一并封存。
- 旧仓不删除：Python 计算核演进历史、OpenCode 配置形态、OpenChamber 定制都可能回头参照。
- 本仓即日起为唯一开发线（local/dev 分支，规范沿用：每轮功能完成即提交）。

## 后续事项

- ~~B5 MATLAB 工具~~（2026-07-10 已完成，见 Phase B 交付）；
- pi / pi-web / pi-mcp-extension 升级流程：改 package.json / .pi/settings.json 版本 → `bun install` 或 `pi update` → `scripts/check-runtime.sh --full` 全绿才算升级完成；
- 新增 MCP server 时：写 `.pi/mcp.json` → 审批门自动覆盖（`mcp_` 前缀）→ **同步 comms-qa.sh 的排除名单**（只读边界靠精确工具名）；
- knowledge/ 扩充与检索召回评测（旧栈遗留课题，与运行时无关）。
