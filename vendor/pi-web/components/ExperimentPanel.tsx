"use client";

import { useState } from "react";
import type { ExperimentView } from "@/lib/experiment-types";

const buttonClass = "rounded border border-border px-3 py-1.5 text-sm text-text disabled:opacity-40";
const inputClass = "w-full rounded border border-border bg-bg px-3 py-2 text-sm text-text";
const statuses = { ready: "待测基线", running: "验证中", paused: "等待下一轮", completed: "已结束", applied: "候选已应用", applying: "正在应用候选" };

export function ExperimentPanel({ experiment, busy, error, cwd, sessionId, onAction, onOptimize, onOpenFile }: {
  experiment: ExperimentView | null;
  busy: boolean;
  error: string | null;
  cwd: string;
  sessionId?: string;
  onAction: (command: Record<string, unknown>) => Promise<unknown>;
  onOptimize: (message: string) => void;
  onOpenFile?: (filename: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const [editing, setEditing] = useState(false);
  const [diff, setDiff] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [project, setProject] = useState(`${cwd.replace(/[\\/]$/, "")}/real_projects/ModulationPy`);
  const [goal, setGoal] = useState("优化调制解调耗时，保持数值行为等价");
  const [files, setFiles] = useState("ModulationPy/ModulationPy.py,tests.py");
  const [maxIterations, setMaxIterations] = useState(3);
  const [seed, setSeed] = useState(42);
  const [checks, setChecks] = useState(JSON.stringify([["bash", `${cwd.replace(/[\\/]$/, "")}/scripts/check-real-project.sh`, "--project", "{project}"]]));
  const [benchmark, setBenchmark] = useState(JSON.stringify(["{python}", `${cwd.replace(/[\\/]$/, "")}/scripts/benchmark-modulation.py`, "--project", "{project}", "--seed", "{seed}"]));
  const [metricName, setMetricName] = useState("roundtrip_ms");
  const [unit, setUnit] = useState("ms");
  const [direction, setDirection] = useState<"lower" | "higher">("lower");
  const baseline = experiment?.runs.find((run) => run.kind === "baseline" && run.status === "passed");
  const owned = !experiment || experiment.ownerSessionId === sessionId;
  const candidates = experiment?.runs.filter((run) => run.kind === "candidate") ?? [];
  const last = experiment?.runs.at(-1);
  const best = candidates.filter((run) => run.status === "passed" && run.metric !== undefined).sort((first, second) => experiment?.config.metric.direction === "higher" ? second.metric! - first.metric! : first.metric! - second.metric!)[0];

  const startNew = () => {
    if (experiment) {
      setProject(experiment.config.project); setGoal(experiment.config.goal); setFiles(experiment.config.allowedFiles.join(","));
      setChecks(JSON.stringify(experiment.config.checks)); setBenchmark(JSON.stringify(experiment.config.benchmark));
      setSeed(experiment.config.seed); setMaxIterations(experiment.config.maxIterations);
      setMetricName(experiment.config.metric.name); setUnit(experiment.config.metric.unit); setDirection(experiment.config.metric.direction);
    }
    setEditing(true);
  };

  const create = async () => {
    try {
      setFormError(null);
      setEditing(false);
      const result = await onAction({ type: "experiment_start", config: { project, goal, allowedFiles: files.split(",").map((filename) => filename.trim()).filter(Boolean), metric: { name: metricName, unit, direction }, checks: JSON.parse(checks), benchmark: JSON.parse(benchmark), seed, maxIterations, timeoutSeconds: 180, rtol: 1e-6, atol: 1e-9 } });
      if (result) setOpen(true);
      else setEditing(true);
    } catch (error) { setFormError(error instanceof Error ? error.message : String(error)); setEditing(true); }
  };

  return <section aria-label="通信实验" className="mb-3 rounded-md border border-border bg-bg-panel">
    <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
      <button className="text-sm font-semibold text-text" aria-expanded={open} onClick={() => setOpen(!open)}>{experiment ? experiment.config.goal : "通信实验"}</button>
      <div className="flex items-center gap-3">
        {experiment && <span role="status" className="text-xs text-text-muted">{experiment.stopRequested ? "已停止" : statuses[experiment.status]} · {candidates.length}/{experiment.config.maxIterations} 轮</span>}
        <button disabled={busy} className={buttonClass} onClick={startNew}>{experiment ? "新建实验" : "开始实验"}</button>
      </div>
    </div>
    {error && <p role="alert" className="px-4 pb-3 text-sm text-red-500">{error}</p>}
    {experiment?.recoveryIssue && <p role="alert" className="px-4 pb-3 text-sm text-red-500">{experiment.recoveryIssue}</p>}
    {last?.status === "failed" && <p role="alert" className="px-4 pb-3 text-sm text-red-500">验证失败：{last.reason} 本轮不能应用。</p>}
    {experiment && open && <div className="max-h-80 overflow-auto border-t border-border p-4">
      <p className="mb-3 text-sm text-text-muted">基线 {experiment.baselineCommit.slice(0, 8)} · 随机种子 {experiment.config.seed} · {baseline?.metric === undefined ? "尚未测得基线" : `基线 ${baseline.metric.toFixed(3)} ${experiment.config.metric.unit}`}</p>
      {!owned && <p className="mb-3 text-sm text-text-muted">该实验属于来源会话。当前分支可查看证据，启动新实验后再修改。</p>}
      <div className="mb-3 flex flex-wrap gap-2">
        <button disabled={busy || !owned || experiment.stopRequested || experiment.status === "applied" || candidates.length >= experiment.config.maxIterations} className={buttonClass} onClick={() => void onAction({ type: "experiment_run" })}>{baseline ? "验证当前候选" : "测量基线"}</button>
        <button disabled={busy || !owned || !baseline || experiment.stopRequested || experiment.status === "applied" || candidates.length >= experiment.config.maxIterations} className={buttonClass} onClick={() => onOptimize("在当前已确认的实验范围内持续优化，读取 experiment_status，只修改候选工作区允许的文件，每轮使用 experiment_run 验证并记录理由。达到最大轮数后汇报，不应用候选，不提交。")}>交给智能体优化</button>
        <button disabled={!busy || !owned} className={buttonClass} onClick={() => void onAction({ type: "experiment_stop" })}>停止实验</button>
        {experiment.stopRequested && <button disabled={busy || !owned} className={buttonClass} onClick={() => void onAction({ type: "experiment_resume" })}>继续实验</button>}
        {experiment.pendingApply && <button disabled={busy || !owned} className={buttonClass} onClick={() => void onAction({ type: "experiment_recover" })}>重新检查恢复</button>}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm" aria-label="实验轮次">
          <thead className="text-xs text-text-muted"><tr><th className="py-2 font-normal">轮次</th><th className="font-normal">验证</th><th className="text-right font-normal">{experiment.config.metric.name}（{experiment.config.metric.unit}）</th><th className="text-right font-normal">证据</th></tr></thead>
          <tbody>{experiment.runs.map((run, position) => <tr key={run.id} className="border-t border-border text-text">
            <td className="py-2">{run.kind === "baseline" ? "基线" : `候选 ${position}`}{run.id === best?.id && <span className="ml-2 text-xs text-text-muted">最佳候选</span>}</td><td>{run.status === "passed" ? "通过" : run.status === "failed" ? "失败" : run.status === "cancelled" ? "已停止" : "运行中"}</td>
            <td className="text-right tabular-nums">{run.metric === undefined ? "—" : run.metric.toFixed(3)}</td>
            <td className="flex flex-wrap justify-end gap-2 py-2">
              {run.commands.map((command, commandIndex) => <button key={command.log} className="text-xs text-text-muted underline" onClick={() => onOpenFile?.(command.log)}>日志 {commandIndex + 1}</button>)}
              {run.status === "passed" && <button className="text-xs underline" onClick={async () => { const result = await onAction({ type: "experiment_diff", runId: run.id }) as { diff?: string } | undefined; if (result) setDiff(result.diff || "本轮文件与基线一致。"); }}>差异</button>}
              {run.kind === "candidate" && run.status === "passed" && <button disabled={busy || !owned || experiment.status === "applied"} className="text-xs underline disabled:opacity-40" onClick={() => void onAction({ type: "experiment_apply", runId: run.id })}>应用快照</button>}
            </td>
          </tr>)}</tbody>
        </table>
      </div>
      <details className="mt-3 text-sm text-text-muted"><summary>实验范围与复现参数</summary><p className="mt-2 break-all">候选：{experiment.candidateDirectory}</p><p>允许文件：{experiment.config.allowedFiles.join("、")}</p><p>相对容差 {experiment.config.rtol}，绝对容差 {experiment.config.atol}；指标{experiment.config.metric.direction === "lower" ? "越低越好" : "越高越好"}。</p>{experiment.notes && <p className="mt-2 whitespace-pre-wrap">{experiment.notes}</p>}</details>
      {diff !== null && <div className="mt-3"><button className="mb-2 text-xs underline" onClick={() => setDiff(null)}>关闭差异</button><pre className="max-h-60 overflow-auto whitespace-pre-wrap break-all text-xs text-text">{diff}</pre></div>}
    </div>}
    {editing && <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 p-4">
      <section role="dialog" aria-modal="true" aria-label="创建通信实验" className="max-h-[85vh] w-full max-w-xl overflow-auto rounded-md border border-border bg-bg p-5 shadow-xl">
        <h2 className="mb-4 text-base font-semibold text-text">创建通信实验</h2>
        <div className="grid gap-3">
          <label className="text-sm text-text">优化目标<input className={inputClass} value={goal} onChange={(event) => setGoal(event.target.value)} /></label>
          <label className="text-sm text-text">项目目录<input className={inputClass} value={project} onChange={(event) => setProject(event.target.value)} /></label>
          <label className="text-sm text-text">允许修改的文件（逗号分隔）<input className={inputClass} value={files} onChange={(event) => setFiles(event.target.value)} /></label>
          <div className="grid grid-cols-2 gap-3"><label className="text-sm text-text">最大候选轮数<input className={inputClass} type="number" min={1} max={100} value={maxIterations} onChange={(event) => setMaxIterations(Number(event.target.value))} /></label><label className="text-sm text-text">随机种子<input className={inputClass} type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} /></label></div>
          <details className="text-sm text-text-muted"><summary>验证命令与指标</summary><div className="mt-3 grid gap-3">
            <label>检查命令（参数数组）<textarea className={inputClass} rows={3} value={checks} onChange={(event) => setChecks(event.target.value)} /></label>
            <label>基准命令（参数数组）<textarea className={inputClass} rows={3} value={benchmark} onChange={(event) => setBenchmark(event.target.value)} /></label>
            <div className="grid grid-cols-2 gap-3"><label>指标名称<input className={inputClass} value={metricName} onChange={(event) => setMetricName(event.target.value)} /></label><label>单位<input className={inputClass} value={unit} onChange={(event) => setUnit(event.target.value)} /></label></div>
            <label>优化方向<select className={inputClass} value={direction} onChange={(event) => setDirection(event.target.value as typeof direction)}><option value="lower">越低越好</option><option value="higher">越高越好</option></select></label>
            <p>命令中的 {"{project}"}、{"{python}"}、{"{seed}"} 由实验系统填入。创建后冻结命令；基准输出须包含指标、单位、种子和数值向量。</p>
          </div></details>
        </div>
        {(formError || error) && <p role="alert" className="mt-3 text-sm text-red-500">{formError || error}</p>}
        <div className="mt-5 flex justify-end gap-2"><button className={buttonClass} disabled={busy} onClick={() => setEditing(false)}>取消</button><button disabled={busy} className={buttonClass} onClick={() => void create()}>确认实验设置</button></div>
      </section>
    </div>}
  </section>;
}
