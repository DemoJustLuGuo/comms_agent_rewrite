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
  plot: "绘图 图片 星座图 频谱图 眼图 ber曲线 误码率曲线 曲线",
}

export const DOMAIN_NAMES = DEFS.map((definition) => definition.name)
export const DISCOVERY_NAMES = ["comms_find", "comms_batch"]
export const CORE_NAMES = ["read", "grep", "find", "ls", "bash", "edit", "write", "link_budget", ...DISCOVERY_NAMES]

/**
 * \u51fa\u56fe\u610f\u56fe\uff1a\u7528\u6237\u8bf4\u300c\u753b / \u7ed8\u5236 / \u51fa\u56fe\u300d\u65f6\uff0cplot \u5fc5\u987b\u8fdb\u5165\u53d1\u73b0\u7ed3\u679c\u3002
 *
 * \u8bc4\u5206\u91cc\u300c\u661f\u5ea7\u56fe\u300d\u5bf9 plot \u4e0e modulation \u90fd\u547d\u4e2d\uff08modulation \u522b\u540d\u662f\u300c\u661f\u5ea7\u300d\uff09\uff0c
 * \u4e24\u8005\u540c\u5206\u800c\u540c\u5206\u6309\u6570\u7ec4\u987a\u5e8f\u6392\uff0cplot \u6392\u5728 channel \u4e4b\u540e\u88ab limit \u622a\u6389\u2014\u2014\u6a21\u578b\u5df2\u62ff\u5230
 * modulation \u7684\u661f\u5ea7\u70b9\u5374\u8c03\u4e0d\u5230 plot\uff0c\u4e8e\u662f\u9000\u56de bash \u81ea\u5df1\u88c5 matplotlib\uff08\u5386\u53f2\u6545\u969c\uff09\u3002
 * \u8fd9\u91cc\u7528\u663e\u5f0f\u610f\u56fe\u8bcd\u52a0\u6743\uff0c\u800c\u4e0d\u662f\u8c03\u5927 limit \u6216\u4f9d\u8d56\u6392\u5e8f\u5de7\u5408\u3002
 */
const DRAW_INTENT = /(\u7ed8\u5236|\u753b|\u51fa\u56fe|\u53ef\u89c6\u5316|\u7ed8\u56fe|\u56fe\u7247|png|\u661f\u5ea7\u56fe|\u9891\u8c31\u56fe|\u773c\u56fe|\u66f2\u7ebf\u56fe)/u

export function findTools(query: string, available: string[], limit = 3) {
  const normalized = query.toLowerCase().trim()
  const tokens = normalized.match(/[a-z][a-z0-9_]+|[\u4e00-\u9fff]{2,}/g) ?? []
  const wantsDraw = DRAW_INTENT.test(normalized)
  return DEFS.filter((definition) => available.includes(definition.name)).map((definition) => {
    const aliases = (ALIASES[definition.name] ?? "").split(" ")
    const text = `${definition.name} ${definition.label} ${definition.description}`.toLowerCase()
    const base = aliases.reduce((total, alias) => total + (normalized.includes(alias) ? 8 : 0), 0)
      + tokens.reduce((total, token) => total + (text.includes(token) ? 2 : 0), 0)
    const score = base + (wantsDraw && definition.name === "plot" && base > 0 ? 12 : 0)
    return { definition, score }
  }).filter((match) => match.score > 0).sort((first, second) => second.score - first.score)
    .slice(0, Math.max(1, Math.min(5, limit))).map((match) => match.definition)
}

export function selectTools(available: string[], preset: "none" | "default" | "full", experimentActive = false) {
  if (preset === "none") return []
  const names = preset === "full" ? available : CORE_NAMES.filter((name) => available.includes(name))
  if (!experimentActive) return names.filter((name) => !name.startsWith("experiment_"))
  return [...new Set([...names, ...available.filter((name) => name.startsWith("experiment_"))])].filter((name) => name !== "bash" && name !== "equivalence_check" && !name.startsWith("mcp_"))
}
