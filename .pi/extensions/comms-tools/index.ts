/**
 * comms 域工具扩展：把 tools/ 下的 Python 计算核注册为 pi 自定义工具。
 * 工具清单与 schema 见 defs.ts；spawn/超时/错误包装见 runner.ts。
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"
import { DEFS } from "./defs"
import { runPyTool } from "./runner"
import { Type } from "typebox"
import { findTools, selectTools } from "./catalog"
import { runCalculationBatch } from "./batch"

export default function (pi: ExtensionAPI) {
  let preset: "none" | "default" | "full" = "full"
  const applyPreset = () => pi.setActiveTools(selectTools(pi.getAllTools().map((tool) => tool.name), preset))
  for (const def of DEFS) {
    pi.registerTool({
      name: def.name,
      label: def.label,
      description: def.description,
      ...(def.promptSnippet ? { promptSnippet: def.promptSnippet } : {}),
      parameters: def.parameters,
      async execute(_toolCallId, params, signal) {
        const result = await runPyTool(def.name, def.spec, params, signal)
        if (!result.details.ok) throw new Error(result.content[0].text)
        return result
      },
    })
  }
  pi.registerTool({
    name: "comms_find",
    label: "查找通信工具",
    description: "按任务查找并启用通信工具。需要频谱、信道、调制、编码、诊断、标准查询或数值等价验证时先查询；返回后下一次模型请求可直接调用匹配工具。",
    promptSnippet: "需要通信计算时先用 comms_find 查询工具；缺参数先询问，工具失败报告原因，不读 tools/*.py 替代工具计算。",
    promptGuidelines: ["链路预算直接调用 link_budget；其它定量通信任务先调用 comms_find，再调用找到的工具。组合计算用 comms_batch，输入和结果必须保持单位一致。"],
    parameters: Type.Object({ query: Type.String({ minLength: 2 }), limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 5 })) }),
    async execute(_id, params) {
      const definitions = findTools(params.query, pi.getAllTools().map((tool) => tool.name), params.limit)
      pi.setActiveTools([...new Set([...pi.getActiveTools(), ...definitions.map((definition) => definition.name)])])
      return { content: [{ type: "text", text: definitions.length ? definitions.map((definition) => `${definition.name}：${definition.description}`).join("\n") : "未找到匹配工具。可用更具体的通信术语重试；不要编造计算结果。" }], details: { tools: definitions.map((definition) => ({ name: definition.name, label: definition.label })) } }
    },
  })
  pi.registerTool({
    name: "comms_batch",
    label: "组合通信计算",
    description: "顺序组合 link_budget、interference、capacity(awgn)，最多 8 步。input 字段可用 {$from:'步骤id.输出字段',unit:'dBm|dB|Hz...'} 引用前序结果；仅接受同单位传值。链路预算输出 rx_power_dbm、fspl_db、eirp_dbm；干扰输出 ratio_db、interference_dbm；容量输出 capacity_bps、spectral_efficiency。",
    parameters: Type.Object({ steps: Type.Array(Type.Object({ id: Type.String(), tool: Type.String(), input: Type.Record(Type.String(), Type.Unknown()) }), { minItems: 1, maxItems: 8 }) }),
    async execute(_id, params, signal, _update, ctx) {
      const result = await runCalculationBatch(params.steps, pi.getAllTools().map((tool) => tool.name), ctx, signal)
      return result
    },
  })
  pi.registerCommand("comms-tools", {
    description: "通信工具显示策略：default 按需、full 全量、none 关闭",
    handler: async (args) => {
      if (!["none", "default", "full"].includes(args.trim())) throw new Error("工具策略必须为 default、full 或 none。")
      preset = args.trim() as typeof preset
      pi.appendEntry("comms-tool-policy", { preset })
      applyPreset()
    },
  })
  pi.on("session_start", (_event, ctx) => {
    const entry = ctx.sessionManager.getBranch().findLast((entry) => entry.type === "custom" && entry.customType === "comms-tool-policy")
    if (entry?.type === "custom" && ["none", "default", "full"].includes((entry.data as { preset?: string })?.preset ?? "")) {
      preset = (entry.data as { preset: typeof preset }).preset
      applyPreset()
    }
  })
  pi.on("before_agent_start", () => {
    if (preset !== "full") applyPreset()
  })
  pi.on("tool_result", (event) => {
    if (event.toolName === "comms_batch" && event.details?.ok === false) return { isError: true }
  })
}
