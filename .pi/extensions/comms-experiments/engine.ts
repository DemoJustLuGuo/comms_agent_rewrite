import { appendFileSync, copyFileSync, existsSync, linkSync, lstatSync, mkdirSync, readFileSync, realpathSync, renameSync, unlinkSync, writeFileSync } from "node:fs"
import { execFile } from "node:child_process"
import { promisify } from "node:util"
import { createHash, randomUUID } from "node:crypto"
import path from "node:path"
import { PROJECT_ROOT, resolvePython } from "../comms-tools/runner"
import { runExperimentCommand } from "./commands"

const executeFile = promisify(execFile)
export const EXPERIMENT_ROOT = path.join(PROJECT_ROOT, ".comms-experiments")

export interface ExperimentConfig {
  project: string
  goal: string
  allowedFiles: string[]
  metric: { name: string; unit: string; direction: "lower" | "higher" }
  checks: string[][]
  benchmark: string[]
  seed: number
  maxIterations: number
  timeoutSeconds: number
  rtol: number
  atol: number
}
export interface CommandRecord { argv: string[]; cwd: string; exitCode: number; log: string; elapsedMs: number }
export interface ExperimentRun {
  id: string
  kind: "baseline" | "candidate"
  status: "running" | "passed" | "failed" | "cancelled"
  startedAt: string
  endedAt?: string
  metric?: number
  vector?: number[]
  commands: CommandRecord[]
  hashes: Record<string, string>
  modifiedFiles: string[]
  reason?: string
  maxAbsoluteError?: number
}
export interface Experiment {
  version: 1
  id: string
  ownerSessionId: string
  config: ExperimentConfig
  baselineCommit: string
  baselineDirectory: string
  candidateDirectory: string
  originalHashes: Record<string, string>
  status: "ready" | "running" | "paused" | "completed" | "applied" | "applying"
  runs: ExperimentRun[]
  createdAt: string
  notes: string
  appliedRunId?: string
  pendingApply?: { runId: string; files: string[]; updatedFiles: string[] }
  recoveryIssue?: string
  stopRequested?: boolean
}

declare global { var __commsExperiments: Map<string, AbortController> | undefined }
const running = () => globalThis.__commsExperiments ??= new Map()
const hash = (content: Buffer | string) => createHash("sha256").update(content).digest("hex")
const fileHash = (filename: string) => hash(readFileSync(filename))

export function safeFile(root: string, relative: string): string {
  if (!relative || path.isAbsolute(relative) || relative.split(/[\\/]/).some((part) => part === ".." || part === ".git" || part.startsWith(".env"))) throw new Error("文件必须为项目内的明确相对路径。")
  const filename = path.resolve(root, relative)
  const canonicalRoot = realpathSync(root)
  const canonicalFile = existsSync(filename) ? realpathSync(filename) : path.join(realpathSync(path.dirname(filename)), path.basename(filename))
  if (!canonicalFile.startsWith(canonicalRoot + path.sep)) throw new Error("文件越过项目范围。")
  return filename
}

async function git(project: string, args: string[]) {
  return (await executeFile("git", ["-C", project, ...args], { timeout: 10000, maxBuffer: 2 * 1024 * 1024 })).stdout.trimEnd()
}

export class ExperimentEngine {
  constructor(readonly storageRoot = EXPERIMENT_ROOT) {}

  private directory(id: string) {
    if (!/^[a-f0-9-]{36}$/.test(id)) throw new Error("实验编号无效。")
    return path.join(this.storageRoot, id)
  }

  private save(experiment: Experiment, event: string, data: Record<string, unknown> = {}) {
    const directory = this.directory(experiment.id)
    const temporary = path.join(directory, `state-${randomUUID()}.tmp`)
    writeFileSync(temporary, JSON.stringify(experiment, null, 2))
    renameSync(temporary, path.join(directory, "state.json"))
    appendFileSync(path.join(directory, "events.jsonl"), JSON.stringify({ event, timestamp: new Date().toISOString(), ...data }) + "\n")
  }

  private recoverApply(experiment: Experiment) {
    if (!experiment.pendingApply) return
    const candidate = experiment.runs.find((run) => run.id === experiment.pendingApply!.runId)
    const baseline = experiment.runs.find((run) => run.kind === "baseline" && run.status === "passed")
    if (!candidate || !baseline) throw new Error("应用恢复记录缺少验证快照。")
    let conflict = false
    for (const filename of experiment.pendingApply.updatedFiles) {
      const target = safeFile(experiment.config.project, filename)
      const backup = `${target}.comms-${experiment.id}.original`
      const displaced = `${target}.comms-${experiment.id}.displaced`
      const temporary = `${target}.comms-${experiment.id}.tmp`
      if (existsSync(temporary) && fileHash(temporary) === candidate.hashes[filename]) unlinkSync(temporary)
      const original = safeFile(path.join(this.directory(experiment.id), baseline.id, "snapshot"), filename)
      if (fileHash(original) !== experiment.originalHashes[filename]) { conflict = true; continue }
      const currentHash = existsSync(target) ? fileHash(target) : undefined
      if (currentHash === experiment.originalHashes[filename]) {
        if (existsSync(backup) && fileHash(backup) === currentHash) unlinkSync(backup)
        continue
      }
      if (currentHash !== undefined && currentHash !== candidate.hashes[filename]) { conflict = true; continue }
      try {
        if (currentHash !== undefined) {
          if (existsSync(displaced)) throw new Error("恢复暂存文件已存在。")
          renameSync(target, displaced)
          if (fileHash(displaced) !== candidate.hashes[filename]) { if (!existsSync(target)) linkSync(displaced, target); conflict = true; continue }
        }
        if (!existsSync(backup)) copyFileSync(original, backup)
        if (fileHash(backup) !== experiment.originalHashes[filename]) throw new Error("捕获的原文件含外部修改。")
        linkSync(backup, target)
        unlinkSync(backup)
        if (existsSync(displaced) && fileHash(displaced) === candidate.hashes[filename]) unlinkSync(displaced)
      } catch { conflict = true }
    }
    experiment.status = "paused"
    experiment.recoveryIssue = conflict ? "应用中断且原文件被其它操作修改，请人工审阅暂存文件后恢复。" : "上次应用中断，已恢复原文件；请重新审阅候选。"
    if (!conflict) delete experiment.pendingApply
    this.save(experiment, "apply_recovered", { conflict })
  }

  read(id: string): Experiment {
    const experiment = JSON.parse(readFileSync(path.join(this.directory(id), "state.json"), "utf8")) as Experiment
    if (experiment.version !== 1 || experiment.id !== id) throw new Error("实验记录版本或编号不一致。")
    if (experiment.pendingApply && !experiment.recoveryIssue && !running().has(id)) {
      this.recoverApply(experiment)
    }
    if (experiment.status === "running" && !running().has(id)) {
      experiment.status = "paused"
      for (const run of experiment.runs.filter((run) => run.status === "running")) { run.status = "cancelled"; run.reason = "服务重启，上一轮没有完整验证证据。" }
      this.save(experiment, "interrupted")
    }
    return experiment
  }

  async start(config: ExperimentConfig, ownerSessionId: string): Promise<Experiment> {
    if (!config.goal.trim() || !config.allowedFiles.length || !Number.isInteger(config.seed) || !Number.isInteger(config.maxIterations) || config.maxIterations < 1 || config.maxIterations > 100) throw new Error("请提供目标、文件范围、整数随机种子和 1–100 轮预算。")
    if (!config.metric.name || !config.metric.unit || !["lower", "higher"].includes(config.metric.direction) || !Number.isFinite(config.rtol) || !Number.isFinite(config.atol) || config.rtol < 0 || config.atol < 0) throw new Error("指标单位、方向或数值容差无效。")
    if (!config.checks.length || !config.benchmark.length || [...config.checks, config.benchmark].some((argv) => !Array.isArray(argv) || !argv.length || argv.some((argument) => typeof argument !== "string" || argument.includes("\0")))) throw new Error("需要明确的验证与基准命令参数列表。")
    if (!Number.isFinite(config.timeoutSeconds) || config.timeoutSeconds < 1 || config.timeoutSeconds > 300) throw new Error("单命令超时范围为 1–300 秒。")
    const project = realpathSync(config.project)
    if (await git(project, ["rev-parse", "--show-toplevel"]) !== project) throw new Error("请选择 Git 仓库根目录。")
    const originalHashes: Record<string, string> = {}
    for (const filename of config.allowedFiles) {
      const target = safeFile(project, filename)
      if (lstatSync(target).isSymbolicLink() || !lstatSync(target).isFile()) throw new Error("实验目标必须为受版本控制的普通文件。")
      if (await git(project, ["status", "--porcelain", "--", filename])) throw new Error(`目标文件 ${filename} 已有修改，请先保存，或为实验选择其它文件。`)
      if (!(await git(project, ["ls-files", "--", filename]))) throw new Error(`实验目标 ${filename} 必须是已有的受版本控制文件。`)
      originalHashes[filename] = fileHash(target)
    }
    const id = randomUUID()
    const directory = this.directory(id)
    mkdirSync(directory, { recursive: true })
    const baselineCommit = await git(project, ["rev-parse", "HEAD"])
    const baselineDirectory = path.join(directory, "baseline")
    const candidateDirectory = path.join(directory, "candidate")
    await git(project, ["worktree", "add", "--detach", baselineDirectory, baselineCommit])
    await git(project, ["worktree", "add", "--detach", candidateDirectory, baselineCommit])
    const experiment: Experiment = { version: 1, id, ownerSessionId, config: { ...config, project }, baselineCommit, baselineDirectory, candidateDirectory, originalHashes, status: "ready", runs: [], createdAt: new Date().toISOString(), notes: "" }
    this.save(experiment, "created")
    return experiment
  }

  requireOwner(experiment: Experiment, ownerSessionId: string) {
    if (experiment.ownerSessionId !== ownerSessionId) throw new Error("该实验来自另一条会话；可以查看记录，请启动自己的实验后再修改。")
  }

  private args(argv: string[], directory: string, config: ExperimentConfig) {
    return argv.map((argument) => argument.replaceAll("{project}", directory).replaceAll("{python}", resolvePython()).replaceAll("{seed}", String(config.seed)))
  }

  preview(id: string) {
    const experiment = this.read(id)
    const directory = experiment.runs.some((run) => run.kind === "baseline" && run.status === "passed") ? experiment.candidateDirectory : experiment.baselineDirectory
    return { directory, commands: [...experiment.config.checks, experiment.config.benchmark].map((argv) => this.args(argv, directory, experiment.config)) }
  }

  async run(id: string, ownerSessionId: string, notify: (experiment: Experiment) => void = () => {}): Promise<Experiment> {
    const experiment = this.read(id)
    this.requireOwner(experiment, ownerSessionId)
    if (running().has(id) || experiment.pendingApply || experiment.stopRequested || ["applied", "completed"].includes(experiment.status)) throw new Error("实验正在运行、已停止、需要恢复，或已经结束。")
    const baseline = experiment.runs.find((run) => run.kind === "baseline" && run.status === "passed")
    const kind = baseline ? "candidate" : "baseline"
    if (kind === "candidate" && experiment.runs.filter((run) => run.kind === "candidate").length >= experiment.config.maxIterations) throw new Error("实验已达到最大候选轮数。")
    const directory = kind === "baseline" ? experiment.baselineDirectory : experiment.candidateDirectory
    const run: ExperimentRun = { id: randomUUID(), kind, status: "running", startedAt: new Date().toISOString(), commands: [], hashes: {}, modifiedFiles: [] }
    const controller = new AbortController()
    running().set(id, controller)
    experiment.status = "running"
    delete experiment.recoveryIssue
    experiment.runs.push(run)
    this.save(experiment, "run_started", { runId: run.id })
    notify(experiment)
    try {
      if (await git(directory, ["rev-parse", "HEAD"]) !== experiment.baselineCommit || await git(directory, ["rev-parse", "--show-toplevel"]) !== directory) throw new Error("工作区版本或路径与基线记录不一致。")
      const modified = (await git(directory, ["status", "--porcelain", "--untracked-files=all"]))
        .split("\n").filter(Boolean).map((line) => line.slice(3).replace(/^"|"$/g, ""))
      run.modifiedFiles = modified
      if (kind === "baseline" && modified.length) throw new Error("基线工作区已被修改。")
      if (modified.some((filename) => !experiment.config.allowedFiles.includes(filename))) throw new Error("候选工作区存在范围之外的改动。")
      for (const filename of experiment.config.allowedFiles) {
        run.hashes[filename] = fileHash(safeFile(directory, filename))
        if (kind === "baseline" && run.hashes[filename] !== experiment.originalHashes[filename]) throw new Error("基线文件与创建时记录不一致。")
      }
      const commands = [...experiment.config.checks, experiment.config.benchmark]
      let resultText = ""
      for (const [position, command] of commands.entries()) {
        const argv = this.args(command, directory, experiment.config)
        const started = performance.now()
        const log = path.join(this.directory(id), `${run.id}-${position}.log`)
        const { stdout, stderr, exitCode } = await runExperimentCommand(argv, directory, experiment.config.seed, experiment.config.timeoutSeconds, controller.signal)
        writeFileSync(log, stdout + "\n" + stderr)
        run.commands.push({ argv, cwd: directory, exitCode, log, elapsedMs: performance.now() - started })
        this.save(experiment, "command_finished", { runId: run.id, position, exitCode })
        notify(experiment)
        if (exitCode !== 0) throw new Error(`验证命令 ${position + 1} 失败，退出码 ${exitCode}。`)
        if (position === commands.length - 1) resultText = stdout
      }
      if (controller.signal.aborted) throw new Error("实验已停止。")
      const after = (await git(directory, ["status", "--porcelain", "--untracked-files=all"]))
        .split("\n").filter(Boolean).map((line) => line.slice(3).replace(/^"|"$/g, ""))
      if (after.some((filename) => !experiment.config.allowedFiles.includes(filename))) throw new Error("验证命令产生了范围之外的改动。")
      if (await git(directory, ["rev-parse", "HEAD"]) !== experiment.baselineCommit) throw new Error("验证命令修改了工作区版本。")
      for (const filename of experiment.config.allowedFiles) if (run.hashes[filename] !== fileHash(safeFile(directory, filename))) throw new Error("验证期间文件内容发生变化，不能使用本轮证据。")
      const marker = resultText.split("\n").findLast((line) => line.startsWith("COMMS_EXPERIMENT_RESULT="))
      if (!marker) throw new Error("基准命令没有输出结构化指标与数值向量。")
      const measurement = JSON.parse(marker.slice("COMMS_EXPERIMENT_RESULT=".length))
      if (measurement.metric?.name !== experiment.config.metric.name || measurement.metric?.unit !== experiment.config.metric.unit || !Number.isFinite(measurement.metric?.value) || measurement.seed !== experiment.config.seed || !Array.isArray(measurement.vector) || !measurement.vector.length || measurement.vector.length > 100000 || !measurement.vector.every(Number.isFinite)) throw new Error("指标名称、单位、种子或数值向量与实验配置不一致。")
      run.metric = measurement.metric.value
      run.vector = measurement.vector
      if (baseline) {
        if (baseline.vector!.length !== run.vector!.length) throw new Error("候选数值向量长度与基线不一致。")
        const differences = run.vector!.map((value, position) => Math.abs(value - baseline.vector![position]))
        run.maxAbsoluteError = differences.reduce((maximum, difference) => Math.max(maximum, difference), 0)
        if (differences.some((difference, position) => difference > experiment.config.atol + experiment.config.rtol * Math.abs(baseline.vector![position]))) throw new Error("候选未通过数值等价校验。")
      }
      const snapshot = path.join(this.directory(id), run.id, "snapshot")
      for (const filename of experiment.config.allowedFiles) { const destination = path.join(snapshot, filename); mkdirSync(path.dirname(destination), { recursive: true }); copyFileSync(safeFile(directory, filename), destination); if (fileHash(destination) !== run.hashes[filename]) throw new Error("快照与已验证文件不一致。") }
      run.status = "passed"
    } catch (error) { run.status = controller.signal.aborted ? "cancelled" : "failed"; run.reason = error instanceof Error ? error.message : String(error) }
    finally {
      running().delete(id)
      run.endedAt = new Date().toISOString()
      experiment.status = "paused"
      experiment.stopRequested = controller.signal.aborted
      this.save(experiment, "run_finished", { runId: run.id, status: run.status })
      notify(experiment)
    }
    return experiment
  }

  stop(id: string, ownerSessionId: string) {
    const experiment = this.read(id)
    this.requireOwner(experiment, ownerSessionId)
    if (experiment.status === "applying") throw new Error("候选应用中，请等待写入或恢复结束。")
    experiment.stopRequested = true
    this.save(experiment, "stop_requested")
    running().get(id)?.abort()
    return experiment
  }

  resume(id: string, ownerSessionId: string) {
    const experiment = this.read(id)
    this.requireOwner(experiment, ownerSessionId)
    if (running().has(id) || experiment.pendingApply || experiment.status === "applied") throw new Error("实验仍在运行、需要恢复或已经应用。")
    experiment.stopRequested = false
    this.save(experiment, "resumed")
    return experiment
  }

  recover(id: string, ownerSessionId: string) {
    const experiment = this.read(id)
    this.requireOwner(experiment, ownerSessionId)
    if (running().has(id)) throw new Error("请等待运行结束后重新检查恢复。")
    this.recoverApply(experiment)
    return experiment
  }

  note(id: string, ownerSessionId: string, notes: string) { const experiment = this.read(id); this.requireOwner(experiment, ownerSessionId); if (running().has(id)) throw new Error("请在本轮结束后更新实验说明。"); experiment.notes = notes.slice(0, 8000); this.save(experiment, "notes_updated"); return experiment }

  async diff(id: string, runId: string): Promise<string> {
    const experiment = this.read(id)
    const run = experiment.runs.find((run) => run.id === runId)
    if (!run || run.status !== "passed") throw new Error("该轮没有可审阅的验证快照。")
    const snapshot = path.join(this.directory(id), run.id, "snapshot")
    const baseline = experiment.runs.find((run) => run.kind === "baseline" && run.status === "passed")!
    const baselineSnapshot = path.join(this.directory(id), baseline.id, "snapshot")
    const diffs: string[] = []
    for (const filename of experiment.config.allowedFiles) {
      try { diffs.push((await executeFile("git", ["diff", "--no-index", "--", safeFile(baselineSnapshot, filename), safeFile(snapshot, filename)], { maxBuffer: 2 * 1024 * 1024 })).stdout) }
      catch (error: any) { if (error.code !== 1) throw error; diffs.push(error.stdout) }
    }
    return diffs.join("\n")
  }

  async apply(id: string, runId: string, ownerSessionId: string): Promise<Experiment> {
    const experiment = this.read(id)
    this.requireOwner(experiment, ownerSessionId)
    if (running().has(id) || experiment.status === "applied" || experiment.pendingApply) throw new Error("实验正在运行、候选已经应用，或上次应用仍需恢复。")
    const run = experiment.runs.find((run) => run.id === runId)
    if (!run || run.kind !== "candidate" || run.status !== "passed") throw new Error("只能应用已通过验证的候选快照。")
    running().set(id, new AbortController())
    try {
    if (await git(experiment.config.project, ["rev-parse", "HEAD"]) !== experiment.baselineCommit) throw new Error("原项目版本已经变化，请重新建立实验。")
    const snapshot = path.join(this.directory(id), run.id, "snapshot")
    const changed = experiment.config.allowedFiles.filter((filename) => run.hashes[filename] !== experiment.originalHashes[filename])
    const baseline = experiment.runs.find((run) => run.kind === "baseline" && run.status === "passed")!
    const originalSnapshot = path.join(this.directory(id), baseline.id, "snapshot")
    for (const filename of changed) {
      if (fileHash(safeFile(experiment.config.project, filename)) !== experiment.originalHashes[filename] || await git(experiment.config.project, ["status", "--porcelain", "--", filename])) throw new Error(`原项目的 ${filename} 已有改动，请重新审阅。`)
      if (fileHash(safeFile(snapshot, filename)) !== run.hashes[filename]) throw new Error("验证快照被修改，拒绝应用。")
      if (fileHash(safeFile(originalSnapshot, filename)) !== experiment.originalHashes[filename]) throw new Error("原始快照被修改，拒绝应用。")
    }
    experiment.status = "applying"
    delete experiment.recoveryIssue
    experiment.pendingApply = { runId, files: changed, updatedFiles: [] }
    this.save(experiment, "apply_started", { runId, files: changed })
    try {
      for (const filename of changed) {
        const target = safeFile(experiment.config.project, filename)
        const temporary = `${target}.comms-${id}.tmp`
        const backup = `${target}.comms-${id}.original`
        if (existsSync(temporary) || existsSync(backup)) throw new Error("上次应用的暂存文件尚未处理。")
        copyFileSync(safeFile(snapshot, filename), temporary)
        experiment.pendingApply.updatedFiles.push(filename)
        this.save(experiment, "apply_file_started", { runId, filename })
        renameSync(target, backup)
        if (fileHash(backup) !== experiment.originalHashes[filename]) {
          if (!existsSync(target)) linkSync(backup, target)
          throw new Error("应用时检测到原文件被外部修改。")
        }
        linkSync(temporary, target)
        unlinkSync(temporary)
      }
    } catch (error) {
      this.recoverApply(experiment)
      throw error
    }
    experiment.status = "applied"; experiment.appliedRunId = runId
    delete experiment.pendingApply
    this.save(experiment, "applied", { runId })
    for (const filename of changed) {
      const backup = `${safeFile(experiment.config.project, filename)}.comms-${id}.original`
      if (existsSync(backup) && fileHash(backup) === experiment.originalHashes[filename]) unlinkSync(backup)
    }
    return experiment
    } finally { running().delete(id) }
  }
}

export function experimentIdFor(manager: { getBranch(): any[] }): string | undefined {
  return manager.getBranch().findLast((entry) => entry.type === "custom" && entry.customType === "comms-experiment")?.data?.id
}
