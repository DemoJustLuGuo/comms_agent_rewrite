/**
 * 审批门（傻瓜式审批的 pi 实现）：高风险工具调用前必须用户点头。
 *
 * - 拦截内建 bash / write / edit，以及会在工具内部执行命令的域工具 equivalence_check
 *   （opencode 时代该工具绕过 bash 审批的缺陷在此根治：统一走同一道门）。
 * - 用户拒绝 → { block: true }，模型收到拒绝原因可改道。
 * - 无交互界面（--print / RPC 未透传 confirm）时 fail-closed：默认拒绝，
 *   仅当显式设置 COMMS_APPROVAL=allow-all（如脚本化验证）才放行。
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"

const GATED = new Set(["bash", "write", "edit", "equivalence_check"])

/** 给用户看的操作摘要：够判断风险即可，长内容截断。 */
export function summarize(toolName: string, input: Record<string, unknown>): string {
  const clip = (s: unknown, n = 200) => String(s ?? "").slice(0, n)
  switch (toolName) {
    case "bash":
      return `执行命令：${clip(input.command)}`
    case "write":
      return `写入文件：${clip(input.path)}（约 ${String(input.content ?? "").length} 字符）`
    case "edit":
      return `修改文件：${clip(input.path)}`
    case "equivalence_check":
      return `数值等价校验将执行两条命令：\n  基准：${clip(input.baseline_cmd)}\n  候选：${clip(input.candidate_cmd)}`
    default:
      return clip(JSON.stringify(input))
  }
}

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event, ctx) => {
    if (!GATED.has(event.toolName)) return

    const summary = summarize(event.toolName, (event.input ?? {}) as Record<string, unknown>)

    if (!ctx.hasUI) {
      if (process.env.COMMS_APPROVAL === "allow-all") return
      return {
        block: true,
        reason:
          "当前无交互界面，高风险操作默认拒绝（fail-closed）。请在交互模式下重试，或由运维显式设置 COMMS_APPROVAL=allow-all。",
      }
    }

    const ok = await ctx.ui.confirm(`审批：${event.toolName}`, summary)
    if (!ok) {
      return { block: true, reason: "用户拒绝了本次操作。请解释意图或提出替代方案，不要原样重试。" }
    }
  })
}
