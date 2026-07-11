/**
 * comms 域工具声明表：20 个工具的 name/label/描述/Typebox schema/运行 spec。
 *
 * 前 15 个迁移自 opencode 时代 15 份 .ts 桥（schema 语义一字不动，zod→Typebox 机械转换）；
 * 2026-07-11 场景审计后新增 5 个：rf_chain/interference/channel_profile/fade_margin（工程评估）
 * + signal_diagnose（故障定位）。
 * promptSnippet 承载工具路由规则——路由知识只在这一处维护。
 *
 * 约定：
 * - 大数组参数的工具（modulation/signal_analysis/signal_diagnose/online_knowledge/plot）走 stdin（spec.stdinJson）。
 * - 蒙特卡洛/FEC 类超时放宽（channel_coding 180s、equivalence_check 120s），其余 30s。
 */
import { Type } from "typebox"
import { StringEnum } from "@earendil-works/pi-ai"
import type { PyToolSpec } from "./runner"

export interface CommsToolDef {
  name: string
  label: string
  description: string
  promptSnippet?: string
  parameters: ReturnType<typeof Type.Object>
  spec: PyToolSpec
}

const MODULATIONS = ["BPSK", "QPSK", "8PSK", "16QAM", "64QAM", "256QAM"]

export const DEFS: CommsToolDef[] = [
  // ── RF / 链路 ────────────────────────────────────────────────────────────
  {
    name: "link_budget",
    label: "链路预算",
    description:
      "计算自由空间链路预算（FSPL / EIRP / 接收功率），用于通信链路可行性快速评估。",
    promptSnippet: "链路预算 / FSPL / EIRP / 接收功率等定量计算调用 link_budget，不要心算。",
    parameters: Type.Object({
      tx_power_dbm: Type.Number({ description: "发射功率，dBm" }),
      tx_gain_dbi: Type.Number({ description: "发射天线增益，dBi" }),
      rx_gain_dbi: Type.Number({ description: "接收天线增益，dBi" }),
      freq_mhz: Type.Number({ description: "载频，MHz" }),
      distance_km: Type.Number({ description: "链路距离，km" }),
      other_losses_db: Type.Optional(Type.Number({ description: "其他损耗（馈线/大气等），dB，默认 0" })),
    }),
    spec: { script: "link_budget.py", failureHint: "确认 uv sync 已建 .venv 且输入合法（距离/频率为正数）。" },
  },
  {
    name: "path_loss",
    label: "路径损耗",
    description:
      "计算无线传播路径损耗（dB），支持对数距离、Okumura-Hata（150–1500 MHz）、COST-231-Hata（1500–2000 MHz）模型。用于蜂窝/城区链路规划，比自由空间 FSPL 更贴近实际。",
    promptSnippet:
      "城区/郊区/蜂窝等实际传播损耗调用 path_loss（Okumura-Hata / COST-231 / 对数距离）；自由空间才用 link_budget。",
    parameters: Type.Object({
      model: StringEnum(["log_distance", "hata", "cost231"], {
        description: "传播模型：log_distance 对数距离；hata Okumura-Hata；cost231 COST-231-Hata",
      }),
      freq_mhz: Type.Number({ description: "载频，MHz" }),
      distance_km: Type.Number({ description: "收发距离，km" }),
      path_loss_exponent: Type.Optional(
        Type.Number({ description: "log_distance 专用：路径损耗指数 n（自由空间 2.0，市区 2.7~3.5，室内 4~6），默认 2.0" }),
      ),
      ref_distance_m: Type.Optional(Type.Number({ description: "log_distance 专用：参考距离 d0，m，默认 1000" })),
      bs_height_m: Type.Optional(Type.Number({ description: "hata/cost231 专用：基站天线高度 hb，m，默认 30" })),
      ms_height_m: Type.Optional(Type.Number({ description: "hata/cost231 专用：移动台天线高度 hm，m，默认 1.5" })),
      area: Type.Optional(
        StringEnum(["urban", "suburban", "rural", "metropolitan"], {
          description: "区域：hata 支持 urban/suburban/rural/metropolitan；cost231 仅 urban/metropolitan，默认 urban",
        }),
      ),
    }),
    spec: { script: "path_loss.py", failureHint: "确认输入合法（频率/距离为正数，area 与所选 model 匹配）。" },
  },
  {
    name: "rf_chain",
    label: "接收链评估",
    description:
      "接收链噪声与灵敏度评估：Friis 级联噪声系数（逐级贡献占比）、kTB 热噪声底、接收灵敏度（噪声底+NF+所需SNR）。用于「这条接收链 NF 多少 / 灵敏度多少 dBm / 噪声底多少」类工程评估。",
    promptSnippet:
      "噪声系数级联/噪声底/接收灵敏度调用 rf_chain（mode=cascade|noise_floor|sensitivity），不要心算。",
    parameters: Type.Object({
      mode: StringEnum(["cascade", "sensitivity", "noise_floor"], {
        description: "cascade=Friis 级联 NF；sensitivity=接收灵敏度；noise_floor=kTB 噪声底",
      }),
      stages: Type.Optional(
        Type.Array(
          Type.Object({
            name: Type.Optional(Type.String({ description: "级名称（如 LNA/混频器/线缆）" })),
            gain_db: Type.Number({ description: "该级增益，dB（损耗为负）" }),
            nf_db: Type.Number({ description: "该级噪声系数，dB（无源损耗件 NF=|损耗|）" }),
          }),
          { description: "cascade 必填、sensitivity 可用：按信号方向排列的各级" },
        ),
      ),
      nf_db: Type.Optional(Type.Number({ description: "sensitivity：整机噪声系数，dB（与 stages 二选一）" })),
      bandwidth_hz: Type.Optional(Type.Number({ description: "sensitivity/noise_floor 必填：噪声带宽，Hz" })),
      required_snr_db: Type.Optional(Type.Number({ description: "sensitivity 必填：解调所需 SNR，dB" })),
      temperature_k: Type.Optional(Type.Number({ description: "噪声温度，K，默认 290" })),
    }),
    spec: { script: "rf_chain.py", failureHint: "按 mode 提供必填参数（cascade 需 stages；sensitivity 需 bandwidth_hz+required_snr_db+nf_db 或 stages）。" },
  },
  {
    name: "interference",
    label: "干扰分析",
    description:
      "载干比 C/I 与 SINR 计算：多干扰源功率在线性域叠加，可结合 kTB(+NF) 噪声算 SINR，给定门限时输出余量结论。用于共道/邻道干扰评估、部署间距核算。",
    promptSnippet: "载干比 C/I、SINR、干扰余量调用 interference（多干扰源自动线性域叠加），不要手加 dB。",
    parameters: Type.Object({
      mode: StringEnum(["ci", "sinr"], { description: "ci=载干比；sinr=含噪声的信干噪比" }),
      carrier_dbm: Type.Number({ description: "载波接收功率，dBm" }),
      interferers: Type.Array(
        Type.Object({
          power_dbm: Type.Number({ description: "该干扰源接收功率，dBm" }),
          name: Type.Optional(Type.String({ description: "干扰源名称" })),
        }),
        { description: "干扰源列表（≥1 项）" },
      ),
      noise_floor_dbm: Type.Optional(Type.Number({ description: "sinr：噪声功率，dBm（与 bandwidth_hz 二选一）" })),
      bandwidth_hz: Type.Optional(Type.Number({ description: "sinr：由 kTB 算噪声的带宽，Hz" })),
      nf_db: Type.Optional(Type.Number({ description: "sinr：接收机噪声系数，dB，默认 0（与 bandwidth_hz 搭配）" })),
      temperature_k: Type.Optional(Type.Number({ description: "噪声温度，K，默认 290" })),
      required_ci_db: Type.Optional(Type.Number({ description: "解调所需 C/I 或 SINR 门限，dB；给了则输出余量结论" })),
    }),
    spec: { script: "interference.py", failureHint: "确认 interferers 非空；sinr 模式需 noise_floor_dbm 或 bandwidth_hz。" },
  },
  {
    name: "channel_profile",
    label: "信道特征",
    description:
      "无线信道特征判定：由载频+速度算最大多普勒频移与相干时间（Tc≈0.423/fd），由 RMS 时延扩展算相干带宽（Bc≈1/(5στ)）；给定符号率/带宽时输出 快衰/慢衰、平坦/频选 判定及依据。用于「该场景是不是频率选择性/要不要均衡或 OFDM」类判断。",
    promptSnippet:
      "多普勒/相干时间/相干带宽/快慢衰/平坦频选判定调用 channel_profile（freq+speed 或 delay_spread 至少一组）。",
    parameters: Type.Object({
      freq_mhz: Type.Optional(Type.Number({ description: "载频，MHz（与 speed_kmh 搭配算多普勒）" })),
      speed_kmh: Type.Optional(Type.Number({ description: "相对运动速度，km/h" })),
      delay_spread_us: Type.Optional(Type.Number({ description: "RMS 时延扩展 στ，μs（算相干带宽）" })),
      symbol_rate_sps: Type.Optional(Type.Number({ description: "符号率，symbol/s（给了才输出快慢衰/平坦频选判定）" })),
      signal_bandwidth_hz: Type.Optional(Type.Number({ description: "信号带宽，Hz（不给则用符号率近似）" })),
    }),
    spec: { script: "channel_profile.py", failureHint: "至少提供 freq_mhz+speed_kmh 或 delay_spread_us 其中一组。" },
  },
  {
    name: "fade_margin",
    label: "衰落余量",
    description:
      "衰落余量与雨衰估算：margin=接收电平-灵敏度（联动 rf_chain 口径）；rain=ITU-R P.838-3 比衰减 + P.530 有效路径缩减的地面视距链路雨衰近似（1~40 GHz，R≤100 mm/h，误差量级 ±20~30%，卫星/倾斜路径不适用）。用于链路可用性与毫米波雨衰预算。",
    promptSnippet:
      "衰落余量、雨衰（地面链路 1~40GHz 近似）调用 fade_margin（mode=margin|rain）；结论须转述其近似口径。",
    parameters: Type.Object({
      mode: StringEnum(["margin", "rain"], { description: "margin=衰落余量；rain=雨衰估算" }),
      rx_power_dbm: Type.Optional(Type.Number({ description: "margin：接收电平，dBm" })),
      sensitivity_dbm: Type.Optional(Type.Number({ description: "margin：接收灵敏度，dBm" })),
      required_margin_db: Type.Optional(Type.Number({ description: "margin：所需余量门限，dB" })),
      freq_ghz: Type.Optional(Type.Number({ description: "rain：频率，GHz（1~40）" })),
      distance_km: Type.Optional(Type.Number({ description: "rain：链路距离，km" })),
      rain_rate_mm_h: Type.Optional(Type.Number({ description: "rain：降雨率（0.01% 时间超越值常用），mm/h，≤100" })),
      polarization: Type.Optional(StringEnum(["h", "v"], { description: "rain：极化，h 水平 / v 垂直，默认 h" })),
    }),
    spec: { script: "fade_margin.py", failureHint: "按 mode 提供必填参数（margin 需 rx_power_dbm+sensitivity_dbm；rain 需 freq_ghz+distance_km+rain_rate_mm_h）。" },
  },
  // ── 性能 / 仿真 ──────────────────────────────────────────────────────────
  {
    name: "ber_snr",
    label: "误码率计算",
    description:
      "BER/SNR 性能计算工具：根据调制方式和信噪比计算理论误码率(BER)，或根据目标 BER 反推所需 SNR。支持 BPSK、QPSK、8PSK、16QAM、64QAM、256QAM。",
    promptSnippet:
      "AWGN 理论 BER↔SNR 换算调用 ber_snr；编码增益不要手填 coding_gain_db 臆测，用 channel_coding 实测。",
    parameters: Type.Object({
      modulation: StringEnum(MODULATIONS, { description: "调制方式" }),
      mode: StringEnum(["snr_to_ber", "ber_to_snr"], {
        description: "计算模式：snr_to_ber 由 SNR 求 BER；ber_to_snr 由目标 BER 求所需 SNR",
      }),
      snr_db: Type.Optional(Type.Number({ description: "信噪比 Eb/N0，dB（mode=snr_to_ber 时必填）" })),
      target_ber: Type.Optional(Type.Number({ description: "目标误码率（mode=ber_to_snr 时必填，如 1e-6）" })),
      coding_gain_db: Type.Optional(Type.Number({ description: "编码增益，dB，默认 0（无编码）" })),
    }),
    spec: { script: "ber_snr.py", failureHint: "确认参数合法（SNR 为实数，BER 在 0~0.5 之间）。" },
  },
  {
    name: "modulation",
    label: "数字调制",
    description:
      "数字调制：给出理想星座点(constellation)、把比特映射成符号(modulate)、或评估实测符号的 EVM(evm)。支持 BPSK/QPSK/8PSK/16QAM/64QAM/256QAM，Gray 编码、能量归一化。星座点可直接喂给 plot 工具画图。",
    promptSnippet: "星座 / Gray 映射 / EVM 评估调用 modulation；星座点可直接交给 plot 画图。",
    parameters: Type.Object({
      mode: StringEnum(["constellation", "modulate", "evm"], { description: "模式" }),
      modulation: StringEnum(MODULATIONS, { description: "调制方式" }),
      bits: Type.Optional(Type.Array(Type.Number(), { description: "modulate：0/1 比特序列" })),
      i: Type.Optional(Type.Array(Type.Number(), { description: "evm：实测符号同相分量 I" })),
      q: Type.Optional(Type.Array(Type.Number(), { description: "evm：实测符号正交分量 Q" })),
    }),
    spec: {
      script: "modulation.py",
      stdinJson: true, // bits 可能较大
      failureHint: "确认按 mode 提供了所需字段（modulate 需 bits；evm 需 i/q）。",
    },
  },
  {
    name: "channel",
    label: "信道仿真",
    description:
      "无线信道端到端仿真：对随机比特做调制，过 AWGN/Rayleigh/Rician 信道，完美 CSI 均衡后解调，统计经验 BER 并对比 AWGN 理论 BER。回答如「QPSK 过 Rayleigh、Eb/N0=8dB 的 BER」这类端到端问题。",
    promptSnippet: "「过某信道后的端到端 BER」（AWGN/Rayleigh/Rician 蒙特卡洛）调用 channel。",
    parameters: Type.Object({
      modulation: StringEnum(MODULATIONS, { description: "调制方式" }),
      snr_db: Type.Number({ description: "Eb/N0，dB" }),
      fading: Type.Optional(StringEnum(["awgn", "rayleigh", "rician"], { description: "信道类型，默认 awgn" })),
      rician_k_db: Type.Optional(Type.Number({ description: "Rician K 因子，dB，默认 6" })),
      num_bits: Type.Optional(Type.Number({ description: "仿真比特数，默认 100000，上限 5,000,000" })),
      seed: Type.Optional(Type.Number({ description: "随机种子（可复现）" })),
    }),
    spec: { script: "channel.py", failureHint: "确认参数合法（调制方式受支持，snr_db 为实数）。" },
  },
  {
    name: "channel_coding",
    label: "信道编码",
    description:
      "信道编码/FEC 仿真：对给定码型+调制+信道，仿真「编码 vs 未编码」BER，量化真实编码增益（取代 ber_snr 手填的 coding_gain_db）。支持卷积码 K=7 rate-1/2（硬/软 Viterbi）、Hamming(7,4)、Reed-Solomon(255,223)。用于「某码在某信道能压多少 BER / 编码增益多少 dB」这类问题。",
    promptSnippet:
      "信道编码/FEC（编码增益、coded vs uncoded BER，卷积/Hamming/RS）调用 channel_coding，不要用 ber_snr 手填编码增益。",
    parameters: Type.Object({
      code: StringEnum(["conv_k7_r12", "hamming_7_4", "rs_255_223"], {
        description: "码型：conv_k7_r12=卷积码K=7 rate-1/2；hamming_7_4=Hamming(7,4)；rs_255_223=Reed-Solomon(255,223)",
      }),
      modulation: StringEnum(MODULATIONS, { description: "调制方式" }),
      channel: Type.Optional(StringEnum(["awgn", "rayleigh"], { description: "信道模型，默认 awgn" })),
      ebn0_db: Type.Optional(Type.Array(Type.Number(), { description: "Eb/N0 扫点（dB，每信息比特能量），默认 [2,4,6]" })),
      num_bits: Type.Optional(
        Type.Number({ description: "每点信息比特数，默认 4000（conv 上限 20000，分组码上限 200000；越大 BER 分辨率越高但越慢）" }),
      ),
      decision: Type.Optional(
        StringEnum(["hard", "soft"], { description: "判决方式，默认 hard；soft 仅 conv_k7_r12 + BPSK/QPSK，其余自动回退硬判决" }),
      ),
      target_ber: Type.Optional(Type.Number({ description: "报告编码增益的目标 BER，默认 1e-3" })),
      seed: Type.Optional(Type.Number({ description: "随机种子（可复现）" })),
    }),
    spec: {
      script: "channel_coding.py",
      timeoutMs: 180_000, // FEC 仿真（纯 Python Viterbi）比其它域工具重；Python 侧对比特数已封顶
      failureHint: "确认 uv sync 已装 scikit-commpy/reedsolo，且参数合法；超时可减小 num_bits 或扫点数。",
    },
  },
  {
    name: "capacity",
    label: "容量计算",
    description:
      "计算信息论容量与频谱效率：AWGN 香农容量 C=B·log2(1+SNR)、MIMO 遍历容量（等功率/注水）、Eb/N0↔SNR↔频谱效率换算。用于容量/频谱效率类问答，不要心算。",
    promptSnippet: "香农/MIMO 容量、频谱效率、Eb/N0↔SNR 换算调用 capacity，不要心算。",
    parameters: Type.Object({
      mode: StringEnum(["awgn", "mimo", "ebn0"], {
        description: "awgn=香农容量；mimo=MIMO 遍历容量；ebn0=Eb/N0↔SNR↔频谱效率换算",
      }),
      bandwidth_hz: Type.Optional(Type.Number({ description: "带宽，Hz。awgn 必填；mimo 可选（给了才输出 bit/s）" })),
      snr_db: Type.Optional(Type.Number({ description: "信噪比，dB。awgn/mimo 必填；ebn0 可选（给了才算对应 Eb/N0）" })),
      nt: Type.Optional(Type.Number({ description: "发射天线数（mimo 必填）" })),
      nr: Type.Optional(Type.Number({ description: "接收天线数（mimo 必填）" })),
      allocation: Type.Optional(StringEnum(["equal", "waterfilling"], { description: "mimo 功率分配；默认等功率与注水都报告" })),
      realizations: Type.Optional(Type.Number({ description: "mimo 遍历平均的 iid 瑞利信道实现数，默认 1000" })),
      spectral_efficiency: Type.Optional(Type.Number({ description: "频谱效率 η，bit/s/Hz（ebn0 必填）" })),
      seed: Type.Optional(Type.Number({ description: "随机种子（mimo 复现）" })),
    }),
    spec: {
      script: "capacity.py",
      failureHint: "按 mode 提供必填参数（awgn 需 bandwidth_hz+snr_db；mimo 需 nt+nr+snr_db；ebn0 需 spectral_efficiency）。",
    },
  },
  {
    name: "pulse_shaping",
    label: "脉冲成形",
    description:
      "脉冲成形 / 匹配滤波 / 眼图：生成根升余弦(RRC)或升余弦(RC)滤波器，对调制符号做上采样→成形→匹配滤波，给出眼图张开度、峰值 ISI、占用带宽与成形信号功率谱。用于解释码间串扰(ISI)、成形滤波与奈奎斯特准则；眼图数据可再交 plot 工具作图。",
    promptSnippet:
      "成形滤波/匹配滤波/眼图/ISI（RRC/RC，滚降 β、每符号采样 sps）调用 pulse_shaping；其 PLOT_EYE_INPUT 字段可直接交 plot 画眼图。",
    parameters: Type.Object({
      modulation: StringEnum(MODULATIONS, { description: "调制方式" }),
      filter: Type.Optional(
        StringEnum(["rrc", "rc"], { description: "滤波器类型，默认 rrc（根升余弦，发/收各一半，级联为 RC）；rc=升余弦" }),
      ),
      beta: Type.Optional(Type.Number({ description: "滚降系数 β，0~1，默认 0.35（无量纲；越大带宽越宽、带外抑制越强）" })),
      sps: Type.Optional(Type.Number({ description: "每符号采样数(samples per symbol)，默认 8" })),
      span_symbols: Type.Optional(Type.Number({ description: "滤波器长度（符号数），默认 10（抽头数 = span_symbols·sps+1）" })),
      num_symbols: Type.Optional(Type.Number({ description: "随机符号数，默认 500（eye/psd 用）" })),
      output: Type.Optional(
        StringEnum(["eye", "impulse", "psd"], { description: "输出：eye=眼图/ISI（默认）；impulse=滤波器抽头；psd=成形信号功率谱" }),
      ),
      seed: Type.Optional(Type.Number({ description: "随机种子（可复现）" })),
    }),
    spec: { script: "pulse_shaping.py", failureHint: "确认参数合法（beta 在 0~1、sps≥2、span_symbols≥1）。" },
  },
  {
    name: "ofdm",
    label: "OFDM 仿真",
    description:
      "OFDM/多载波链路仿真：搭最小 OFDM 收发链（子载波映射→IFFT→循环前缀→AWGN/多径信道→去 CP→FFT→单抽头频域均衡→解调），解释子载波/CP/PAPR。三种 metric：papr（峰均比 CCDF）、ber（经验误码率，支持多径频选信道）、spectrum（占用带宽/带外抑制）。用于「OFDM/LTE/5G/WiFi 多载波性能、PAPR、CP、频选信道」类问题。",
    promptSnippet: "OFDM/多载波（子载波、循环前缀 CP、PAPR、频选信道）调用 ofdm（metric=papr|ber|spectrum）。",
    parameters: Type.Object({
      n_fft: Type.Optional(Type.Number({ description: "FFT/IFFT 点数（子载波总数），默认 64" })),
      n_used: Type.Optional(Type.Number({ description: "数据子载波数（≤ n_fft-1，留 DC/保护），默认 52" })),
      cp_len: Type.Optional(Type.Number({ description: "循环前缀长度（样点数），默认 16" })),
      modulation: Type.Optional(StringEnum(MODULATIONS, { description: "子载波调制方式，默认 QPSK" })),
      channel: Type.Optional(StringEnum(["awgn", "multipath"], { description: "信道模型，默认 awgn；multipath 为频选多径信道" })),
      channel_taps_db: Type.Optional(
        Type.Array(Type.Number(), { description: "multipath 各径功率（dB，第一径为 0），默认 [0,-3,-6]；径数-1 即时延扩展样点数" }),
      ),
      snr_db: Type.Optional(Type.Number({ description: "信噪比 Eb/N0，dB（metric=ber 时用），默认 20" })),
      n_symbols: Type.Optional(Type.Number({ description: "OFDM 符号数，默认 200（papr/ber 用；越大统计越准）" })),
      metric: Type.Optional(StringEnum(["papr", "ber", "spectrum"], { description: "输出指标，默认 papr" })),
      seed: Type.Optional(Type.Number({ description: "随机种子（可复现）" })),
    }),
    spec: { script: "ofdm.py", failureHint: "确认参数合法（n_used ≤ n_fft-1，cp_len ≥ 0，metric ∈ papr/ber/spectrum）。" },
  },
  // ── 信号 / 协议分析 ─────────────────────────────────────────────────────
  {
    name: "signal_analysis",
    label: "信号分析",
    description:
      "信号频谱分析工具：对输入信号执行 FFT，返回频率分量、功率谱密度和主要频率峰值。用于调制信号识别、干扰定位和频谱占用评估。上万点的长信号请用 signal_file 从文件读入，不要在对话里逐点生成 signal 数组。",
    promptSnippet: "FFT/频谱/功率谱密度/频率峰值分析调用 signal_analysis；上万点长信号用 signal_file 传文件路径。",
    parameters: Type.Object({
      signal: Type.Optional(
        Type.Array(Type.Number(), { description: "时域信号采样值序列（实数）；与 signal_file 二选一。短信号用这个。" }),
      ),
      signal_file: Type.Optional(
        Type.String({
          description: "信号文件路径；与 signal 二选一。适合上万点的长信号。文件内容可为 JSON 数组或空白/逗号/换行分隔的数值。",
        }),
      ),
      sample_rate_hz: Type.Number({ description: "采样率，Hz" }),
      window: Type.Optional(
        StringEnum(["rectangular", "hamming", "hanning", "blackman"], { description: "加窗类型，默认 hamming" }),
      ),
      num_peaks: Type.Optional(Type.Number({ description: "返回的频率峰值数量，默认 5" })),
    }),
    spec: {
      script: "signal_analysis.py",
      stdinJson: true, // 信号数组可能很大
      failureHint: "确认 uv sync 已装 numpy/scipy，且输入信号非空。",
    },
  },
  {
    name: "signal_diagnose",
    label: "信号诊断",
    description:
      "测量信号诊断（工程估计口径）：对实测数据估计 SNR、DC 偏置、削波（平顶段检测）、THD 谐波失真、IQ 幅度/相位失衡（需 i+q 双路，假设单音/窄带激励），输出指标与触发的症状条目。用于故障定位/信号质量体检；配合 knowledge/故障特征速查.md 定位根因。",
    promptSnippet:
      "实测信号「有没有问题/质量体检/故障定位」调用 signal_diagnose（三选一：signal / signal_file / i+q），再对照 knowledge/故障特征速查.md 给根因假设。",
    parameters: Type.Object({
      signal: Type.Optional(Type.Array(Type.Number(), { description: "实信号采样值（与 signal_file、i+q 三选一）" })),
      signal_file: Type.Optional(
        Type.String({ description: "信号文件路径（JSON 数组或空白/逗号分隔数值），长信号用这个" }),
      ),
      i: Type.Optional(Type.Array(Type.Number(), { description: "IQ 双路：同相分量 I（与 q 搭配，做 IQ 失衡估计）" })),
      q: Type.Optional(Type.Array(Type.Number(), { description: "IQ 双路：正交分量 Q" })),
      sample_rate_hz: Type.Number({ description: "采样率，Hz" }),
      fundamental_hz: Type.Optional(Type.Number({ description: "基波频率，Hz（THD 用；不给则取最强谱峰）" })),
      clip_level: Type.Optional(Type.Number({ description: "削波判定电平（绝对值），默认取峰值的 0.999 倍" })),
    }),
    spec: {
      script: "signal_diagnose.py",
      stdinJson: true, // 信号数组可能很大
      failureHint: "确认提供了 signal / signal_file / i+q 之一，且信号至少 32 点。",
    },
  },
  {
    name: "frame_parser",
    label: "帧解析",
    description:
      "通信协议帧解析工具：解析十六进制帧数据，提取帧头/帧长/载荷/CRC 等字段，校验完整性。支持自定义帧格式或常见预置格式（Ethernet II、简单 TLV）。",
    promptSnippet: "解析通信协议帧数据（hex）调用 frame_parser（Ethernet II / TLV / 自定义帧格式，CRC 校验）。",
    parameters: Type.Object({
      hex_data: Type.String({ description: "十六进制帧数据字符串（如 'AA55000C...'），不含 0x 前缀和空格" }),
      format: Type.Optional(
        StringEnum(["auto", "ethernet", "tlv", "custom"], {
          description: "帧格式：auto 自动检测，ethernet II 帧，tlv 简单 TLV，custom 自定义。默认 auto",
        }),
      ),
      custom_spec: Type.Optional(
        Type.String({
          description:
            '自定义帧格式规格（JSON 字符串），字段列表如：[{"name":"sync","bytes":2},{"name":"length","bytes":2,"endian":"big"},{"name":"payload","bytes":"length"},{"name":"crc","bytes":2,"type":"crc16"}]',
        }),
      ),
      endian: Type.Optional(StringEnum(["big", "little"], { description: "默认字节序，big 或 little，默认 big" })),
    }),
    spec: { script: "frame_parser.py", failureHint: "确认 hex_data 为合法的十六进制字符串（偶数长度）。" },
  },
  // ── 工程护栏 ────────────────────────────────────────────────────────────
  {
    name: "comms_lint",
    label: "代码体检",
    description:
      "通信代码体检（提示非拦截）：对项目内 .py/.m 文件启发式检查——数值是否标注单位、是否手写 FFT/erfc 等标准算法、随机过程是否设种子、协议解析是否文档化帧结构/字节序、是否硬编码密钥/绝对路径。改数值代码前后可各跑一次作为客观依据。",
    promptSnippet: "改通信/数值代码前后各调用一次 comms_lint 体检目标 .py/.m（单位/复现/NumPy/协议/密钥），提示非拦截。",
    parameters: Type.Object({
      path: Type.String({ description: "待检查文件（项目根目录内的 .py 或 .m），相对项目根或绝对路径" }),
      checks: Type.Optional(
        StringEnum(["all", "units", "numpy", "repro", "protocol", "secrets"], {
          description: "检查项，默认 all；也可逗号分隔多个（如 units,repro）",
        }),
      ),
      strict: Type.Optional(Type.Boolean({ description: "为 true 时若存在 error 级发现则非零退出（供 CI）；默认 false" })),
    }),
    spec: { script: "comms_lint.py", failureHint: "确认 path 指向项目内的 .py/.m 文件（禁止越界）。" },
  },
  {
    name: "equivalence_check",
    label: "等价校验",
    description:
      "数值等价校验（回归护栏）：分别运行 baseline 与 candidate 两条命令，解析各自 stdout 的数值向量，比对最大绝对/相对误差与相关系数，超 rtol/atol 即判 FAIL。用于优化前后「行为等价」的可复现断言。注意：本工具会执行传入的命令（受审批门管控），只应传入受信的验证命令（如跑本项目脚本、对比新旧实现）。",
    promptSnippet:
      "改动数值代码后用 equivalence_check 对同一输入跑「优化前 vs 优化后」两条命令比对等价；该工具会执行命令并触发审批，只传受信的验证命令。",
    parameters: Type.Object({
      baseline_cmd: Type.String({ description: "基准实现命令（如 'python -X utf8 old.py'）；以 shlex 切分、不经 shell 执行" }),
      candidate_cmd: Type.String({ description: "候选实现命令（如 'python -X utf8 new.py'）；以 shlex 切分、不经 shell 执行" }),
      stdin_data: Type.Optional(Type.String({ description: "同时喂给两条命令 stdin 的输入（可选）" })),
      rtol: Type.Optional(Type.Number({ description: "相对容差，默认 1e-6（无量纲）" })),
      atol: Type.Optional(Type.Number({ description: "绝对容差，默认 1e-9（无量纲）" })),
      parse: Type.Optional(
        StringEnum(["auto", "json", "floats"], { description: "输出解析方式，默认 auto（先试 JSON 数组，再回退抽取所有浮点数）" }),
      ),
      timeout_s: Type.Optional(Type.Number({ description: "每条命令超时秒，默认 60（上限 300）" })),
    }),
    spec: {
      script: "equivalence_check.py",
      timeoutMs: 120_000, // 内部各跑一条 baseline/candidate 命令（各自可达数十秒）
      failureHint: "确认 baseline_cmd/candidate_cmd 可运行且输出可解析为数值。",
    },
  },
  // ── 知识 / 可视化 ───────────────────────────────────────────────────────
  {
    name: "online_knowledge",
    label: "在线知识",
    description:
      "在线通信知识源查询：当本地 knowledge/ 不足，或问题涉及 RFC、标准、论文、协议版本时，查询白名单外部知识源并返回带 URL 的证据。支持 Wikidata、Hugging Face telecom KG、IETF/RFC、arXiv、3GPP OpenAPI 等入口。",
    promptSnippet:
      "本地 knowledge/ 未命中，或涉及 RFC/标准/论文/协议版本时调用 online_knowledge；回答必须给出来源 URL 并说明 warning 影响。",
    parameters: Type.Object({
      query: Type.String({ description: "查询文本，例如 MIMO、RFC9000、massive MIMO、5G Core API" }),
      intent: Type.Optional(
        StringEnum(["auto", "term", "protocol", "standard", "paper", "schema"], { description: "查询意图，默认 auto" }),
      ),
      source: Type.Optional(
        StringEnum(
          ["auto", "wikidata", "hf_telecom_kg", "ietf", "rfc", "arxiv", "3gpp_openapi", "3gpp_scout", "semantic_scholar", "openalex", "ieee"],
          { description: "知识源，默认 auto" },
        ),
      ),
      max_results: Type.Optional(Type.Number({ description: "最大结果数，1-10，默认 5" })),
    }),
    spec: {
      script: "online_knowledge.py",
      stdinJson: true,
      failureHint: "确认本机可联网；如查询可选 provider，请确认对应环境变量已设置。",
    },
  },
  {
    name: "plot",
    label: "通信绘图",
    description:
      "通信可视化绘图：生成星座图(constellation)、频谱(spectrum)、波形(waveform)、BER 曲线(ber_curve)、眼图(eye) 的 PNG，返回文件路径。图以文件交付，可在 Web UI 查看。",
    promptSnippet:
      "需要星座图/频谱/BER 曲线/波形/眼图时调用 plot 生成 PNG；回复中必须原样包含工具输出的「Markdown 内联」图片行（Web 界面内联显示），并告知文件路径。",
    parameters: Type.Object({
      plot_type: StringEnum(["constellation", "spectrum", "waveform", "ber_curve", "eye"], { description: "图类型" }),
      title: Type.Optional(Type.String({ description: "图标题" })),
      output_path: Type.Optional(
        Type.String({ description: "输出 PNG 路径，仅允许写入项目 plots/ 目录，默认 plots/<plot_type>.png" }),
      ),
      i: Type.Optional(Type.Array(Type.Number(), { description: "constellation：同相分量 I" })),
      q: Type.Optional(Type.Array(Type.Number(), { description: "constellation：正交分量 Q" })),
      signal: Type.Optional(Type.Array(Type.Number(), { description: "spectrum/waveform/eye：时域信号采样值" })),
      sample_rate_hz: Type.Optional(Type.Number({ description: "spectrum/waveform：采样率 Hz" })),
      samples_per_symbol: Type.Optional(Type.Number({ description: "eye：每符号采样数" })),
      snr_db: Type.Optional(Type.Array(Type.Number(), { description: "ber_curve：Eb/N0 序列 dB" })),
      ber: Type.Optional(Type.Array(Type.Number(), { description: "ber_curve：对应 BER 序列" })),
      series: Type.Optional(Type.Any({ description: "ber_curve：多曲线 [{label, snr_db, ber}]" })),
    }),
    spec: {
      script: "plot.py",
      stdinJson: true, // 信号可能很大
      failureHint: "确认 uv sync 已装 matplotlib，且提供了该图类型所需字段。",
    },
  },
]
