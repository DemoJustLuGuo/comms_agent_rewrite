/**
 * comms 域工具扩展：把 tools/ 下的 Python 计算核注册为 pi 自定义工具。
 * 工具清单与 schema 见 defs.ts；spawn/超时/错误包装见 runner.ts。
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent"
import { DEFS } from "./defs"
import { runPyTool } from "./runner"

export default function (pi: ExtensionAPI) {
  for (const def of DEFS) {
    pi.registerTool({
      name: def.name,
      label: def.label,
      description: def.description,
      ...(def.promptSnippet ? { promptSnippet: def.promptSnippet } : {}),
      parameters: def.parameters,
      async execute(_toolCallId, params, signal) {
        return runPyTool(def.name, def.spec, params, signal)
      },
    })
  }
}
