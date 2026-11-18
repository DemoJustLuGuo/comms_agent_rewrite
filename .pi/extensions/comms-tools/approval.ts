import type { ExtensionContext } from "@earendil-works/pi-coding-agent"
import { DOMAIN_NAMES, DISCOVERY_NAMES } from "./catalog"
import { ExperimentEngine, experimentIdFor } from "../comms-experiments/engine"

export type ApprovalTier = "read" | "write" | "exec"

export function approvalTier(name: string): ApprovalTier {
  if (["edit", "write", "plot"].includes(name)) return "write"
  if (name === "equivalence_check" || name === "experiment_run" || name.startsWith("mcp_") || name === "bash") return "exec"
  if (name === "experiment_status") return "read"
  if (name === "experiment_note") return "write"
  if (["read", "grep", "find", "ls", ...DISCOVERY_NAMES, ...DOMAIN_NAMES].includes(name)) return "read"
  return "exec"
}

export function operationSummary(name: string, input: Record<string, unknown>): string {
  const clip = (value: unknown) => String(value ?? "").slice(0, 500)
  if (name === "bash") return `执行命令：${clip(input.command)}`
  if (name === "edit" || name === "write") return `修改目标：${clip(input.path)}`
  if (name === "plot") return `生成图片：${clip(input.output_path ?? `plots/${input.plot_type}.png`)}`
  if (name === "equivalence_check") return `基准：${clip(input.baseline_cmd)}\n候选：${clip(input.candidate_cmd)}`
  if (name.startsWith("mcp_matlab_")) return `MATLAB 工具：${name}\n${clip(input.code ?? input.script_path ?? input.filename ?? "工具调用")}`
  return `工具：${name}`
}

export async function authorizeTool(name: string, input: Record<string, unknown>, ctx: Pick<ExtensionContext, "hasUI" | "ui"> & { sessionManager?: ExtensionContext["sessionManager"]; signal?: AbortSignal }) {
  const tier = approvalTier(name)
  if (tier === "read") return
  if (!ctx.hasUI) {
    if (process.env.COMMS_APPROVAL === "allow-all") return
    return { block: true, reason: "当前无交互界面，高风险操作默认拒绝（fail-closed）。" }
  }
  let summary = operationSummary(name, input)
  if (name === "experiment_run" && ctx.sessionManager) {
    const id = experimentIdFor(ctx.sessionManager)
    if (!id) return { block: true, reason: "当前会话没有实验。" }
    const preview = new ExperimentEngine().preview(id)
    summary = `工作区：${preview.directory}\n${preview.commands.map((argv) => argv.join(" ")).join("\n")}`
  }
  const accepted = await ctx.ui.confirm(`审批：${tier === "write" ? "写入" : "执行"} · ${name}`, summary, { signal: ctx.signal })
  if (!accepted) return { block: true, reason: "用户拒绝了本次操作。请解释意图或提出替代方案，不要原样重试。" }
}
