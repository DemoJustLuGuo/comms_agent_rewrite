/**
 * 离线冒烟测试：不起模型会话，直接以 mock ExtensionAPI 加载 comms-tools 扩展，
 * 逐个调用 execute 验证 Python 计算核桥接（bun scripts/dev/smoke_extension.ts）。
 *
 * 覆盖 15 个工具中的 14 个真实调用；online_knowledge 需外网，仅验证注册
 * （其 provider 解析逻辑由 scripts/tests/test_online_knowledge.py 用 mock 覆盖）。
 */
import commsTools from "../../.pi/extensions/comms-tools/index"

interface Registered {
  name: string
  execute: (id: string, params: unknown, signal?: AbortSignal) => Promise<{ content: Array<{ type: string; text: string }> }>
}

const tools: Registered[] = []
const mockPi = {
  registerTool: (def: Registered) => tools.push(def),
  on: () => {},
  registerCommand: () => {},
} as any

commsTools(mockPi)
console.log(`registered ${tools.length} tools: ${tools.map((t) => t.name).join(", ")}`)
if (tools.length !== 15) {
  console.log("[FAIL] 期望注册 15 个工具")
  process.exit(1)
}

const VENV_PY = "F:/CODE/agent_rewrite_in_PI/.venv/Scripts/python.exe"
const sine = Array.from({ length: 256 }, (_, n) => Math.sin((2 * Math.PI * 100 * n) / 1000))

// 每工具一条快乐路径 + link_budget 一条域错误路径；参数刻意取小保证秒级返回。
const cases: Array<{ tool: string; params: unknown; expect: string }> = [
  {
    tool: "link_budget",
    params: { tx_power_dbm: 30, tx_gain_dbi: 15, rx_gain_dbi: 12, freq_mhz: 2400, distance_km: 10, other_losses_db: 2 },
    expect: "-65.04 dBm",
  },
  {
    tool: "link_budget",
    params: { tx_power_dbm: 30, tx_gain_dbi: 0, rx_gain_dbi: 0, freq_mhz: 2400, distance_km: 0 },
    expect: "错误", // 域校验失败：退出码 0 + 可读提示
  },
  { tool: "path_loss", params: { model: "hata", freq_mhz: 900, distance_km: 5 }, expect: "路径损耗" },
  { tool: "ber_snr", params: { modulation: "QPSK", mode: "snr_to_ber", snr_db: 8 }, expect: "BER" },
  { tool: "modulation", params: { mode: "constellation", modulation: "QPSK" }, expect: "星座" },
  { tool: "channel", params: { modulation: "BPSK", snr_db: 6, num_bits: 20000, seed: 1 }, expect: "BER" },
  {
    tool: "channel_coding",
    params: { code: "hamming_7_4", modulation: "BPSK", ebn0_db: [4], num_bits: 4000, seed: 1 },
    expect: "编码",
  },
  { tool: "capacity", params: { mode: "awgn", bandwidth_hz: 1e6, snr_db: 10 }, expect: "容量" },
  { tool: "pulse_shaping", params: { modulation: "QPSK", output: "impulse", seed: 1 }, expect: "RRC" },
  { tool: "ofdm", params: { metric: "papr", n_symbols: 50, seed: 1 }, expect: "PAPR" },
  { tool: "signal_analysis", params: { signal: sine, sample_rate_hz: 1000 }, expect: "峰值" },
  { tool: "frame_parser", params: { hex_data: "01020304", format: "tlv" }, expect: "TLV" },
  { tool: "comms_lint", params: { path: "scripts/tests/fixtures/lint_clean.py", checks: "all" }, expect: "体检完成" },
  {
    tool: "equivalence_check",
    params: {
      baseline_cmd: `"${VENV_PY}" -c "print(1.234567)"`,
      candidate_cmd: `"${VENV_PY}" -c "print(1.234567)"`,
    },
    expect: "PASS",
  },
  {
    tool: "plot",
    params: { plot_type: "constellation", i: [1, -1, 1, -1], q: [1, 1, -1, -1], title: "smoke_qpsk" },
    expect: "COMM_ARTIFACT",
  },
]

let failed = 0
for (const c of cases) {
  const tool = tools.find((t) => t.name === c.tool)!
  const t0 = Date.now()
  const r = await tool.execute("smoke", c.params)
  const text = r.content[0].text
  const ok = text.includes(c.expect)
  console.log(`[${ok ? "PASS" : "FAIL"}] ${c.tool} → 期望含「${c.expect}」（${((Date.now() - t0) / 1000).toFixed(1)}s）`)
  if (!ok) {
    failed++
    console.log(text.slice(0, 400))
  }
}
console.log(failed ? `${failed} 个用例失败` : "全部通过")
process.exit(failed ? 1 : 0)
