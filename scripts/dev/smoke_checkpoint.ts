/**
 * git-checkpoint 扩展冒烟：临时 git 仓库上跑真实 checkpoint→改动→回滚闭环。
 * mock 的 pi.exec 语义与 pi 的 ExecResult{stdout,stderr,code} 对齐（非零不抛）。
 * 运行：bun scripts/dev/smoke_checkpoint.ts
 */
import gitCheckpoint from "../../.pi/extensions/git-checkpoint"
import { spawnSync } from "node:child_process"
import { mkdtempSync, writeFileSync, readFileSync, existsSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"

type ToolCallHandler = (event: any, ctx?: any) => Promise<unknown>
let onToolCall: ToolCallHandler | undefined
let rollbackHandler: ((args: string, ctx: any) => Promise<void>) | undefined

const mockPi = {
  exec: async (cmd: string, args: string[]) => {
    const r = spawnSync(cmd, args, { encoding: "utf8" })
    return { stdout: r.stdout ?? "", stderr: r.stderr ?? "", code: r.status ?? 1, killed: false }
  },
  on: (name: string, h: ToolCallHandler) => {
    if (name === "tool_call") onToolCall = h
  },
  registerCommand: (name: string, def: { handler: (args: string, ctx: any) => Promise<void> }) => {
    if (name === "rollback") rollbackHandler = def.handler
  },
  registerTool: () => {},
} as any

gitCheckpoint(mockPi)
if (!onToolCall || !rollbackHandler) throw new Error("扩展未注册 tool_call/rollback")

// 临时 git 仓库
const repo = mkdtempSync(path.join(tmpdir(), "ckpt-"))
const g = (...args: string[]) => spawnSync("git", ["-C", repo, ...args], { encoding: "utf8" })
g("init", "-q")
g("config", "user.email", "t@t")
g("config", "user.name", "t")
const tracked = path.join(repo, "algo.py")
writeFileSync(tracked, "original = 1\n")
g("add", "-A")
g("commit", "-qm", "init")

let failed = 0
const check = (label: string, cond: boolean) => {
  console.log(`[${cond ? "PASS" : "FAIL"}] ${label}`)
  if (!cond) failed++
}

// 场景 1：已跟踪文件 edit → checkpoint → 模型改写 → /rollback 恢复
await onToolCall({ toolName: "edit", input: { path: tracked } })
writeFileSync(tracked, "optimized = 2\n") // 模拟模型写入
const notices: string[] = []
const ctx = {
  ui: {
    select: async (_t: string, items: string[]) => items[0],
    notify: (m: string) => notices.push(m),
  },
}
await rollbackHandler("", ctx)
// autocrlf 环境下 checkout 会以 CRLF 重写文本，比较前归一化行尾
check("已跟踪文件回滚到改前内容", readFileSync(tracked, "utf8").replace(/\r\n/g, "\n") === "original = 1\n")

// 场景 2：write 新文件 → checkpoint（tracked=false）→ 写入 → /rollback 删除
const fresh = path.join(repo, "new_module.py")
await onToolCall({ toolName: "write", input: { path: fresh } })
writeFileSync(fresh, "print('new')\n")
await rollbackHandler("", ctx)
check("新建文件回滚即删除", !existsSync(fresh))

// 场景 3：非 write 类工具不打 checkpoint
await onToolCall({ toolName: "read", input: { path: tracked } })
await rollbackHandler("", ctx)
check("read 不产生 checkpoint", notices.some((n) => n.includes("没有可回滚")))

console.log(failed ? `${failed} 个用例失败` : "全部通过")
process.exit(failed ? 1 : 0)
