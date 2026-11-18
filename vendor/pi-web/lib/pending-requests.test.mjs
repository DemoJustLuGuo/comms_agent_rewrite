import assert from "node:assert/strict";
import test from "node:test";
import { upsertRequest, removeRequest, pendingDialogs } from "./pending-requests.ts";

test("parallel approvals remain queued and repeated SSE requests do not duplicate them", () => {
  const first = { id: "a", method: "confirm", title: "修改文件", message: "candidate.py" };
  const second = { id: "b", method: "confirm", title: "执行测试", message: "test.py" };
  const queue = upsertRequest(upsertRequest(upsertRequest([], first), second), first);
  assert.deepEqual(queue.map((request) => request.id), ["a", "b"]);
  assert.deepEqual(removeRequest(queue, "a"), [second]);
  assert.deepEqual(removeRequest(queue, "expired"), queue);
});

test("only live dialog requests enter the approval queue", () => {
  const request = { id: "a", method: "confirm", title: "执行", message: "test.py" };
  assert.deepEqual(pendingDialogs([request, { id: "notice", method: "notify", message: "已完成" }]), [request]);
});
