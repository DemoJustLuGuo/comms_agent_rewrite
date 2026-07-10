/**
 * comms 域工具扩展：把 tools/ 下的 Python 计算核注册为 pi 自定义工具。
 *
 * A2 原型先注册两个代表：link_budget（小参数，argv 型）与 plot（大数组，stdin 型）。
 * Phase B 其余 13 个工具按 DEFS 里同样的声明式条目追加，不再各写一份桥接文件。
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"
import { Type } from "typebox"
import { StringEnum } from "@earendil-works/pi-ai"
import { runPyTool, type PyToolSpec } from "./runner"

interface CommsToolDef {
  name: string
  label: string
  description: string
  promptSnippet?: string
  parameters: ReturnType<typeof Type.Object>
  spec: PyToolSpec
}

const DEFS: CommsToolDef[] = [
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
      other_losses_db: Type.Optional(
        Type.Number({ description: "其他损耗（馈线/大气等），dB，默认 0" }),
      ),
    }),
    spec: {
      script: "link_budget.py",
      failureHint: "确认 uv sync 已建 .venv 且输入合法（距离/频率为正数）。",
    },
  },
  {
    name: "plot",
    label: "通信绘图",
    description:
      "通信可视化绘图：生成星座图(constellation)、频谱(spectrum)、波形(waveform)、BER 曲线(ber_curve)、眼图(eye) 的 PNG，返回文件路径。图以文件交付，可在 Web UI 查看。",
    promptSnippet:
      "需要星座图/频谱/BER 曲线/波形/眼图时调用 plot 生成 PNG，并把返回的文件路径告诉用户。",
    parameters: Type.Object({
      plot_type: StringEnum(["constellation", "spectrum", "waveform", "ber_curve", "eye"], {
        description: "图类型",
      }),
      title: Type.Optional(Type.String({ description: "图标题" })),
      output_path: Type.Optional(
        Type.String({ description: "输出 PNG 路径，仅允许写入项目 plots/ 目录，默认 plots/<plot_type>.png" }),
      ),
      i: Type.Optional(Type.Array(Type.Number(), { description: "constellation：同相分量 I" })),
      q: Type.Optional(Type.Array(Type.Number(), { description: "constellation：正交分量 Q" })),
      signal: Type.Optional(
        Type.Array(Type.Number(), { description: "spectrum/waveform/eye：时域信号采样值" }),
      ),
      sample_rate_hz: Type.Optional(Type.Number({ description: "spectrum/waveform：采样率 Hz" })),
      samples_per_symbol: Type.Optional(Type.Number({ description: "eye：每符号采样数" })),
      snr_db: Type.Optional(Type.Array(Type.Number(), { description: "ber_curve：Eb/N0 序列 dB" })),
      ber: Type.Optional(Type.Array(Type.Number(), { description: "ber_curve：对应 BER 序列" })),
      series: Type.Optional(Type.Any({ description: "ber_curve：多曲线 [{label, snr_db, ber}]" })),
    }),
    spec: {
      script: "plot.py",
      stdinJson: true, // 信号可能很大，stdin 传参避免命令行长度上限
      failureHint: "确认 uv sync 已装 matplotlib，且提供了该图类型所需字段。",
    },
  },
]

export default function (pi: ExtensionAPI) {
  for (const def of DEFS) {
    pi.registerTool({
      name: def.name,
      label: def.label,
      description: def.description,
      ...(def.promptSnippet ? { promptSnippet: def.promptSnippet } : {}),
      parameters: def.parameters,
      async execute(_toolCallId, params, signal) {
        return runPyTool(def.name, def.spec, params, signal)
      },
    })
  }
}
