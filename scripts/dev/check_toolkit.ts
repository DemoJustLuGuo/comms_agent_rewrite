import assert from "node:assert/strict"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import path from "node:path"
import { createAgentSession, DefaultResourceLoader, SessionManager, SettingsManager, AuthStorage } from "@earendil-works/pi-coding-agent"
import commsTools from "../../.pi/extensions/comms-tools/index"
import { findTools, DOMAIN_NAMES } from "../../.pi/extensions/comms-tools/catalog"
import { approvalTier } from "../../.pi/extensions/comms-tools/approval"
import { runCalculationBatch, resolveInput } from "../../.pi/extensions/comms-tools/batch"
import { DEFS } from "../../.pi/extensions/comms-tools/defs"
import { runPyTool } from "../../.pi/extensions/comms-tools/runner"

assert.equal(findTools("fft 频谱", DOMAIN_NAMES)[0].name, "signal_analysis")
assert.equal(findTools("LDPC 纠错", DOMAIN_NAMES)[0].name, "channel_coding")
assert.equal(findTools("这里的 MAC 地址怎么配置", DOMAIN_NAMES).length, 0)
assert.equal(findTools("等价校验", ["link_budget"]).length, 0)
assert.equal(approvalTier("write"), "write")
assert.equal(approvalTier("equivalence_check"), "exec")
assert.equal(approvalTier("unknown_extension"), "exec")

const calculation = { tx_power_dbm: 20, tx_gain_dbi: 0, rx_gain_dbi: 0, freq_mhz: 2400, distance_km: 1 }
const batch = await runCalculationBatch([
  { id: "budget", tool: "link_budget", input: calculation },
  { id: "sinr", tool: "interference", input: { mode: "sinr", carrier_dbm: { $from: "budget.rx_power_dbm", unit: "dBm" }, interferers: [{ power_dbm: -90 }], noise_floor_dbm: -100 } },
  { id: "rate", tool: "capacity", input: { mode: "awgn", bandwidth_hz: 1e6, snr_db: { $from: "sinr.ratio_db", unit: "dB" } } },
], DOMAIN_NAMES, { hasUI: false, ui: {} as any })
assert.equal(batch.details.ok, true)
const records = batch.details.steps
assert.equal(records[1].input.carrier_dbm, (records[0].result.details.data as any).rx_power_dbm)
assert.equal(records[2].input.snr_db, (records[1].result.details.data as any).ratio_db)
assert.equal((records[2].result.details.units as any).capacity_bps, "bit/s")
assert.throws(() => resolveInput({ carrier_dbm: { $from: "budget.rx_power_dbm", unit: "dB" } }, "interference", new Map([["budget", records[0].result]])), /单位/)
await assert.rejects(runCalculationBatch([{ id: "bad", tool: "equivalence_check", input: {} }], DOMAIN_NAMES, { hasUI: false, ui: {} as any }), /未允许/)
const definition = DEFS.find((definition) => definition.name === "link_budget")!
const text = await runPyTool(definition.name, { ...definition.spec, structured: false }, calculation)
assert.equal(text.content[0].text, records[0].result.content[0].text)
const failed = await runCalculationBatch([{ id: "bad", tool: "link_budget", input: { ...calculation, distance_km: -1 } }], DOMAIN_NAMES, { hasUI: false, ui: {} as any })
assert.equal(failed.details.ok, false)

const workspace = mkdtempSync(path.join(tmpdir(), "comms-toolkit-"))
const payloads: any[] = []
const server = Bun.serve({ port: 0, hostname: "127.0.0.1", async fetch(request) {
  const payload = await request.json()
  payloads.push(payload)
  const call = payloads.length === 1 ? { id: "discover", type: "function", function: { name: "comms_find", arguments: JSON.stringify({ query: "FFT 频谱分析" }) } } : undefined
  const delta = call ? { role: "assistant", tool_calls: [{ index: 0, ...call }] } : { role: "assistant", content: "工具发现已验证" }
  return new Response(`data: ${JSON.stringify({ id: "fixture", object: "chat.completion.chunk", choices: [{ index: 0, delta, finish_reason: call ? "tool_calls" : "stop" }] })}\n\ndata: [DONE]\n\n`, { headers: { "Content-Type": "text/event-stream" } })
} })
try {
  const settingsManager = SettingsManager.inMemory({ defaultProjectTrust: "always" })
  const resourceLoader = new DefaultResourceLoader({ cwd: workspace, agentDir: workspace, settingsManager, noExtensions: true, noSkills: true, noPromptTemplates: true, noContextFiles: true, extensionFactories: [commsTools] })
  await resourceLoader.reload()
  const authStorage = AuthStorage.inMemory()
  authStorage.setRuntimeApiKey("fixture", "fixture")
  const { session } = await createAgentSession({ cwd: workspace, agentDir: workspace, settingsManager, resourceLoader, authStorage, sessionManager: SessionManager.inMemory(workspace), model: { id: "fixture", name: "fixture", api: "openai-completions", provider: "fixture", baseUrl: `http://127.0.0.1:${server.port}/v1`, reasoning: false, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 10000, maxTokens: 1000 } })
  await session.bindExtensions({ mode: "rpc" })
  await session.prompt("/comms-tools default")
  await session.prompt("分析频谱")
  assert.equal(payloads.length, 2)
  assert(!payloads[0].tools.some((tool: any) => tool.function.name === "signal_analysis"))
  assert(payloads[1].tools.some((tool: any) => tool.function.name === "signal_analysis"))
  await session.prompt("普通问答")
  assert(!payloads[2].tools.some((tool: any) => tool.function.name === "signal_analysis"))
  await session.prompt("/comms-tools full")
  await session.prompt("全量配置")
  assert(payloads[3].tools.some((tool: any) => tool.function.name === "signal_analysis"))
  console.log(JSON.stringify({ passed: true, adaptiveTools: payloads[0].tools.length, discoveredTools: payloads[1].tools.length, fullTools: payloads[3].tools.length, adaptiveSchemaBytes: JSON.stringify(payloads[0].tools).length, fullSchemaBytes: JSON.stringify(payloads[3].tools).length, batchSteps: records.length }))
  session.dispose()
} finally {
  server.stop(true)
  rmSync(workspace, { recursive: true, force: true })
}
