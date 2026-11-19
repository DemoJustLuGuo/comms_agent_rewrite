/**
 * 智能体级资源（extension / prompt / AGENTS.md）的定位与注入。
 *
 * 背景：pi 默认把扩展、提示词模板、项目规则都绑在会话 cwd 上
 * （`<cwd>/.pi/extensions`、`<cwd>/.pi/prompts`、从 cwd 向上找 AGENTS.md）。
 * 但 Web 工作台的 cwd 是用户在侧栏任意选择的——通信域工具是智能体本体，
 * 不是某个项目目录的附属物，不能因为换了工作目录就整体消失
 * （历史故障：cwd 指向空目录 → 0 扩展 0 工具 → 模型退化去手写 python 算 FSPL）。
 *
 * 因此 Web 侧始终按「智能体仓库根」注入这些资源，与 cwd 无关：
 * - 根目录来源：COMMS_AGENT_ROOT（启动脚本导出）优先，否则按本文件位置推导
 *   （vendor/pi-web/lib → 仓库根），保证直接 `next start` 也成立。
 * - 扩展必须逐个列文件：pi 的 additionalExtensionPaths 走 package 解析，
 *   传目录会报 “Cannot find module”；路径按 realpath 去重，仓库内会话不重复注册。
 * - AGENTS.md 只在 cwd 未覆盖它时追加，避免仓库内会话出现两份相同规则。
 *
 * 未探测到仓库根（例如 vendored pi-web 被单独使用）时返回空配置，行为退回上游。
 */
import { existsSync, readFileSync, realpathSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));

export type AgentResourcePaths = {
  root: string;
  extensions: string[];
  promptDir: string | null;
  agentsFile: string | null;
};

function realOrNull(target: string): string | null {
  try {
    return realpathSync(target);
  } catch {
    return null;
  }
}

/** 智能体仓库根：env 覆盖 → 从 vendor/pi-web/lib 上溯三级 → null。 */
export function resolveAgentRoot(): string | null {
  const fromEnv = process.env.COMMS_AGENT_ROOT;
  const candidate = fromEnv ? path.resolve(fromEnv) : path.resolve(HERE, "..", "..", "..");
  return existsSync(path.join(candidate, ".pi")) ? candidate : null;
}

/**
 * 与 cwd 无关的智能体资源清单。只返回真实存在的项，缺失不影响会话创建。
 * 顺序即注册顺序：审批门先于域工具，MCP 最后。
 */
export function agentResourcePaths(): AgentResourcePaths | null {
  const root = resolveAgentRoot();
  if (!root) return null;

  const extensions = [
    ".pi/extensions/approval-gate.ts",
    ".pi/extensions/git-checkpoint.ts",
    ".pi/extensions/comms-tools/index.ts",
    ".pi/extensions/comms-experiments/index.ts",
    "vendor/pi-mcp-extension/src/index.ts",
  ]
    .map((relative) => path.join(root, relative))
    .filter((absolute) => existsSync(absolute));

  const promptDir = path.join(root, ".pi", "prompts");
  const agentsFile = path.join(root, "AGENTS.md");

  return {
    root,
    extensions,
    promptDir: existsSync(promptDir) ? promptDir : null,
    agentsFile: existsSync(agentsFile) ? agentsFile : null,
  };
}

/**
 * 组装 createAgentSessionServices 的 resourceLoaderOptions。
 * AGENTS.md 已由 pi 从 cwd 链加载过（同 realpath）时不再追加。
 */
export function resourceLoaderOptionsFor(resources: AgentResourcePaths | null) {
  if (!resources) return undefined;

  const agentsOverride = resources.agentsFile
    ? (base: { agentsFiles: Array<{ path: string; content: string }> }) => {
        const target = realOrNull(resources.agentsFile!);
        const alreadyLoaded = base.agentsFiles.some((file) => realOrNull(file.path) === target);
        if (alreadyLoaded) return base;
        return {
          agentsFiles: [
            ...base.agentsFiles,
            { path: resources.agentsFile!, content: readFileSync(resources.agentsFile!, "utf-8") },
          ],
        };
      }
    : undefined;

  return {
    ...(resources.extensions.length > 0 ? { additionalExtensionPaths: resources.extensions } : {}),
    ...(resources.promptDir ? { additionalPromptTemplatePaths: [resources.promptDir] } : {}),
    ...(agentsOverride ? { agentsFilesOverride: agentsOverride } : {}),
  };
}
