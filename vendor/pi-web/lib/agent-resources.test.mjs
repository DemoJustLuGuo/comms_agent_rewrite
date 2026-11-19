import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

/**
 * 回归：通信域工具、提示词模板和 AGENTS.md 必须跟随智能体，而不是跟随用户选择的
 * 工作目录。历史故障：会话 cwd 指向空目录 → 0 扩展 0 工具 → 模型退化去手写 python。
 */
async function loadSubject() {
  return import("./agent-resources.ts");
}

function fakeAgentRoot() {
  const root = mkdtempSync(path.join(tmpdir(), "comms-agent-root-"));
  mkdirSync(path.join(root, ".pi", "prompts"), { recursive: true });
  mkdirSync(path.join(root, "vendor", "pi-mcp-extension", "src"), { recursive: true });
  writeFileSync(path.join(root, ".pi", "prompts", "term.md"), "# term\n");
  writeFileSync(path.join(root, "AGENTS.md"), "# agent rules\n");
  writeFileSync(path.join(root, "vendor", "pi-mcp-extension", "src", "index.ts"), "export default () => {}\n");
  for (const ext of ["approval-gate.ts", "git-checkpoint.ts", "comms-tools/index.ts", "comms-experiments/index.ts"]) {
    const target = path.join(root, ".pi", "extensions", ext);
    mkdirSync(path.dirname(target), { recursive: true });
    writeFileSync(target, "export default () => {}\n");
  }
  return root;
}

test("agent resources resolve from COMMS_AGENT_ROOT, not from cwd", async () => {
  const { agentResourcePaths } = await loadSubject();
  const root = fakeAgentRoot();
  const previous = process.env.COMMS_AGENT_ROOT;
  process.env.COMMS_AGENT_ROOT = root;
  try {
    const resources = agentResourcePaths();
    assert.equal(resources?.root, root);
    assert.deepEqual(
      resources?.extensions.map((entry) => path.relative(root, entry)),
      [
        ".pi/extensions/approval-gate.ts",
        ".pi/extensions/git-checkpoint.ts",
        ".pi/extensions/comms-tools/index.ts",
        ".pi/extensions/comms-experiments/index.ts",
        "vendor/pi-mcp-extension/src/index.ts",
      ],
    );
    assert.equal(resources?.promptDir, path.join(root, ".pi", "prompts"));
    assert.equal(resources?.agentsFile, path.join(root, "AGENTS.md"));
  } finally {
    if (previous === undefined) delete process.env.COMMS_AGENT_ROOT;
    else process.env.COMMS_AGENT_ROOT = previous;
    rmSync(root, { recursive: true, force: true });
  }
});

test("resource loader options skip a directory that is not an agent root", async () => {
  const { agentResourcePaths, resourceLoaderOptionsFor } = await loadSubject();
  const unrelated = mkdtempSync(path.join(tmpdir(), "not-an-agent-"));
  const previous = process.env.COMMS_AGENT_ROOT;
  process.env.COMMS_AGENT_ROOT = unrelated;
  try {
    assert.equal(agentResourcePaths(), null);
    assert.equal(resourceLoaderOptionsFor(null), undefined);
  } finally {
    if (previous === undefined) delete process.env.COMMS_AGENT_ROOT;
    else process.env.COMMS_AGENT_ROOT = previous;
    rmSync(unrelated, { recursive: true, force: true });
  }
});

test("AGENTS.md is appended once and deduped when cwd already loaded it", async () => {
  const { resourceLoaderOptionsFor } = await loadSubject();
  const root = fakeAgentRoot();
  try {
    const options = resourceLoaderOptionsFor({
      root,
      extensions: [],
      promptDir: null,
      agentsFile: path.join(root, "AGENTS.md"),
    });
    const override = options?.agentsFilesOverride;

    const alreadyLoaded = override({ agentsFiles: [{ path: path.join(root, "AGENTS.md"), content: "# agent rules\n" }] });
    assert.equal(alreadyLoaded.agentsFiles.length, 1);

    const withoutProjectCopy = override({ agentsFiles: [] });
    assert.equal(withoutProjectCopy.agentsFiles.length, 1);
    assert.equal(withoutProjectCopy.agentsFiles[0].content, "# agent rules\n");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});