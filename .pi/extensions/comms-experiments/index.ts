import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"
import { Type } from "typebox"
import path from "node:path"
import { ExperimentEngine, experimentIdFor, safeFile, type Experiment } from "./engine"

export function experimentSummary(experiment: Experiment) {
  return { ...experiment, runs: experiment.runs.map(({ vector: _vector, ...run }) => run) }
}

export default function (pi: ExtensionAPI, engine = new ExperimentEngine()) {
  pi.registerTool({
    name: "experiment_status", label: "实验记录", description: "读取本会话实验的目标、允许文件、基线、每轮指标与验证结论。", parameters: Type.Object({}),
    async execute(_id, _params, _signal, _update, ctx) {
      const id = experimentIdFor(ctx.sessionManager)
      if (!id) throw new Error("当前会话没有实验，请先在 Web 中创建。")
      return { content: [{ type: "text", text: JSON.stringify(experimentSummary(engine.read(id))) }], details: {} }
    },
  })
  pi.registerTool({
    name: "experiment_run", label: "验证实验候选", description: "在本会话的隔离工作区运行已冻结的验证与基准命令。首次测基线，后续测候选；自动记录指标、种子、单位和数值等价证据。", parameters: Type.Object({}),
    async execute(_id, _params, signal, _update, ctx) {
      const id = experimentIdFor(ctx.sessionManager)
      if (!id) throw new Error("请先创建实验。")
      const stop = () => engine.stop(id, ctx.sessionManager.getSessionId())
      signal?.addEventListener("abort", stop, { once: true })
      try {
        const experiment = await engine.run(id, ctx.sessionManager.getSessionId())
        return { content: [{ type: "text", text: JSON.stringify(experimentSummary(experiment)) }], details: { experimentId: id } }
      } finally { signal?.removeEventListener("abort", stop) }
    },
  })
  pi.registerTool({
    name: "experiment_note", label: "更新实验说明", description: "保存当前候选的设计理由、已知限制和下一轮建议。", parameters: Type.Object({ notes: Type.String({ maxLength: 8000 }) }),
    async execute(_id, params, _signal, _update, ctx) {
      const id = experimentIdFor(ctx.sessionManager)
      if (!id) throw new Error("请先创建实验。")
      engine.note(id, ctx.sessionManager.getSessionId(), params.notes)
      return { content: [{ type: "text", text: "实验说明已保存。" }], details: {} }
    },
  })
  pi.on("tool_call", (event, ctx) => {
    const id = experimentIdFor(ctx.sessionManager)
    if (!id) return
    const experiment = engine.read(id)
    if (experiment.status === "applied" || experiment.status === "completed") return
    if (["edit", "write"].includes(event.toolName)) {
      const requested = path.resolve(ctx.cwd, String((event.input as Record<string, unknown>).path ?? ""))
      const relative = path.relative(experiment.candidateDirectory, requested)
      try {
        engine.requireOwner(experiment, ctx.sessionManager.getSessionId())
        if (!experiment.config.allowedFiles.includes(relative) || safeFile(experiment.candidateDirectory, relative) !== requested || experiment.pendingApply || experiment.stopRequested || experiment.status === "running" || experiment.runs.filter((run) => run.kind === "candidate").length >= experiment.config.maxIterations) throw new Error("本次修改不在已确认的候选范围内、验证正在运行、实验已停止、需要恢复，或已达到轮数预算。")
      } catch (error) { return { block: true, reason: error instanceof Error ? error.message : String(error) } }
    }
    if (event.toolName === "bash" || event.toolName === "equivalence_check" || event.toolName.startsWith("mcp_")) return { block: true, reason: "实验中请使用 experiment_run 执行已确认的命令；其它执行入口未纳入本实验范围。" }
  })
  pi.on("before_agent_start", (_event, ctx) => {
    const id = experimentIdFor(ctx.sessionManager)
    if (!id) return
    const experiment = engine.read(id)
    if (["applied", "completed"].includes(experiment.status)) return
    return { message: { customType: "experiment-context", display: false, content: `当前实验：${JSON.stringify(experimentSummary(experiment))}\n只修改 candidateDirectory 内 allowedFiles 的绝对路径；验证调用 experiment_run。未通过验证的候选不能应用。达到 maxIterations 后停止提出新轮次。` } }
  })
}
