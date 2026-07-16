# 通信场景覆盖地图

> 「某场景有没有被覆盖」的单一事实源。覆盖 = 有域工具 / 知识条目 / 命令入口 三者之一或组合。
> 新增能力后**必须回写本表**（连同 defs.ts / comms-env.sh 白名单 / 冒烟 / 单测 / 路由 / README 计数）。
> 场景本身不拆 agent——双模式（qa 只读 / optimize 可写）是覆盖面的容器，工具进 defs.ts 两模式即同时可用。

## 图例

- 工具：`defs.ts` 里的域工具名（Python 计算核在 `tools/<name>.py`）
- 知识：`knowledge/` 下条目
- 命令：`.pi/prompts/` 下 `/命令` 模板
- 状态：✅ 已覆盖 · 🟡 部分 · ⬜ 空白（含重启条件）

## 1. RF / 链路规划

| 场景 | 工具 | 知识 | 命令 | 状态 |
|---|---|---|---|---|
| 自由空间链路预算（FSPL/EIRP/Prx） | `link_budget` | 通信术语速查 | `/rf-calc` | ✅ |
| 实际传播损耗（Hata/COST-231/对数距离） | `path_loss` | — | `/rf-calc` | ✅ |
| 接收链噪声/灵敏度（Friis/kTB） | `rf_chain` | 工程评估速查 | — | ✅ |
| 干扰 C/I 与 SINR（多源线性叠加） | `interference` | 工程评估速查 | — | ✅ |
| 信道特征（多普勒/相干时间/相干带宽/快慢衰/平坦频选） | `channel_profile` | 工程评估速查 | — | ✅ |
| 衰落余量 / 雨衰（地面 1~40GHz 近似） | `fade_margin` | 工程评估速查 | — | ✅ |

## 2. 调制 / 性能

| 场景 | 工具 | 知识 | 命令 | 状态 |
|---|---|---|---|---|
| 理论 BER↔SNR（AWGN，6 种调制） | `ber_snr` | 通信术语速查 | — | ✅ |
| 星座/Gray 映射/EVM | `modulation` | — | — | ✅ |
| 端到端信道仿真（AWGN/Rayleigh/Rician） | `channel` | — | — | ✅ |
| 信息论容量与频谱效率（香农/MIMO/Eb-N0） | `capacity` | — | `/capacity` | ✅ |
| 脉冲成形/匹配滤波/眼图/ISI | `pulse_shaping` | — | `/pulse` | ✅ |
| **链路自适应/AMC（选 MCS 档）** | `link_adaptation` | 工程评估速查 | `/amc` | ✅ |

## 3. 信道编码 / FEC

| 场景 | 工具 | 知识 | 命令 | 状态 |
|---|---|---|---|---|
| 经典码编码增益（卷积 K7/Hamming/RS） | `channel_coding` | — | `/fec` | ✅ |
| 现代信道码 LDPC（WiMAX rate-1/2）/ Turbo（rate-1/3） | `channel_coding`（扩展，commpy） | — | `/fec` | ✅ |
| Polar 码（5G 控制信道，SC 译码） | `channel_coding`（扩展，py-polar-codes 库） | — | `/fec` | ✅ |

## 4. 多载波 / MIMO

| 场景 | 工具 | 知识 | 命令 | 状态 |
|---|---|---|---|---|
| OFDM/多载波（PAPR/BER/频谱/CP/频选） | `ofdm` | — | `/ofdm` | ✅ |
| **波束成形/预编码（MRT/ZF，阵列增益/方向图）** | `beamforming` | — | `/beamform` | ✅ |
| MIMO 遍历容量（等功率/注水） | `capacity` | — | `/capacity` | ✅ |

## 5. 扩频 / 抗干扰

| 场景 | 工具 | 知识 | 命令 | 状态 |
|---|---|---|---|---|
| **扩频处理增益/抗干扰余量（DSSS/跳频）** | `spread_spectrum` | — | `/spread` | ✅ |

## 6. 信号 / 故障诊断

| 场景 | 工具 | 知识 | 命令 | 状态 |
|---|---|---|---|---|
| 频谱/PSD/频率峰值 | `signal_analysis` | — | — | ✅ |
| 实测信号体检（SNR/DC/削波/THD/IQ 失衡） | `signal_diagnose` | 故障特征速查 | `/diagnose` | ✅ |
| **同步偏移量化（CFO/定时/SFO）** | `sync_estimate` | 故障特征速查 | `/diagnose` | ✅ |
| **均衡演示（ZF/MMSE/DFE）** | `equalizer` | 故障特征速查 | `/diagnose` | ✅ |
| 可视化（星座/频谱/波形/BER 曲线/眼图） | `plot` | — | — | ✅ |

## 7. 协议分析

| 场景 | 工具 | 知识 | 命令 | 状态 |
|---|---|---|---|---|
| 帧解析（Ethernet/TLV/自定义，CRC） | `frame_parser` | — | `/frame` | ✅ |
| 协议深化（吞吐/时延/ARQ 预算） | — | — | — | ⬜ 有意不做 |

## 8. 工程护栏

| 场景 | 工具 | 命令 | 状态 |
|---|---|---|---|
| 通信代码体检（单位/复现/NumPy/协议/密钥） | `comms_lint` | `/lint` | ✅ |
| 数值等价校验（优化回归护栏） | `equivalence_check` | `/equiv` | ✅ |

## 9. 知识检索

| 场景 | 资产 | 状态 |
|---|---|---|
| 专业名词/概念/原理 | `knowledge/`（术语速查/原理 100 问/工程评估/故障特征） | ✅ |
| 名词查询 | `/term` | ✅ |
| 在线知识（RFC/标准/论文/协议版本） | `online_knowledge` | ✅ |
| 网页抓取 | `mcp_fetch_fetch` | ✅ |
| MATLAB 工具箱（用户自备） | `mcp_matlab_*` | 🟡 可选降级 |

## 待验证（已实现，未运行确认）

- **Polar 码（极化码）**：已加 `py-polar-codes` 依赖（导入名 `polarcodes`，见 `pyproject.toml`）+ `polar_sc_r12` 分支（N=256/K=128，SC 译码）。该库 API 有状态且版本敏感，本轮**未运行验证**——runner 全部调用点包 try/except，API 不符时返回 `POLAR_API` 清晰错误而非乱码。首次 `uv sync` 后跑 `ModernCodesTests` 确认；失败按报错对齐库调用约定。

## 有意不做（重启条件未触发）

- **多 agent / 场景专属 agent**：场景间无安全边界差异（读/写边界已由双模式覆盖），拆分只发散维护面（persona/白名单/自检计数 ×N），路由收益为零。
- **协议深化（吞吐/时延/ARQ）**：等出现真实吞吐/时延预算或 ARQ 需求。
- **长期记忆 / 本地 RAG**：等 qa 模式 grep/read 检索出现召回不足的具体案例。

## 空白复查节奏

每轮新增能力后回写对应行；季度性对照旧栈/真实使用日志复查 ⬜ 行是否触发重启条件。
