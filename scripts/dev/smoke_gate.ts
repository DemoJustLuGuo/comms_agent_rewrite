/**
 * 审批门离线单测：mock ExtensionAPI/ctx，验证放行/拒绝/无 UI fail-closed 三条路径。
 * 运行：bun scripts/dev/smoke_gate.ts
 */
import approvalGate, { summarize } from "../../.pi/extensions/approval-gate"

type Handler = (event: any, ctx: any) => Promise<{ block: boolean; reason?: string } | void>
let handler: Handler | undefined
approvalGate({ on: (name: string, h: Handler) => name === "tool_call" && (handler = h), registerTool: () => {}, registerCommand: () => {} } as any)

if (!handler) throw new Error("tool_call handler 未注册")

const mkCtx = (hasUI: boolean, answer = true) => ({ hasUI, ui: { confirm: async () => answer } })
const bashEvent = { toolName: "bash", input: { command: "python tests.py" } }

let failed = 0
const check = (label: string, cond: boolean) => {
  console.log(`[${cond ? "PASS" : "FAIL"}] ${label}`)
  if (!cond) failed++
}

// 1) 有 UI + 用户同意 → 放行（返回 undefined）
check("同意→放行", (await handler(bashEvent, mkCtx(true, true))) === undefined)
// 2) 有 UI + 用户拒绝 → block
const denied = await handler(bashEvent, mkCtx(true, false))
check("拒绝→block", !!denied && denied.block === true)
// 3) 无 UI（headless）→ fail-closed block
delete process.env.COMMS_APPROVAL
const headless = await handler(bashEvent, mkCtx(false))
check("无UI→fail-closed", !!headless && headless.block === true)
// 4) 无 UI + COMMS_APPROVAL=allow-all → 放行
process.env.COMMS_APPROVAL = "allow-all"
check("无UI+allow-all→放行", (await handler(bashEvent, mkCtx(false))) === undefined)
// 5) 非受控工具（read）→ 直接放行
check("read→不拦", (await handler({ toolName: "read", input: {} }, mkCtx(false))) === undefined)
// 6) equivalence_check 纳管 + 摘要含两条命令
delete process.env.COMMS_APPROVAL
const eq = await handler({ toolName: "equivalence_check", input: { baseline_cmd: "python old.py", candidate_cmd: "python new.py" } }, mkCtx(false))
check("equivalence_check→纳管", !!eq && eq.block === true)
check("摘要含命令", summarize("equivalence_check", { baseline_cmd: "python old.py", candidate_cmd: "python new.py" }).includes("old.py"))

process.exit(failed ? 1 : 0)
