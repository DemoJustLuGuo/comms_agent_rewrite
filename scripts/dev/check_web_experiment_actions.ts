import assert from "node:assert/strict"
import { mkdtempSync, writeFileSync, rmSync } from "node:fs"
import { execFileSync } from "node:child_process"
import { tmpdir } from "node:os"
import path from "node:path"
import { SessionManager } from "@earendil-works/pi-coding-agent"
import { AgentSessionWrapper } from "../../vendor/pi-web/lib/rpc-manager"
import { ExperimentEngine } from "../../.pi/extensions/comms-experiments/engine"

const directory = mkdtempSync(path.join(tmpdir(), "comms-web-actions-"))
const manager = SessionManager.inMemory(directory)
const git = (args: string[]) => execFileSync("git", ["-C", directory, ...args], { encoding: "utf8" })
git(["init", "-q"]); git(["config", "user.name", "Web fixture"]); git(["config", "user.email", "fixture@example.invalid"])
writeFileSync(path.join(directory, "vector.json"), "[1,2]")
git(["add", "vector.json"]); git(["commit", "-qm", "baseline"])
const engine = new ExperimentEngine()
const experiment = await engine.start({ project: directory, goal: "Web 审批测试", allowedFiles: ["vector.json"], metric: { name: "metric", unit: "ms", direction: "lower" }, checks: [[process.execPath, "-e", "process.exit(0)"]], benchmark: [process.execPath, "-e", "process.exit(0)"], seed: 42, maxIterations: 1, timeoutSeconds: 10, rtol: 1e-6, atol: 1e-9 }, manager.getSessionId())
manager.appendCustomEntry("comms-experiment", { id: experiment.id })
let promptCalls = 0
const wrapper = new AgentSessionWrapper({
  sessionId: manager.getSessionId(), sessionManager: manager, isStreaming: false, isCompacting: false,
  extensionRunner: { setUIContext() {} }, agent: { state: {} }, getAllTools: () => [],
  prompt: async () => { promptCalls += 1 }, abort: async () => {},
} as any)
const events: any[] = []
wrapper.onEvent((event) => events.push(event))
try {
  const applying = wrapper.send({ type: "experiment_apply", runId: "invalid" }).catch((error) => error as Error)
  await new Promise((resolve) => setTimeout(resolve, 20))
  const firstRequest = events.find((event) => event.type === "extension_ui_request")
  assert(firstRequest)
  assert.equal(wrapper.isRunning(), true)
  await assert.rejects(wrapper.send({ type: "experiment_apply", runId: "invalid" }), /等待/)
  await assert.rejects(wrapper.send({ type: "prompt", message: "new prompt" }), /实验操作/)
  await wrapper.send({ type: "experiment_stop" })
  assert.match((await applying).message, /取消/)
  assert(events.some((event) => event.type === "extension_ui_dismiss" && event.id === firstRequest.id))
  assert.equal(wrapper.isRunning(), false)
  await wrapper.send({ type: "extension_ui_response", id: firstRequest.id, confirmed: true })
  assert.equal(promptCalls, 0)
  console.log("PASS: pending experiment approval locks session, duplicate start rejected, stop cancels approval, stale approval cannot execute")
} finally {
  wrapper.destroy()
  git(["worktree", "remove", "--force", experiment.baselineDirectory])
  git(["worktree", "remove", "--force", experiment.candidateDirectory])
  rmSync(path.join(engine.storageRoot, experiment.id), { recursive: true, force: true })
  rmSync(directory, { recursive: true, force: true })
}
