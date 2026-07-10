/**
 * Git checkpoint 回滚扩展（傻瓜式一键回退的 pi 实现）。
 *
 * 行为：
 * - 模型每次 edit/write 前（审批门之后、真正写入之前），对目标文件所在的 git 仓库
 *   打一个 checkpoint（git stash create 快照，不动工作区、不产生分支噪音）。
 *   注意 real_projects/ModulationPy 是嵌套的独立 git 仓库——checkpoint 打在文件
 *   所属仓库上，而不是外层工作区。
 * - /rollback 命令列出本会话的 checkpoint（新→旧），选中后恢复该文件：
 *   已跟踪文件从快照 checkout 回来；当时不存在的新建文件则直接删除。
 *
 * 已知边界：快照按文件恢复（git checkout <ref> -- <file>），不整仓回滚；
 * 跨会话的历史回退请直接用目标仓库的 git。
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"
import { unlink } from "node:fs/promises"
import path from "node:path"

interface Checkpoint {
  repo: string
  /** 仓库相对路径（git 用） */
  rel: string
  /** 展示用绝对路径 */
  abs: string
  /** stash 快照 ref；干净工作区时为 HEAD */
  ref: string
  /** checkpoint 时文件是否已被 git 跟踪；false → 回滚 = 删除新建文件 */
  tracked: boolean
  at: string
}

const WRITE_TOOLS = new Set(["edit", "write"])

export default function (pi: ExtensionAPI) {
  const stack: Checkpoint[] = []

  // pi.exec 返回 ExecResult{stdout,stderr,code}，非零退出不抛异常——按 code 判定
  const exec = async (cmd: string, args: string[]) => {
    const r = await pi.exec(cmd, args)
    return { ok: r.code === 0, stdout: (r.stdout ?? "").trim(), err: (r.stderr ?? "").trim() }
  }

  pi.on("tool_call", async (event) => {
    if (!WRITE_TOOLS.has(event.toolName)) return
    const input = (event.input ?? {}) as Record<string, unknown>
    const raw = String(input.path ?? input.file_path ?? input.filePath ?? "")
    if (!raw) return

    const abs = path.resolve(process.cwd(), raw)
    const dir = path.dirname(abs)

    // 文件所属 git 仓库；不在任何仓库内则不打 checkpoint（不阻断写入）
    const top = await exec("git", ["-C", dir, "rev-parse", "--show-toplevel"])
    if (!top.ok || !top.stdout) return
    const repo = top.stdout

    const rel = path.relative(repo, abs).split(path.sep).join("/")
    const trackedRes = await exec("git", ["-C", repo, "ls-files", "--error-unmatch", rel])
    const tracked = trackedRes.ok

    // stash create：把当前工作区快照成一个悬挂 commit（工作区不动）；干净时输出为空 → 用 HEAD
    const stash = await exec("git", ["-C", repo, "stash", "create"])
    const ref = stash.ok && stash.stdout ? stash.stdout : "HEAD"

    stack.push({ repo, rel, abs, ref, tracked, at: new Date().toLocaleTimeString() })
    // 不返回任何值：checkpoint 只记录，不拦截（拦截是审批门的职责）
  })

  pi.registerCommand("rollback", {
    description: "回滚模型改过的文件到改动前的 checkpoint",
    handler: async (_args, ctx) => {
      if (!stack.length) {
        ctx.ui.notify("本会话还没有可回滚的改动", "info")
        return
      }
      const items = [...stack]
        .reverse()
        .map((c, i) => `${i + 1}. [${c.at}] ${c.rel}${c.tracked ? "" : "（新建文件，回滚即删除）"}`)
      const choice = await ctx.ui.select("回滚哪次改动？", items)
      if (!choice) return
      const idx = stack.length - 1 - (parseInt(choice, 10) - 1)
      const cp = stack[idx]
      if (!cp) return

      if (cp.tracked) {
        const r = await exec("git", ["-C", cp.repo, "checkout", cp.ref, "--", cp.rel])
        if (!r.ok) {
          ctx.ui.notify(`回滚失败：${r.err || r.stdout}`, "error")
          return
        }
        ctx.ui.notify(`已恢复 ${cp.rel} 到 ${cp.at} 的快照`, "info")
      } else {
        try {
          await unlink(cp.abs)
          ctx.ui.notify(`已删除新建文件 ${cp.rel}`, "info")
        } catch (e: any) {
          ctx.ui.notify(`删除失败：${e?.message ?? e}`, "error")
          return
        }
      }
      stack.splice(idx, 1)
    },
  })
}
