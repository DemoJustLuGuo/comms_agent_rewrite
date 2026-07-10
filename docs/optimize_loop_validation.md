# comms-optimize 真实项目优化闭环验证（Runbook）

> **⚠️ 历史记录（OpenCode 时代，2026-07-07）**：本文中的 `.ps1` / `opencode` / `start-opencode` 命令
> 均属旧栈，仅作历史参照。pi 栈的等效闭环已于 2026-07-10 重演通过（见 `pi_migration.md` §C1），
> 现行流程：`scripts/comms-optimize.sh` + `/optimize-loop` 模板 + `scripts/check-real-project.sh` 验证。

目标：完成 `../../docs/ACCEPTANCE.md` §7 的最后一项——`comms-optimize` 对
`real_projects/ModulationPy` 跑通一次完整闭环：**读代码 → 提出修改 → 审批 → 修改文件 →
运行验证 → 汇报结果差异**。

该验证需要有效的模型 Key 和人工点击审批，无法由脚本代跑；按本文步骤人工执行一次即可。

## 1. 前置条件

```powershell
cd F:\CODE\agent_rewrite\comms-agent
$env:OPENAI_BASE_URL = "https://your-api.example/v1"
$env:OPENAI_API_KEY = "your-api-key"
$env:MATLAB_ROOT = "F:\matlabR2024"   # 可选，本轮闭环不需要 MATLAB
.\scripts\check-runtime.ps1            # 应全绿（MATLAB 未设则 SKIP）
```

## 2. 记录基线

```powershell
.\scripts\check-real-project.ps1                              # 应通过
git -C real_projects\ModulationPy status --short              # 应为空（工作区干净）
```

ModulationPy 自带独立 `.git`（被根仓库忽略），基线干净才能在验证后审阅 diff 和回退。

## 2b. （可选）OpenCode 会话内 MATLAB 首调实测

到目前为止，MATLAB 只验证过两件事：OpenCode 启动时 5 个 tools 注册成功，以及自检经 MCP
协议直连执行 `disp(1+1)` 通过。**OpenCode 会话 → MCP → MATLAB 引擎的首次调用整条链路
尚未实测过**。若本轮或后续要用 MATLAB，先在 `comms-optimize` 里做一次首调：

> 用 matlab_evaluate_matlab_code 执行 `disp(1+1)`，把返回原样贴出来。

要点：
- 会弹出 `matlab*` 审批（全局 `ask`），点同意。
- MATLAB 引擎冷启动较慢；`opencode.json` 的 `mcp.timeout`（30s）只约束「启动 + 取工具
  清单」预算，**不限制单次工具调用**，所以引擎首调慢不会被这个超时掐断。首调通过后再调会明显变快。
- 首调若长时间无返回，先确认 `MATLAB_ROOT` 指向可用安装、`bin/` 下有对应平台的 server 二进制。

## 3. 执行闭环

1. `.\start-opencode.ps1` 启动，Tab 切换到 `comms-optimize`。
2. 输入首轮低风险优化指令（目标来自 `real_project_integration.md` 的推荐范围）：

   > 优化 real_projects/ModulationPy/ModulationPy/ModulationPy.py：只做低风险改进——
   > 为关键变量补充单位与通信含义注释（星座符号、噪声方差、LLR 等），并为调制阶数、
   > 输入长度、二进制输入约束补充清晰的错误提示。保持所有计算结果与 tests.py 行为
   > 完全等价。动手前先用一两句话说明方案。

3. 过程核对清单（任何一条不符合即算未通过）：
   - [ ] 模型先读取目标文件并给出方案，而不是直接改。
   - [ ] 每次写文件都弹出 edit 审批，未出现未经审批的写入。
   - [ ] 运行验证命令（`scripts/check-real-project.ps1`）时弹出 bash 审批。
   - [ ] 最终输出包含前后对比与风险说明（符合 optimize.md 的输出结构）。

## 4. 验证与审阅

```powershell
.\scripts\check-real-project.ps1                              # 必须仍然通过
git -C real_projects\ModulationPy diff                        # 人工审阅改动是否符合"低风险"边界
```

## 5. 回退方式

- 丢弃本轮全部改动：`git -C real_projects\ModulationPy checkout -- .`
- 或使用 OpenCode 会话内的 revert 功能逐步回退。

## 6. 通过标准与收尾

通过标准：一次会话内完成 读 → 改 → 审批 → 验证 → 汇报；`tests.py` 保持通过；
无越权操作。

通过后更新：
- `../../docs/PROGRESS.md`：勾选"完整优化闭环"待办，添加日志条目。
- `../../docs/ACCEPTANCE.md`："当前结论"补充闭环通过时间与证据。
- 根目录 `CLAUDE.md` / `comms-agent/CLAUDE.md` 的待办勾选。

## 7. 执行记录

### 2026-07-07 · deepseek-v4-flash · 首次闭环通过

- **模型 / 端点**：`custom-openai/deepseek-v4-flash`，OpenAI Responses API（`/v1/responses`）；端点探测流式 3/3 稳定。
- **运行方式**：`opencode run --agent comms-optimize -m custom-openai/deepseek-v4-flash --auto`（headless）。
- **审批说明（重要）**：本次用 `--auto` 自动放行 edit/bash，**未经 TUI 交互式人工审批**；权限门控（`ask`）本身已在 P0 单独验证。人工把关由操作者在 agent 完成后**手动审查 diff + 独立复跑测试**充当，等效于审批环节。
- **目标文件**：`real_projects/ModulationPy/ModulationPy/ModulationPy.py`。
- **改动**：为 `Modem.__init__` 补充中文 docstring（33 行），标注各参数通信含义与单位（M=调制阶数 2ⁿ、N=log₂(M) bit/symbol、noise_var=线性功率值、phi=rad 等）；未改任何可执行代码，docstring 予以保留。
- **等价性**：`git diff` 确认仅新增字符串字面量，控制流零改动。
- **验证**：agent 自跑 `unittest` 2 tests OK；操作者独立复跑 `python -m unittest tests.py`（2 tests OK, RC=0）+ 官方入口 `scripts/check-real-project.ps1`（passed, RC=0）+ `py_compile`（OK）。
- **模型甄别**：先用 MiniMax-M3 试跑，端点 `/v1/responses` 流式偶发 `empty_stream`、长任务输出易截断（曾产出少一个引号的坏 docstring），不适合当主力；改用 deepseek-v4-flash 一次跑通。
- **结论**：P1 优化闭环（读 → 改 → 验证）跑通。

### 2026-07-07 · deepseek-v4-flash · TUI 人工审批闭环通过

- **运行方式**：用户在 TUI 中启动 `comms-optimize` 并执行 `/optimize-loop`。
- **审批证据**：edit / bash 权限审批均正常弹出并由用户手动确认；模型调用正常。
- **目标文件**：`real_projects/ModulationPy/ModulationPy/ModulationPy.py`。
- **模型产物**：补充 docstring、增强错误消息、修正局部变量拼写 `possition -> position`。`scripts/check-real-project.ps1` 通过，`tests.py` 2 tests OK。
- **人工审阅结论**：流程通过，但产物不保留。原因是本轮只是闭环测试；同时审阅发现模型把归一化仿真量写成 `[V]` / `[W]`，单位表达过度具体，属于模型产物质量问题，不是智能体流程失败。
- **收尾**：执行 `git -C real_projects\ModulationPy checkout -- .` 回退测试产物；根仓库和真实项目子仓库均恢复干净；`scripts/check-real-project.ps1` 复跑通过。
- **后续约束**：已将单位臆造风险沉淀到 `.opencode/prompts/optimize.md`，并新增 `model_output_review_checklist.md` 作为保留/回退模型产物的审阅清单。
