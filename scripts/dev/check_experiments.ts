import assert from "node:assert/strict"
import { execFileSync } from "node:child_process"
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { ExperimentEngine, type ExperimentConfig } from "../../.pi/extensions/comms-experiments/engine"
import experimentExtension from "../../.pi/extensions/comms-experiments/index"
import { runExperimentCommand } from "../../.pi/extensions/comms-experiments/commands"

const workspace = mkdtempSync(path.join(tmpdir(), "comms-experiment-tests-"))
const project = path.join(workspace, "project")
mkdirSync(project)
const git = (args: string[]) => execFileSync("git", ["-C", project, ...args], { encoding: "utf8" }).trim()
git(["init", "-q"])
git(["config", "user.name", "Experiment fixture"])
git(["config", "user.email", "fixture@example.invalid"])
writeFileSync(path.join(project, "vector.json"), "[1,2]")
git(["add", "vector.json"])
git(["commit", "-qm", "fixture baseline"])
writeFileSync(path.join(project, "user-note.txt"), "user data")
const command = [process.execPath, "-e", 'const vector=JSON.parse(require("fs").readFileSync("vector.json","utf8")); console.log("COMMS_EXPERIMENT_RESULT="+JSON.stringify({metric:{name:"latency",unit:"ms",value:1},vector,seed:42}));']
const config: ExperimentConfig = { project, goal: "验证数值等价与原文件保护", allowedFiles: ["vector.json"], metric: { name: "latency", unit: "ms", direction: "lower" }, checks: [[process.execPath, "-e", "process.exit(0)"]], benchmark: command, seed: 42, maxIterations: 4, timeoutSeconds: 10, rtol: 1e-6, atol: 1e-9 }
const engine = new ExperimentEngine(path.join(workspace, "records"))
try {
  const controller = new AbortController()
  const commandStopped = runExperimentCommand([process.execPath, "-e", "setTimeout(()=>{},30000)"], project, 42, 60, controller.signal)
  setTimeout(() => controller.abort(), 30)
  assert.equal((await commandStopped).exitCode, -1)
  const nonexistent = await runExperimentCommand([path.join(workspace, "missing-command")], project, 42, 1, new AbortController().signal)
  assert.equal(nonexistent.exitCode, -1)
  const experiment = await engine.start(config, "owner")
  const baseline = await engine.run(experiment.id, "owner")
  assert.equal(baseline.runs[0].status, "passed")
  assert.equal(baseline.runs[0].commands[0].cwd, experiment.baselineDirectory)
  engine.stop(experiment.id, "owner")
  assert.equal(engine.read(experiment.id).stopRequested, true)
  await assert.rejects(engine.run(experiment.id, "owner"), /已停止/)
  engine.resume(experiment.id, "owner")
  assert.equal(engine.read(experiment.id).stopRequested, false)
  writeFileSync(path.join(experiment.candidateDirectory, "vector.json"), "[1,3]")
  const failed = await engine.run(experiment.id, "owner")
  assert.equal(failed.runs.at(-1)!.status, "failed")
  assert.match(failed.runs.at(-1)!.reason!, /等价/)
  await assert.rejects(engine.apply(experiment.id, failed.runs.at(-1)!.id, "owner"), /只能应用/)
  writeFileSync(path.join(experiment.candidateDirectory, "vector.json"), "[1,2]\n")
  const candidate = await engine.run(experiment.id, "owner")
  assert.equal(candidate.runs.at(-1)!.status, "passed")
  assert.equal(new ExperimentEngine(engine.storageRoot).read(experiment.id).runs.length, 3)
  assert((await engine.diff(experiment.id, candidate.runs.at(-1)!.id)).includes("vector.json"))
  await assert.rejects(engine.run(experiment.id, "another-session"), /另一条会话/)
  writeFileSync(path.join(project, "vector.json"), "user changed it")
  await assert.rejects(engine.apply(experiment.id, candidate.runs.at(-1)!.id, "owner"), /已有改动/)
  writeFileSync(path.join(project, "vector.json"), "[1,2]")
  const applied = await engine.apply(experiment.id, candidate.runs.at(-1)!.id, "owner")
  assert.equal(applied.status, "applied")
  assert.equal(readFileSync(path.join(project, "vector.json"), "utf8"), "[1,2]\n")
  assert.equal(readFileSync(path.join(project, "user-note.txt"), "utf8"), "user data")
  const interrupted = engine.read(experiment.id)
  interrupted.status = "applying"
  interrupted.pendingApply = { runId: candidate.runs.at(-1)!.id, files: ["vector.json"], updatedFiles: ["vector.json"] }
  writeFileSync(path.join(engine.storageRoot, experiment.id, "state.json"), JSON.stringify(interrupted))
  const recovered = new ExperimentEngine(engine.storageRoot).read(experiment.id)
  assert.equal(recovered.status, "paused")
  assert.equal(readFileSync(path.join(project, "vector.json"), "utf8"), "[1,2]")
  const handlers = new Map<string, (...args: any[]) => any>()
  experimentExtension({ registerTool() {}, on(name: string, handler: (...args: any[]) => any) { handlers.set(name, handler) } } as any, engine)
  const ctx = { cwd: project, sessionManager: { getBranch: () => [{ type: "custom", customType: "comms-experiment", data: { id: experiment.id } }], getSessionId: () => "owner" } }
  assert.equal(handlers.get("tool_call")!({ toolName: "edit", input: { path: path.join(project, "vector.json") } }, ctx).block, true)
  assert.equal(handlers.get("tool_call")!({ toolName: "edit", input: { path: path.join(experiment.candidateDirectory, "vector.json") } }, ctx), undefined)
  assert.equal(handlers.get("tool_call")!({ toolName: "bash", input: { command: "anything" } }, ctx).block, true)
  const originalSave = (engine as any).save.bind(engine)
  const instrumented = engine as any
  instrumented.save = (state: unknown, event: string, data: unknown) => {
    originalSave(state, event, data)
    if (event === "apply_file_started") writeFileSync(path.join(project, "vector.json"), "external edit during apply")
  }
  await assert.rejects(engine.apply(experiment.id, candidate.runs.at(-1)!.id, "owner"), /外部修改/)
  assert.equal(readFileSync(path.join(project, "vector.json"), "utf8"), "external edit during apply")
  writeFileSync(path.join(project, "vector.json"), "[1,2]")
  assert.equal(engine.recover(experiment.id, "owner").pendingApply, undefined)
  console.log("PASS: baseline, numerical failure, candidate snapshot, resume, owner isolation, original edit conflict, apply, interrupted apply recovery, concurrent editor protection, tool scope and user data protection")
} finally { rmSync(workspace, { recursive: true, force: true }) }
