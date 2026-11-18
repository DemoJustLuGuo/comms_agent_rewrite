"use client";

import type { ExtensionUiRequest } from "@/lib/types";

type ConfirmRequest = Extract<ExtensionUiRequest, { method: "confirm" }>;

export function ApprovalRequest({ request, count, busy, error, onRespond }: {
  request: ConfirmRequest;
  count: number;
  busy: boolean;
  error: string | null;
  onRespond: (request: ConfirmRequest, response: { confirmed: boolean }) => void;
}) {
  return (
    <section aria-label="待批准操作" className="mb-3 rounded-md border border-border bg-bg-panel p-4">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-sm font-semibold text-text">{request.title}</h2>
        <span className="shrink-0 text-xs text-text-muted">{count > 1 ? `${count} 项待处理` : "等待批准"}</span>
      </div>
      <p className="my-3 max-h-40 overflow-auto whitespace-pre-wrap break-words text-sm leading-relaxed text-text-muted">{request.message}</p>
      {error && <p role="alert" className="mb-3 text-sm text-red-500">{error}</p>}
      <div className="flex flex-wrap justify-end gap-2">
        <button disabled={busy} onClick={() => onRespond(request, { confirmed: false })} className="rounded border border-border px-4 py-2 text-sm text-text disabled:opacity-50">拒绝</button>
        <button disabled={busy} onClick={() => onRespond(request, { confirmed: true })} className="rounded bg-accent px-4 py-2 text-sm text-white disabled:opacity-50">{busy ? "正在提交…" : "批准本次操作"}</button>
      </div>
    </section>
  );
}
