/**
 * Configuration loading, validation, and merging for pi-mcp.
 *
 * Config file locations (highest priority first):
 *   1. <cwd>/.pi/mcp.json        — project-level config
 *   2. <agentRoot>/.pi/mcp.json  — agent-level config（COMMS_AGENT_ROOT，见下）
 *   3. ~/.pi/agent/mcp.json      — user global config
 *
 * 本地修改（comms agent）：上游只读 <cwd> 与 ~/.pi/agent。Web 工作台的 cwd 由用户任选，
 * 通信智能体自带的 MCP 服务（MATLAB / fetch）不该随工作目录消失，因此增加 agent 级配置：
 * 由启动脚本通过 COMMS_AGENT_ROOT 指向智能体仓库根。agentRoot 等于 cwd 时去重（仓库内会话
 * 即项目级配置，不重复读取）。未设置时行为与上游一致。
 *
 * 后两个来源按 key 浅合并、逐 server 覆盖（project > agent > global）。
 * No deep merge, no env var interpolation — WYSIWYG config.
 */

import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { z } from "zod";
import { McpError } from "./errors.js";

// ─── Zod Schemas ──────────────────────────────────────────────────────────────

const AuthConfigSchema = z.object({
  /** Auth type. Currently only "oauth" is supported. Default: "oauth". */
  type: z.enum(["oauth"]).default("oauth"),
  /**
   * Callback URL for the OAuth redirect.
   * Default: auto-detected local callback server.
   */
  redirectUrl: z.string().optional(),
  /**
   * Optional scope to request during authorization.
   */
  scope: z.string().optional(),
  /**
   * Pre-registered client_id (skip dynamic client registration).
   */
  clientId: z.string().optional(),
  /**
   * Pre-registered client_secret.
   */
  clientSecret: z.string().optional(),
});

const ServerConfigSchema = z
  .object({
    /** Executable to spawn (e.g. "npx", "node", "uvx"). Required for stdio. */
    command: z.string().optional(),
    /** Arguments passed to command. */
    args: z.array(z.string()).default([]),
    /**
     * Extra environment variables passed to the child process as literals.
     * These merge with process.env; project env overrides parent env.
     * No ${VAR} interpolation — set vars in your shell environment instead.
     */
    env: z.record(z.string()).optional(),
    /** Transport protocol. Default: "stdio". */
    transport: z.enum(["stdio", "streamable-http", "sse"]).default("stdio"),
    /**
     * URL for streamable-http or sse transports.
     * Must be a valid URL (e.g. "https://my-mcp-server.example.com/mcp").
     */
    url: z.string().url().optional(),
    /**
     * Static HTTP headers to include with every request (streamable-http / sse only).
     * Useful for API-key-based auth (e.g. { "Authorization": "Bearer <key>" }).
     * For OAuth2, use the "auth" field instead.
     */
    headers: z.record(z.string()).optional(),
    /**
     * OAuth2 configuration for servers that require authorization.
     * When set, the transport will use the SDK's OAuth flow (discovery,
     * dynamic client registration, PKCE, token refresh).
     * Only applies to streamable-http and sse transports.
     */
    auth: AuthConfigSchema.optional(),
    /**
     * "eager" — start at session_start.
     * "lazy"  — start manually via /mcp:start command.
     */
    lifecycle: z.enum(["eager", "lazy"]).default("lazy"),
    /** Per-request timeout in ms. Overrides global setting. Default: 30000. */
    requestTimeoutMs: z.number().positive().optional(),
    /**
     * Opt-in heartbeat interval (ping) in ms.
     * Only useful for long-lived connections where you want proactive liveness checks.
     * Default: disabled.
     */
    healthCheckIntervalMs: z.number().positive().optional(),
  })
  .refine(
    (cfg) => {
      if (cfg.transport === "stdio") return cfg.command !== undefined;
      return cfg.url !== undefined;
    },
    (cfg) => ({
      message:
        cfg.transport === "stdio"
          ? `"command" is required for stdio transport`
          : `"url" is required for ${cfg.transport} transport`,
    }),
  );

const SettingsSchema = z.object({
  /**
   * Prefix used in Pi tool names: <prefix>_<server>_<tool>.
   * Must match [a-zA-Z0-9_]. Default: "mcp".
   */
  toolPrefix: z
    .string()
    .regex(/^[a-zA-Z0-9_]+$/, "toolPrefix must match [a-zA-Z0-9_]")
    .default("mcp"),
  /** Default per-request timeout in ms for all servers. Default: 30000. */
  requestTimeoutMs: z.number().positive().default(30000),
  /** Maximum retry attempts when a server fails to connect. Default: 5. */
  maxRetries: z.number().int().min(0).max(10).default(5),
});

const McpConfigSchema = z.object({
  settings: SettingsSchema.default({}),
  mcpServers: z.record(ServerConfigSchema).default({}),
});

// ─── Public Types ─────────────────────────────────────────────────────────────

export type AuthConfig = z.output<typeof AuthConfigSchema>;
export type ServerConfig = z.output<typeof ServerConfigSchema>;
export type Settings = z.output<typeof SettingsSchema>;
export type McpConfig = z.output<typeof McpConfigSchema>;

// ─── Loader ───────────────────────────────────────────────────────────────────

async function readJsonFile(path: string): Promise<unknown | null> {
  try {
    const text = await readFile(path, "utf8");
    return JSON.parse(text) as unknown;
  } catch (err) {
    // ENOENT → file doesn't exist, silently skip
    if ((err as NodeJS.ErrnoException).code === "ENOENT") return null;
    throw err;
  }
}

function parseConfig(raw: unknown, sourcePath: string): McpConfig {
  const result = McpConfigSchema.safeParse(raw);
  if (!result.success) {
    const issues = result.error.issues
      .map((i) => `  ${i.path.join(".")}: ${i.message}`)
      .join("\n");
    throw new McpError(
      `Invalid mcp.json at ${sourcePath}:\n${issues}`,
      "<config>",
      "config",
    );
  }
  return result.data;
}

function mergeConfigs(
  globalCfg: McpConfig,
  projectCfg: McpConfig,
): McpConfig {
  return {
    // Shallow spread: project settings override global settings per key
    settings: { ...globalCfg.settings, ...projectCfg.settings },
    // Per-server override: project server entry completely replaces global entry with same name
    mcpServers: { ...globalCfg.mcpServers, ...projectCfg.mcpServers },
  };
}

/**
 * Resolve the agent-level config path.
 *
 * COMMS_AGENT_ROOT 由启动脚本（scripts/comms-env.sh）导出为智能体仓库根；未设置时返回
 * undefined，保持上游「仅 project + global」的行为。cwd 就是仓库根时不去重——那正是同一
 * 份 <cwd>/.pi/mcp.json，交给 loadConfig 里的路径去重处理。
 */
function agentConfigPath(): string | undefined {
  const root = process.env.COMMS_AGENT_ROOT;
  if (!root) return undefined;
  return join(resolve(root), ".pi", "mcp.json");
}

/**
 * Load and merge project (<cwd>/.pi/mcp.json), agent (<COMMS_AGENT_ROOT>/.pi/mcp.json)
 * and global (~/.pi/agent/mcp.json) configs. Project > agent > global.
 * Same-path sources are read once. Returns a fully validated, merged config.
 */
export async function loadConfig(cwd: string): Promise<McpConfig> {
  const globalPath = join(homedir(), ".pi", "agent", "mcp.json");
  const projectPath = join(resolve(cwd), ".pi", "mcp.json");
  const agentPath = agentConfigPath();

  const candidates = [projectPath, agentPath, globalPath]
    .filter((p): p is string => p !== undefined)
    .filter((p, index, all) => all.indexOf(p) === index);
  const sources = await Promise.all(
    candidates.map(async (path) => ({
      path,
      raw: await readJsonFile(path),
    })),
  );

  // If none of the files exist, return an empty valid config
  if (sources.every((source) => source.raw === null)) {
    return McpConfigSchema.parse({});
  }

  // Merge lowest → highest priority so later sources win per key.
  let merged = McpConfigSchema.parse({});
  for (const source of [...sources].reverse()) {
    const cfg = source.raw !== null
      ? parseConfig(source.raw, source.path)
      : McpConfigSchema.parse({});
    merged = mergeConfigs(merged, cfg);
  }
  return merged;
}
