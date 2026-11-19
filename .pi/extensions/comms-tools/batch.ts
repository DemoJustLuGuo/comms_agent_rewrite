import { validateToolArguments } from "@earendil-works/pi-ai"
import { DEFS } from "./defs"
import { authorizeTool } from "./approval"
import type { ExtensionContext } from "@earendil-works/pi-coding-agent"
import { runPyTool, type PyToolResult } from "./runner"

const INPUT_UNITS: Record<string, Record<string, string>> = {
  link_budget: { tx_power_dbm: "dBm", tx_gain_dbi: "dBi", rx_gain_dbi: "dBi", freq_mhz: "MHz", distance_km: "km", other_losses_db: "dB" },
  interference: { carrier_dbm: "dBm", noise_floor_dbm: "dBm", bandwidth_hz: "Hz", nf_db: "dB", required_ci_db: "dB" },
  capacity: { bandwidth_hz: "Hz", snr_db: "dB", spectral_efficiency: "bit/s/Hz" },
}

export interface CalculationStep { id: string; tool: string; input: Record<string, unknown> }

export function resolveInput(input: Record<string, unknown>, tool: string, results: Map<string, PyToolResult>) {
  return Object.fromEntries(Object.entries(input).map(([field, value]) => {
    if (value && typeof value === "object" && "$from" in value) {
      const reference = value as { $from: string; unit: string }
      const [stepId, outputField, ...rest] = String(reference.$from).split(".")
      const details = results.get(stepId)?.details
      const data = details?.data as Record<string, unknown> | undefined
      const units = details?.units as Record<string, string> | undefined
      if (rest.length || !data || !Object.hasOwn(data, outputField)) throw new Error(`引用 ${reference.$from} 不存在或不是已完成步骤的结构化字段。`)
      if (!reference.unit || reference.unit !== units?.[outputField] || reference.unit !== INPUT_UNITS[tool]?.[field]) throw new Error(`引用 ${reference.$from} 的单位与 ${tool}.${field} 不一致。`)
      return [field, data[outputField]]
    }
    return [field, value]
  }))
}

export async function runCalculationBatch(steps: CalculationStep[], available: string[], ctx: Pick<ExtensionContext, "hasUI" | "ui"> & { sessionManager?: ExtensionContext["sessionManager"] }, signal?: AbortSignal) {
  const results = new Map<string, PyToolResult>()
  const records: Array<{ id: string; tool: string; input: Record<string, unknown>; result: PyToolResult }> = []
  if (!steps.length || steps.length > 8 || new Set(steps.map((step) => step.id)).size !== steps.length) throw new Error("计算链必须包含 1–8 个唯一编号的步骤。")
  for (const step of steps) {
    if (!/^[a-z][a-z0-9_]*$/.test(step.id) || !INPUT_UNITS[step.tool] || !available.includes(step.tool)) throw new Error(`步骤 ${step.id} 使用了未允许的组合工具 ${step.tool}。`)
    if (step.tool === "capacity" && step.input.mode !== "awgn") throw new Error("组合中的 capacity 仅支持 awgn。")
  }
  for (const step of steps) {
    if (signal?.aborted) throw new Error("计算链已停止。")
    const definition = DEFS.find((item) => item.name === step.tool)!
    const input = resolveInput(step.input, step.tool, results)
    const args = validateToolArguments(definition, { type: "toolCall", id: step.id, name: step.tool, arguments: input })
    const denied = await authorizeTool(step.tool, args, ctx)
    if (denied) throw new Error(denied.reason)
    const result = await runPyTool(step.tool, definition.spec, args, signal, ctx.sessionManager?.getCwd?.())
    records.push({ id: step.id, tool: step.tool, input: args, result })
    if (!result.details.ok || !result.details.data) return { content: result.content, details: { ok: false, failedStep: step.id, steps: records } }
    results.set(step.id, result)
  }
  return { content: [{ type: "text" as const, text: records.map((record) => `${record.id} · ${record.tool}\n${record.result.content[0].text}`).join("\n\n") }], details: { ok: true, steps: records } }
}
