import { spawn } from "node:child_process"

export function runExperimentCommand(argv: string[], cwd: string, seed: number, timeoutSeconds: number, signal: AbortSignal): Promise<{ stdout: string; stderr: string; exitCode: number }> {
  return new Promise((resolve) => {
    if (signal.aborted) { resolve({ stdout: "", stderr: "实验已停止。", exitCode: -1 }); return }
    const grouped = process.platform !== "win32"
    const child = spawn(argv[0], argv.slice(1), { cwd, detached: grouped, stdio: ["ignore", "pipe", "pipe"], env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1", COMMS_EXPERIMENT_SEED: String(seed) } })
    let stdout = "", stderr = "", reason = "", finished = false
    const terminate = (message: string) => {
      if (reason) return
      reason = message
      const kill = (kind: NodeJS.Signals) => {
        try { if (grouped && child.pid) process.kill(-child.pid, kind); else child.kill(kind) } catch {}
      }
      kill("SIGTERM")
      const escalation = setTimeout(() => kill("SIGKILL"), 500)
      escalation.unref()
    }
    const abort = () => terminate("实验已停止。")
    signal.addEventListener("abort", abort, { once: true })
    const timeout = setTimeout(() => terminate(`验证命令超过 ${timeoutSeconds} 秒。`), timeoutSeconds * 1000)
    const finish = (exitCode: number, error?: string) => {
      if (finished) return
      finished = true
      clearTimeout(timeout)
      signal.removeEventListener("abort", abort)
      resolve({ stdout, stderr: [stderr, reason, error].filter(Boolean).join("\n"), exitCode: reason ? -1 : exitCode })
    }
    child.stdout.setEncoding("utf8").on("data", (chunk: string) => {
      if (stdout.length + stderr.length + chunk.length > 8 * 1024 * 1024) terminate("验证输出超过 8 MiB 上限。")
      else stdout += chunk
    })
    child.stderr.setEncoding("utf8").on("data", (chunk: string) => {
      if (stdout.length + stderr.length + chunk.length > 8 * 1024 * 1024) terminate("验证输出超过 8 MiB 上限。")
      else stderr += chunk
    })
    child.on("error", (error) => finish(-1, error.message))
    child.on("close", (code) => finish(code ?? -1))
  })
}
