import { NextResponse } from "next/server";
import { mkdtempSync, rmSync, writeFileSync } from "fs";
import { tmpdir } from "os";
import { join } from "path";
import { AuthStorage, ModelRegistry } from "@earendil-works/pi-coding-agent";

export const dynamic = "force-dynamic";

const FETCH_TIMEOUT_MS = 20_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

// Parse an OpenAI-style /models response into a flat list of model ids.
// Tolerates the common shapes: { data: [{ id }] }, { models: [...] }, or a bare array.
function extractModelIds(payload: unknown): string[] {
  const rows: unknown =
    isRecord(payload) && Array.isArray(payload.data) ? payload.data
    : isRecord(payload) && Array.isArray(payload.models) ? payload.models
    : Array.isArray(payload) ? payload
    : [];
  if (!Array.isArray(rows)) return [];
  const ids: string[] = [];
  for (const row of rows) {
    if (typeof row === "string") { ids.push(row); continue; }
    if (isRecord(row)) {
      const id = row.id ?? row.name ?? row.model;
      if (typeof id === "string" && id.trim()) ids.push(id.trim());
    }
  }
  // De-dup while preserving order
  return [...new Set(ids)];
}

export async function POST(req: Request) {
  let tempDir: string | undefined;

  try {
    const body = await req.json() as { providerName?: unknown; provider?: unknown };
    const providerName = typeof body.providerName === "string" ? body.providerName.trim() : "";
    if (!providerName) return NextResponse.json({ ok: false, error: "providerName is required" }, { status: 400 });
    if (!isRecord(body.provider)) return NextResponse.json({ ok: false, error: "provider is required" }, { status: 400 });

    const baseUrl = typeof body.provider.baseUrl === "string" ? body.provider.baseUrl.trim() : "";
    if (!baseUrl) return NextResponse.json({ ok: false, error: "Base URL is required to list models" }, { status: 400 });

    // Resolve apiKey/headers exactly the way a real request would: write a temp
    // models.json with a placeholder model and let ModelRegistry resolve auth
    // (env vars, !shell commands, literals) — same pattern as the test route.
    tempDir = mkdtempSync(join(tmpdir(), "pi-web-list-models-"));
    const modelsPath = join(tempDir, "models.json");
    const PROBE_ID = "__list_models_probe__";
    writeFileSync(modelsPath, JSON.stringify({
      providers: {
        [providerName]: {
          ...body.provider,
          models: [{ id: PROBE_ID }],
        },
      },
    }, null, 2), "utf8");

    const registry = ModelRegistry.create(AuthStorage.create(), modelsPath);
    const loadError = registry.getError();
    if (loadError) return NextResponse.json({ ok: false, error: loadError });

    const probe = registry.find(providerName, PROBE_ID);
    if (!probe) return NextResponse.json({ ok: false, error: `Provider not found: ${providerName}` });

    const auth = await registry.getApiKeyAndHeaders(probe);
    if (!auth.ok) return NextResponse.json({ ok: false, error: auth.error });

    const headers: Record<string, string> = { ...(auth.headers ?? {}) };
    const hasAuthHeader = Object.keys(headers).some((k) => k.toLowerCase() === "authorization");
    if (auth.apiKey && !hasAuthHeader) {
      headers["Authorization"] = `Bearer ${auth.apiKey}`;
    }

    const url = `${baseUrl.replace(/\/+$/, "")}/models`;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    const startedAt = Date.now();

    try {
      const res = await fetch(url, { method: "GET", headers, signal: controller.signal });
      const latencyMs = Date.now() - startedAt;
      const text = await res.text();

      if (!res.ok) {
        return NextResponse.json({
          ok: false,
          error: `HTTP ${res.status}${text ? `: ${text.slice(0, 300)}` : ""}`,
          status: res.status,
          latencyMs,
        });
      }

      let payload: unknown;
      try {
        payload = JSON.parse(text);
      } catch {
        return NextResponse.json({ ok: false, error: "Response was not valid JSON", status: res.status, latencyMs });
      }

      const models = extractModelIds(payload);
      if (models.length === 0) {
        return NextResponse.json({ ok: false, error: "No models found in response", status: res.status, latencyMs });
      }

      return NextResponse.json({ ok: true, models, status: res.status, latencyMs });
    } finally {
      clearTimeout(timeout);
    }
  } catch (error) {
    return NextResponse.json({ ok: false, error: errorMessage(error) }, { status: 500 });
  } finally {
    if (tempDir) rmSync(tempDir, { recursive: true, force: true });
  }
}
