import { DEFS } from "./defs"

const ALIASES: Record<string, string> = {
  link_budget: "链路预算 自由空间 接收功率 fspl eirp",
  path_loss: "路径损耗 城区传播 hata cost231",
  rf_chain: "接收链 灵敏度 噪声系数 噪声底 friis nf ktb",
  interference: "干扰 载干比 信干噪比 ci sinr",
  channel_profile: "信道特性 多径 相干带宽 时延扩展",
  fade_margin: "衰落余量 可用度 可靠性 中断概率",
  ber_snr: "误码率 信噪比 ber snr ebn0",
  modulation: "调制 星座 灰码 evm qam psk",
  channel: "信道仿真 瑞利 莱斯 awgn rayleigh rician",
  channel_coding: "信道编码 纠错 卷积 turbo ldpc fec",
  capacity: "容量 香农 频谱效率 mimo ebn0 shannon",
  pulse_shaping: "脉冲成形 匹配滤波 眼图 isi rrc",
  ofdm: "多载波 子载波 循环前缀 papr ofdm",
  equalizer: "均衡器 均衡 lms mmse zf",
  link_adaptation: "链路自适应 调制编码策略 mcs amc",
  spread_spectrum: "扩频 抗干扰 处理增益 dsss fhss",
  beamforming: "波束赋形 阵列 天线 mrt ula",
  signal_analysis: "频谱 fft 功率谱 波形分析 频率峰值",
  signal_diagnose: "信号诊断 削波 直流偏置 故障定位",
  sync_estimate: "同步 频偏 定时偏差 cfo",
  frame_parser: "协议帧 帧解析 十六进制 ethernet tlv crc",
  comms_lint: "通信代码检查 单位检查 代码优化 体检",
  equivalence_check: "等价校验 数值回归 基线 候选 容差",
  online_knowledge: "通信标准 在线知识 rfc arxiv 3gpp",
  plot: "绘图 图片 星座图 频谱图 眼图 ber曲线",
}

export const DOMAIN_NAMES = DEFS.map((definition) => definition.name)
export const DISCOVERY_NAMES = ["comms_find", "comms_batch"]
export const CORE_NAMES = ["read", "grep", "find", "ls", "bash", "edit", "write", "link_budget", ...DISCOVERY_NAMES]

export function findTools(query: string, available: string[], limit = 3) {
  const normalized = query.toLowerCase().trim()
  const tokens = normalized.match(/[a-z][a-z0-9_]+|[\u4e00-\u9fff]{2,}/g) ?? []
  return DEFS.filter((definition) => available.includes(definition.name)).map((definition) => {
    const aliases = (ALIASES[definition.name] ?? "").split(" ")
    const text = `${definition.name} ${definition.label} ${definition.description}`.toLowerCase()
    const score = aliases.reduce((total, alias) => total + (normalized.includes(alias) ? 8 : 0), 0)
      + tokens.reduce((total, token) => total + (text.includes(token) ? 2 : 0), 0)
    return { definition, score }
  }).filter((match) => match.score > 0).sort((first, second) => second.score - first.score)
    .slice(0, Math.max(1, Math.min(5, limit))).map((match) => match.definition)
}

export function selectTools(available: string[], preset: "none" | "default" | "full") {
  if (preset === "none") return []
  if (preset === "full") return [...available]
  return CORE_NAMES.filter((name) => available.includes(name))
}
