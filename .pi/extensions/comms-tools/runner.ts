/**
 * comms 域工具公共 runner：spawn Python 计算核（tools/*.py）并回传文本结果。
 *
 * 这是 opencode 时代 15 份复制粘贴 TS 桥的收敛点——spawn/超时/编码/错误包装只写这一次，
 * 各工具以声明式 spec 注册（见 index.ts）。
 *
 * 约定（与 Python 计算核保持一致，勿破坏）：
 * - 小参数经 argv[1] 传 JSON；大数组（信号采样）经 stdin 传 JSON（Windows 命令行 32767 字符上限）。
 * - 成功：退出码 0，stdout 即给模型看的报告（含「错误：」开头的域校验失败，同样退出码 0）。
 * - 结构性错误（非法 JSON/缺字段）：非零退出码，由本 runner 包装成【失败】文本。
 */
import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import path from "node:path"
import { fileURLToPath } from "node:url"

const HERE = path.dirname(fileURLToPath(import.meta.url))
// .pi/extensions/comms-tools/ → 项目根
export const PROJECT_ROOT = path.resolve(HERE, "..", "..", "..")
export const TOOLS_DIR = path.join(PROJECT_ROOT, "tools")

/** Python 解释器：PYTHON_BIN 显式覆盖 → 项目 uv 虚拟环境 → PATH 上的 python。 */
export function resolvePython(): string {
  if (process.env.PYTHON_BIN) return process.env.PYTHON_BIN
  const candidates = [
    path.join(PROJECT_ROOT, ".venv", "Scripts", "python.exe"), // Windows venv
    path.join(PROJECT_ROOT, ".venv", "bin", "python"), // POSIX venv
  ]
  for (const c of candidates) if (existsSync(c)) return c
  return "python"
}

export interface PyToolSpec {
  /** tools/ 下的脚本文件名（不含路径） */
  script: string
  /** 参数走 stdin（大数组）还是 argv（默认） */
  stdinJson?: boolean
  /** 子进程超时毫秒，默认 30s */
  timeoutMs?: number
  /** 失败时给模型的排障提示 */
  failureHint: string
  structured?: boolean
}

export interface PyToolResult {
  content: Array<{ type: "text"; text: string }>
  details: Record<string, unknown>
}

function failureText(toolName: string, reason: string, hint: string): string {
  return [`【失败】${toolName} 调用失败`, `原因：${reason}`, `解决方案：${hint}`].join("\n")
}

export function runPyTool(
  toolName: string,
  spec: PyToolSpec,
  params: unknown,
  signal?: AbortSignal,
): Promise<PyToolResult> {
  const script = path.join(TOOLS_DIR, spec.script)
  const timeoutMs = spec.timeoutMs ?? 30_000
  const payload = JSON.stringify({ ...(params as Record<string, unknown> ?? {}), ...(spec.structured ? { __comms_structured: true } : {}) })
  const argv = ["-X", "utf8", script, ...(spec.stdinJson ? [] : [payload])]

  return new Promise((resolve) => {
    const done = (text: string) => {
      const marker = spec.structured ? text.lastIndexOf("COMMS_RESULT_JSON=") : -1
      let data: Record<string, unknown> | undefined
      if (marker >= 0) {
        try { data = JSON.parse(text.slice(marker + "COMMS_RESULT_JSON=".length)) } catch { return resolve({ content: [{ type: "text", text: failureText(toolName, "结构化结果不可解析", spec.failureHint) }], details: { ok: false } }) }
      }
      const report = marker >= 0 ? text.slice(0, marker).trim() : text
      resolve({ content: [{ type: "text", text: report }], details: { ok: !/^(?:【失败】|错误[：:])/mu.test(report), ...(data ?? {}) } })
    }
    const fail = (reason: string) => done(failureText(toolName, reason, spec.failureHint))

    let child: ReturnType<typeof spawn>
    try {
      child = spawn(resolvePython(), argv, {
        // 固定项目根为子进程 cwd：pi-web 拉起的 pi 进程 cwd 是 pi-web 包目录
        // （曾把 plots/ 产物写进 node_modules），TUI 下也恒等于项目根，行为一致。
        cwd: PROJECT_ROOT,
        stdio: ["pipe", "pipe", "pipe"],
        windowsHide: true,
      })
    } catch (e: any) {
      fail(String(e?.message || e))
      return
    }

    let out = ""
    let err = ""
    let timedOut = false
    let settled = false

    const timer = setTimeout(() => {
      timedOut = true
      child.kill()
    }, timeoutMs)

    const onAbort = () => child.kill()
    signal?.addEventListener("abort", onAbort, { once: true })

    child.stdout!.setEncoding("utf8").on("data", (d: string) => (out += d))
    child.stderr!.setEncoding("utf8").on("data", (d: string) => (err += d))

    child.on("error", (e) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      fail(`无法启动 Python 子进程：${e.message}`)
    })

    child.on("close", (code) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      signal?.removeEventListener("abort", onAbort)
      if (signal?.aborted) return fail("已被会话中断（abort）。")
      if (timedOut) return fail(`Python 计算超过 ${timeoutMs / 1000} 秒未返回，已强制终止。`)
      if (code !== 0) return fail((err || out || `exit code ${code}`).trim())
      done(out.trim())
    })

    if (spec.stdinJson) child.stdin!.end(payload)
    else child.stdin!.end()
  })
}
