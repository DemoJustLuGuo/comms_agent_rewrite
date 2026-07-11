# 通信场景审计与功能细化（2026-07-11）

对新仓 15 域工具能力面 × 旧栈 persona 声明场景做双向盘点后，本轮补齐两大场景缺口并迁移报告模式。

## 审计结论（当时基线：15 域工具）

| 场景（persona 承诺） | 当时状态 | 处置 |
|---|---|---|
| 定量计算/仿真、代码优化 | 15 工具覆盖良好 | 不动 |
| **工程评估**（噪声/灵敏度/干扰/衰落/多普勒） | 算子为零 | ✅ 本轮新增 rf_chain / interference / channel_profile / fade_margin |
| **故障定位/测量数据分析** | 仅 FFT/PSD（signal_analysis） | ✅ 本轮新增 signal_diagnose + /diagnose + 故障特征速查.md |
| 报告交付（旧栈 report_prompt） | 未迁移 | ✅ 本轮以 /report 命令承载（不加第三模式） |
| knowledge/ 工程口径 | 只有教学向内容 | ✅ 本轮新增 工程评估速查.md + 故障特征速查.md |
| 协议分析深化（吞吐/时延/ARQ） | frame_parser 仅静态帧 | ⏸ 本轮不做（见下） |
| 长期记忆（旧栈 store/search_memory） | 无 | ⏸ 不做（pi 会话已覆盖主要需求） |
| 本地 RAG/文档上传入库 | 无 | ⏸ 不做（grep/read 检索召回不足时再议） |

## 本轮交付（域工具 15→20，模板 10→12）

1. **rf_chain**：Friis 级联 NF（逐级贡献占比）、kTB 噪声底、接收灵敏度。
2. **interference**：C/I 与 SINR（多干扰源线性域叠加，kTB+NF 噪声，门限余量结论）。
3. **channel_profile**：多普勒/相干时间（Tc≈0.423/fd）、相干带宽（Bc≈1/(5στ)）、快慢衰/平坦频选判定。
4. **fade_margin**：衰落余量；雨衰=ITU-R P.838-3 系数（1~40 GHz 内插）+ P.530 有效路径缩减——**地面视距近似（±20~30%），卫星/倾斜路径不适用**，工具输出与 promptSnippet 均强制转述该口径。
5. **signal_diagnose**：SNR 估计、DC 偏置、削波（平顶连续段判据，避免纯正弦误报）、THD、IQ 幅度/相位失衡（假设单音/窄带激励，输出回显假设）；输出触发症状条目，对接 knowledge/故障特征速查.md。
6. **/diagnose /report** 模板；reports/ 已 gitignore（/report 在 optimize 模式落盘、qa 模式输出正文）。
7. **knowledge/**：工程评估速查.md（典型 NF/灵敏度/门限/余量/量纲关系）+ 故障特征速查.md（症状→原因→排查动作，含时域/频域/IQ/误码四视角）。

布线同步：comms-env.sh 白名单（qa 24 / optimize 33）、qa-mode.md 职责范围、
smoke_extension.ts（21 例）、test_domain_tools.py（106 条，含 Friis/多普勒/相干带宽已知值断言）、
validate-tool-routing.sh（21 例）、check-runtime.sh 计数、README。

## 有意不做（重新评估触发条件）

- **协议分析深化**：等出现真实的吞吐/时延预算或 ARQ 分析需求；届时优先做 throughput/latency 估算工具而非协议状态机。
- **长期记忆 / 本地 RAG**：等 qa 模式的 grep/read 检索在实际使用中出现召回不足的具体案例。

## GUI：对话内图片内联渲染（2026-07-11，零 fork）

调研结论：pi-web 聊天区用 react-markdown 渲染助手消息，且未覆写/禁用 `img` 元素——
`![标题](/api/files/<绝对路径逐段URL编码>?type=download)` 即可内联显示（其 files API
只认绝对路径，相对路径 403；A4 已证 PNG 经该端点 200 image/png）。据此**不 fork**，改两处：

1. `tools/plot.py`：①ROOT 锚定脚本位置（曾因 pi-web 拉起的 pi 进程 cwd=pi-web 包目录，
   把 PNG 写进 node_modules）；②输出新增「Markdown 内联」行，含现成的图片 markdown（盘符
   冒号编码为 %3A，兼容中文文件名）；TUI 下该行为普通文本无副作用。
2. `defs.ts` plot promptSnippet：要求模型回复中原样携带该行。
   `runner.ts` 同时把子进程 cwd 固定为项目根（其余相对路径工具在 pi-web 下同样受益）。

E2E 实证：pi-web 会话内模型画图 → PNG 落项目 plots/ → 助手回复携带 markdown 图片行 →
该 URL 返回 200 image/png（浏览器端由 react-markdown 默认 img 渲染内联）。
