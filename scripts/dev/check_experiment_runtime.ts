import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { createAgentSession, DefaultResourceLoader, SessionManager, SettingsManager, AuthStorage } from "@earendil-works/pi-coding-agent"
import commsTools from "../../.pi/extensions/comms-tools/index"
import approvalGate from "../../.pi/extensions/approval-gate"
import experimentTools from "../../.pi/extensions/comms-experiments/index"
import { ExperimentEngine } from "../../.pi/extensions/comms-experiments/engine"

const workspace = mkdtempSync(path.join(tmpdir(), "comms-experiment-runtime-"))
const project = path.join(workspace, "project")
mkdirSync(project)
const git = (args: string[]) => execFileSync("git", ["-C", project, ...args], { encoding: "utf8" }).trim()
git(["init", "-q"]); git(["config", "user.name", "Runtime fixture"]); git(["config", "user.email", "fixture@example.invalid"])
writeFileSync(path.join(project, "vector.json"), "[1,2]")
git(["add", "vector.json"]); git(["commit", "-qm", "baseline"])
const sessionManager = SessionManager.inMemory(workspace)
const engine = new ExperimentEngine()
const experiment = await engine.start({ project, goal: "模型工具链验收", allowedFiles: ["vector.json"], metric: { name: "latency", unit: "ms", direction: "lower" }, checks: [[process.execPath, "-e", "process.exit(0)"]], benchmark: [process.execPath, "-e", 'console.log("COMMS_EXPERIMENT_RESULT="+JSON.stringify({metric:{name:"latency",unit:"ms",value:1},vector:JSON.parse(require("fs").readFileSync("vector.json","utf8")),seed:42}));'], seed: 42, maxIterations: 1, timeoutSeconds: 10, rtol: 1e-6, atol: 1e-9 }, sessionManager.getSessionId())
await engine.run(experiment.id, sessionManager.getSessionId())
sessionManager.appendCustomEntry("comms-experiment", { id: experiment.id })
const payloads: any[] = []
const calls = [
  { name: "write", input: { path: path.join(project, "vector.json"), content: "intrusion" } },
  { name: "write", input: { path: path.join(experiment.candidateDirectory, "vector.json"), content: "[1,2]\n" } },
  { name: "experiment_run", input: {} },
  { name: "experiment_run", input: {} },
]
const server = Bun.serve({ port: 0, hostname: "127.0.0.1", async fetch(request) {
  payloads.push(await request.json())
  const call = calls[payloads.length - 1]
  const delta = call ? { role: "assistant", tool_calls: [{ index: 0, id: `call-${payloads.length}`, type: "function", function: { name: call.name, arguments: JSON.stringify(call.input) } }] } : { role: "assistant", content: "预算已到，候选通过，等待审阅。" }
  return new Response(`data: ${JSON.stringify({ id: "fixture", object: "chat.completion.chunk", choices: [{ index: 0, delta, finish_reason: call ? "tool_calls" : "stop" }] })}\n\ndata: [DONE]\n\n`, { headers: { "Content-Type": "text/event-stream" } })
} })
let dispose: (() => void) | undefined
try {
  const settingsManager = SettingsManager.inMemory({ defaultProjectTrust: "always" })
  const resourceLoader = new DefaultResourceLoader({ cwd: workspace, agentDir: workspace, settingsManager, noExtensions: true, noSkills: true, noPromptTemplates: true, noContextFiles: true, extensionFactories: [commsTools, approvalGate, experimentTools] })
  await resourceLoader.reload()
  const authStorage = AuthStorage.inMemory(); authStorage.setRuntimeApiKey("fixture", "fixture")
  const { session } = await createAgentSession({ cwd: workspace, agentDir: workspace, settingsManager, resourceLoader, authStorage, sessionManager, model: { id: "fixture", name: "fixture", api: "openai-completions", provider: "fixture", baseUrl: `http://127.0.0.1:${server.port}/v1`, reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 10000, maxTokens: 1000 } })
  dispose = () => session.dispose()
  await session.bindExtensions({ mode: "rpc", uiContext: { confirm: async () => true } as any })
  await session.prompt("/comms-tools default")
  await session.prompt("执行候选修改与验证，到预算后结束。")
  assert.equal(readFileSync(path.join(project, "vector.json"), "utf8"), "[1,2]")
  const results = session.messages.filter((message) => message.role === "toolResult") as any[]
  assert.equal(results[0].isError, true)
  assert.equal(results[1].isError, false)
  assert.equal(results[2].isError, false)
  assert.equal(results[3].isError, true)
  assert(results[3].content.some((block: any) => block.text?.includes("最大候选轮数")))
  assert.equal(engine.read(experiment.id).runs.filter((run) => run.kind === "candidate").length, 1)
  assert(payloads.every((payload) => !payload.tools.some((tool: any) => ["bash", "equivalence_check"].includes(tool.function.name))))
  console.log("PASS: provider → scoped candidate write → approved fixed commands → verified result → hard iteration budget → original unchanged")
} finally {
  dispose?.(); server.stop(true)
  execFileSync("git", ["-C", project, "worktree", "remove", "--force", experiment.baselineDirectory])
  execFileSync("git", ["-C", project, "worktree", "remove", "--force", experiment.candidateDirectory])
  rmSync(path.join(engine.storageRoot, experiment.id), { recursive: true, force: true })
  rmSync(workspace, { recursive: true, force: true })
}
