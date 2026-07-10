/**
 * 离线冒烟测试：不起模型会话，直接以 mock ExtensionAPI 加载 comms-tools 扩展，
 * 逐个调用 execute 验证 Python 计算核桥接（bun scripts/dev/smoke_extension.ts）。
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
console.log(`registered tools: ${tools.map((t) => t.name).join(", ")}`)

const cases: Array<{ tool: string; params: unknown; expect: string }> = [
  {
    tool: "link_budget",
    params: { tx_power_dbm: 30, tx_gain_dbi: 15, rx_gain_dbi: 12, freq_mhz: 2400, distance_km: 10, other_losses_db: 2 },
    expect: "-65.04 dBm",
  },
  {
    tool: "plot",
    params: { plot_type: "constellation", i: [1, -1, 1, -1], q: [1, 1, -1, -1], title: "smoke_qpsk" },
    expect: "COMM_ARTIFACT",
  },
  {
    tool: "link_budget",
    params: { tx_power_dbm: 30, tx_gain_dbi: 0, rx_gain_dbi: 0, freq_mhz: 2400, distance_km: 0 },
    expect: "错误", // 域校验失败：退出码 0 + 可读提示
  },
]

let failed = 0
for (const c of cases) {
  const tool = tools.find((t) => t.name === c.tool)!
  const r = await tool.execute("smoke", c.params)
  const text = r.content[0].text
  const ok = text.includes(c.expect)
  console.log(`[${ok ? "PASS" : "FAIL"}] ${c.tool} → 期望含「${c.expect}」`)
  if (!ok) {
    failed++
    console.log(text.slice(0, 400))
  }
}
process.exit(failed ? 1 : 0)
