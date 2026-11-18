import type { ExtensionUiRequest } from "./types";

export type PendingDialog = Extract<ExtensionUiRequest, { method: "confirm" | "select" | "input" | "editor" }>;

export function upsertRequest(requests: PendingDialog[], request: PendingDialog): PendingDialog[] {
  const index = requests.findIndex((item) => item.id === request.id);
  if (index < 0) return [...requests, request];
  return requests.map((item, position) => position === index ? request : item);
}

export function removeRequest(requests: PendingDialog[], id: string): PendingDialog[] {
  return requests.filter((item) => item.id !== id);
}

export function pendingDialogs(requests: ExtensionUiRequest[]): PendingDialog[] {
  return requests.filter((request): request is PendingDialog => ["confirm", "select", "input", "editor"].includes(request.method));
}
