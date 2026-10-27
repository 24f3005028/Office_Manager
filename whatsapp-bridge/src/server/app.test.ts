import assert from "node:assert/strict";
import { test, type TestContext } from "node:test";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import type { AddressInfo } from "node:net";
import type { BridgeConfig } from "../config.js";
import { createApp, closeApp, startServer } from "./app.js";
import { OperationSender } from "../queue/operation-sender.js";
import { SendQueue } from "../queue/send-queue.js";
import { MAX_PDF_BYTES } from "../domain/path-validation.js";
import { deferred, FakeClient, flush, harness, hasCode, MemoryJournal } from "../testing/fakes.js";

async function fixture(t: TestContext, options: { config?: Partial<BridgeConfig>; create?: () => FakeClient; ready?: boolean } = {}) {
  const h = harness({ config: { port: 0, ...options.config }, create: options.create });
  if (options.ready !== false) await h.ready();
  const journal = new MemoryJournal();
  const sender = new OperationSender(h.config, h.client, new SendQueue(0, 3, 100, h.clock), journal, h.clock);
  const app = createApp(h.config, h.client, sender);
  const server = await startServer(h.config, app);
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  t.after(async () => {
    closeApp(app); await h.client.close(); server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
  });
  const json = (route: string, body: unknown, options: { method?: string; headers?: Record<string, string> } = {}) => fetch(base + route, {
    method: options.method ?? "POST", headers: { "Content-Type": "application/json", ...options.headers }, body: JSON.stringify(body),
  });
  return { ...h, app, server, base, sender, journal, json };
}

const text = { contact_id: "12025550101@c.us", operation_id: "mock-http-op", text: "Mock message" };

test("HTTP start/reconnect return promptly and repeated calls do not duplicate initialization", async (t) => {
  const init = deferred<void>();
  const h = await fixture(t, { ready: false, create: () => { const sdk = new FakeClient(); sdk.initializeImpl = () => init.promise; return sdk; } });
  const responses = await Promise.all([h.json("/start", {}), h.json("/start", {}), h.json("/reconnect", {})]);
  assert.ok(responses.every((r) => r.status === 200));
  assert.equal((await responses[0].json() as { initializing: boolean }).initializing, true);
  assert.equal(h.clients.length, 1);
  const status = await (await fetch(h.base + "/status")).json() as Record<string, unknown>;
  for (const key of ["status", "connected", "qr_available", "initializing", "requires_action", "message", "generation", "qr_revision"]) assert.ok(key in status);
  init.resolve(); await flush();
});

test("Origins are denied before mutation or parsing; configured Origin is allowed", async (t) => {
  const h = await fixture(t, { config: { corsOrigins: ["http://localhost:8000"] }, ready: false });
  for (const route of ["/start", "/reconnect", "/send-text"]) {
    const response = await h.json(route, text, { headers: { Origin: "https://untrusted.example" } });
    assert.equal(response.status, 403); assert.equal((await response.json() as { code: string }).code, "origin_forbidden");
  }
  assert.equal(h.client.status().generation, 0);
  const denied = await h.json("/allowed-roots", { roots: [] }, { method: "PUT", headers: { Origin: "null" } });
  assert.equal(denied.status, 403);
  const allowed = await h.json("/start", {}, { headers: { Origin: "http://localhost:8000" } });
  assert.equal(allowed.status, 200);
  assert.equal(allowed.headers.get("access-control-allow-origin"), "http://localhost:8000");
});

test("optional API key stays optional; configured API key supports both existing headers", async (t) => {
  const h = await fixture(t, { config: { apiKey: "mock-test-key" } });
  const unauthorized = await h.json("/send-text", text);
  assert.equal(unauthorized.status, 401);
  assert.deepEqual(await unauthorized.json(), { error: "Unauthorized", code: "unauthorized", retryable: false, outcome: "not_started" });
  for (const headers of [{ "x-api-key": "mock-test-key" } as Record<string, string>, { authorization: "Bearer mock-test-key" } as Record<string, string>]) {
    const response = await fetch(h.base + "/status", { headers }); assert.equal(response.status, 200);
  }
});

test("HTTP successful sends return receipt plus operation_id, and duplicates never send twice", async (t) => {
  const h = await fixture(t);
  for (let i = 0; i < 2; i++) {
    const response = await h.json("/send-text", text);
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { status: "sent", message_id: "fake-receipt", operation_id: text.operation_id });
  }
  assert.equal(h.clients[0].sends.length, 1);
  const conflict = await h.json("/send-text", { ...text, text: "Different request" });
  assert.equal(conflict.status, 409); assert.equal((await conflict.json() as { code: string }).code, "operation_conflict");
});

test("send input validation rejects missing operation IDs, manufactured routing and invalid generations", async (t) => {
  const h = await fixture(t);
  for (const body of [{ ...text, operation_id: undefined }, { ...text, operation_id: 123 }, { ...text, contact_id: "abc12025550101@c.us" }, { ...text, generation: "1" }, { ...text, generation: -1 }, { ...text, text: " " }]) {
    assert.equal((await h.json("/send-text", body)).status, 400);
  }
  const stale = await h.json("/send-text", { ...text, generation: 99 });
  assert.equal(stale.status, 409); assert.equal((await stale.json() as { code: string }).code, "stale_generation");
  assert.equal(h.clients[0].sends.length, 0);
});

test("not-ready and ambiguous SDK outcomes expose the shared stable error contract", async (t) => {
  const h = await fixture(t);
  h.clients[0].sendImpl = async () => undefined;
  const ambiguous = await h.json("/send-text", text);
  assert.equal(ambiguous.status, 409);
  assert.deepEqual(await ambiguous.json(), {
    error: "The send outcome is unknown; reconcile it before creating another operation", code: "outcome_unknown", retryable: false, outcome: "unknown",
  });
  h.clients[0].emit("disconnected", "NETWORK");
  const offline = await h.json("/send-text", { ...text, operation_id: "offline" });
  assert.equal(offline.status, 503);
  assert.deepEqual(await offline.json(), { error: "WhatsApp is not ready", code: "session_not_ready", retryable: true, outcome: "not_started" });
});

test("JSON/parser/multipart errors are sanitized 4xx and do not disclose body or SDK details", async (t) => {
  const h = await fixture(t);
  for (const [body, contentType] of [["{private-body", "application/json"], ["x".repeat(270_000), "application/json"], ["malformed", "multipart/form-data; boundary=mock"]]) {
    const response = await fetch(h.base + "/send-document", { method: "POST", headers: { "Content-Type": contentType }, body });
    assert.ok(response.status >= 400 && response.status < 500);
    const error = await response.json() as { outcome: string }; assert.equal(error.outcome, "not_started");
    assert.equal(JSON.stringify(error).includes("private-body"), false);
  }
  h.clients[0].sendImpl = async () => { throw new Error("private-file-path and private-body"); };
  const response = await h.json("/send-text", text);
  assert.equal(JSON.stringify(await response.json()).includes("private"), false);
});

test("allowed roots updates validate atomically and [] disables path sending", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "agent-tmp", "bridge-http-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const h = await fixture(t, { config: { allowedRoots: [root] } });
  const rejected = await h.json("/allowed-roots", { roots: [root, "relative"] }, { method: "PUT" });
  assert.equal(rejected.status, 400); assert.deepEqual(h.config.allowedRoots, [root]);
  assert.equal((await h.json("/allowed-roots", { roots: [] }, { method: "PUT" })).status, 200);
  assert.deepEqual(h.config.allowedRoots, []);
  const file = path.join(root, "mock.pdf"); await writeFile(file, "%PDF-mock");
  const denied = await h.json("/send-document", { contact_id: text.contact_id, operation_id: "path", file_path: file });
  assert.equal(denied.status, 400); assert.equal(h.clients[0].sends.length, 0);
  await h.json("/allowed-roots", { roots: [root] }, { method: "PUT" });
  const accepted = await h.json("/send-document", { contact_id: text.contact_id, operation_id: "path", file_path: file });
  assert.equal(accepted.status, 200); assert.equal(h.clients[0].sends[0].options.sendMediaAsDocument, true);
});

test("JSON document sends accept a null caption as absent and still reject non-string captions", async (t) => {
  const root = await mkdtemp(path.join(os.tmpdir(), "agent-tmp", "bridge-caption-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const h = await fixture(t, { config: { allowedRoots: [root] } });
  const file = path.join(root, "mock.pdf"); await writeFile(file, "%PDF-mock");
  for (const [operationId, caption] of [["caption-null", null], ["caption-omitted", undefined]] as const) {
    const response = await h.json("/send-document", {
      contact_id: text.contact_id, operation_id: operationId, file_path: file,
      ...(caption === undefined ? {} : { caption }),
    });
    assert.equal(response.status, 200);
  }
  assert.equal(h.clients[0].sends.length, 2);
  for (const send of h.clients[0].sends) assert.equal(send.options.caption, undefined);
  const invalid = await h.json("/send-document", {
    contact_id: text.contact_id, operation_id: "caption-invalid", file_path: file, caption: 42,
  });
  assert.equal(invalid.status, 400);
  assert.equal((await invalid.json() as { code: string }).code, "invalid_request");
});

test("multipart PDF uses normalized MIME and requires a real PDF signature", async (t) => {
  const h = await fixture(t);
  for (const valid of [false, true]) {
    const form = new FormData();
    form.set("to", text.contact_id); form.set("operation_id", valid ? "upload-valid" : "upload-invalid");
    form.set("generation", String(h.client.status().generation));
    form.set("file", new Blob([valid ? "%PDF-mock" : "not a PDF"], { type: "text/plain" }), "mock.pdf");
    const response = await fetch(h.base + "/send-document", { method: "POST", body: form });
    assert.equal(response.status, valid ? 200 : 400);
  }
  const media = h.clients[0].sends[0].content;
  assert.equal(typeof media === "object" && media.mimetype, "application/pdf");
});

test("multipart rejects files exceeding the common 25 MiB maximum before sending", async (t) => {
  const h = await fixture(t);
  const bytes = new Uint8Array(MAX_PDF_BYTES + 1); bytes.set(Buffer.from("%PDF-"));
  const form = new FormData(); form.set("to", text.contact_id); form.set("operation_id", "oversized");
  form.set("file", new Blob([bytes], { type: "application/pdf" }), "mock.pdf");
  const response = await fetch(h.base + "/send-document", { method: "POST", body: form });
  assert.equal(response.status, 413); assert.equal((await response.json() as { code: string }).code, "upload_rejected");
  assert.equal(h.clients[0].sends.length, 0);
});

test("server listen errors reject instead of hanging or becoming unhandled events", async (t) => {
  const h = await fixture(t);
  const port = (h.server.address() as AddressInfo).port;
  await assert.rejects(startServer({ ...h.config, port }, h.app), hasCode("listen_failed"));
});
