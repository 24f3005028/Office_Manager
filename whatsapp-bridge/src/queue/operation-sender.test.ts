import assert from "node:assert/strict";
import { test } from "node:test";
import { OperationSender } from "./operation-sender.js";
import { SendQueue } from "./send-queue.js";
import { BridgeError } from "../domain/errors.js";
import { deferred, flush, harness, hasCode, MemoryJournal } from "../testing/fakes.js";

const command = { kind: "text" as const, contactId: "12025550101@c.us", operationId: "mock-job:intro:2026-10-24", text: "Mock message" };
async function setup() {
  const h = harness(); const sdk = await h.ready(); const journal = new MemoryJournal();
  const queue = new SendQueue(0, h.config.sendCapacity, h.config.sendDeadlineMs, h.clock);
  const sender = new OperationSender(h.config, h.client, queue, journal, h.clock);
  return { ...h, sdk, journal, queue, sender, close: async () => { sender.close(); await h.client.close(); } };
}

test("durable reservation precedes submission, in-flight duplicate joins, completed duplicate returns actual receipt", async () => {
  const h = await setup(); const result = deferred<unknown>();
  h.sdk.sendImpl = async () => {
    assert.ok(h.journal.records.has(command.operationId)); return result.promise;
  };
  const first = h.sender.send(command), duplicate = h.sender.send(command);
  await flush(); assert.equal(h.sdk.sends.length, 1);
  result.resolve({ id: { _serialized: "accepted-message-id" } });
  const receipt = { status: "sent", message_id: "accepted-message-id", operation_id: command.operationId };
  assert.deepEqual(await first, receipt); assert.deepEqual(await duplicate, receipt);
  assert.deepEqual(await h.sender.send(command), receipt);
  assert.equal(h.sdk.sends.length, 1);
  assert.equal(h.sdk.sends[0].options.waitUntilMsgSent, true);
  await h.close();
});

test("current WhatsApp id.$1 receipts are accepted, including an empty legacy field", async () => {
  const h = await setup();
  for (const [operationId, shape] of [
    ["current-id-shape", { $1: "current-message-id" }],
    ["empty-legacy-id-shape", { _serialized: " ", $1: "fallback-message-id" }],
  ] as const) {
    h.sdk.sendImpl = async () => ({ id: shape });
    const receipt = { status: "sent", message_id: shape.$1, operation_id: operationId };
    assert.deepEqual(await h.sender.send({ ...command, operationId }), receipt);
    assert.equal(h.journal.records.get(operationId)?.message, shape.$1);
  }
  await h.close();
});

test("the same operation ID cannot be rebound to different text, target, type or account", async () => {
  const h = await setup(); await h.sender.send(command);
  await assert.rejects(h.sender.send({ ...command, text: "Different" }), hasCode("operation_conflict"));
  await assert.rejects(h.sender.send({ ...command, contactId: "12025550102@c.us" }), hasCode("operation_conflict"));
  await assert.rejects(h.sender.send({ operationId: command.operationId, contactId: command.contactId, kind: "upload", filename: "mock.pdf", buffer: Buffer.from("%PDF-mock") }), hasCode("operation_conflict"));
  h.sdk.info.wid._serialized = "12025550199@c.us";
  await assert.rejects(h.sender.send(command), hasCode("operation_conflict"));
  assert.equal(h.sdk.sends.length, 1); await h.close();
});

test("PDF options are explicit, MIME normalized, and duplicate upload fingerprints include bytes", async () => {
  const h = await setup();
  const document = { kind: "upload" as const, operationId: "mock-pdf", contactId: command.contactId, buffer: Buffer.from("%PDF-mock"), filename: "mock.pdf", caption: "Mock caption" };
  await h.sender.send(document);
  const sent = h.sdk.sends[0];
  assert.deepEqual(sent.options, { caption: "Mock caption", waitUntilMsgSent: true, sendMediaAsDocument: true });
  assert.equal(typeof sent.content === "object" && sent.content.mimetype, "application/pdf");
  await assert.rejects(h.sender.send({ ...document, buffer: Buffer.from("%PDF-changed") }), hasCode("operation_conflict"));
  await h.close();
});

test("session-not-ready and stale generations fail before journal reservation or SDK submission", async () => {
  const h = await setup();
  await assert.rejects(h.sender.send({ ...command, generation: 999 }), hasCode("stale_generation"));
  h.sdk.emit("disconnected", "NETWORK");
  await assert.rejects(h.sender.send(command), (error: unknown) => error instanceof BridgeError && error.status === 503 && error.retryable && error.outcome === "not_started");
  assert.equal(h.journal.records.size, 0); assert.equal(h.sdk.sends.length, 0); await h.close();
});

test("LID send targets are resolved to a verified phone identity before journal reservation and SDK submission", async () => {
  const h = await setup();
  const lidCommand = { ...command, operationId: "lid-send", contactId: "lid-token-123456789012345@lid" };
  h.sdk.mappingImpl = async (ids) => ids.map((id) => ({ lid: id, pn: "12025550101@c.us" }));
  await h.sender.send(lidCommand);
  assert.equal(h.sdk.sends[0].id, "12025550101@c.us");
  await h.close();
});

test("unresolved or malformed LID mappings fail before external submission", async () => {
  const h = await setup();
  const lidCommand = { ...command, operationId: "bad-lid-send", contactId: "lid-token-123456789012345@lid" };
  h.sdk.mappingImpl = async () => [{ lid: lidCommand.contactId, pn: "letters12025550101@c.us" }];
  await assert.rejects(h.sender.send(lidCommand), hasCode("unresolved_contact"));
  assert.equal(h.sdk.sends.length, 0); await h.close();
});

test("SDK rejection and missing receipt are outcome_unknown, not retryable, and never replayed", async () => {
  for (const send of [async () => undefined, async () => null, async () => ({ id: {} }), async () => ({ id: { _serialized: "", $1: "   " } }), async () => { throw new Error("private SDK reason"); }]) {
    const h = await setup(); h.sdk.sendImpl = send;
    await assert.rejects(h.sender.send(command), (error: unknown) => error instanceof BridgeError && error.status === 409 && error.code === "outcome_unknown" && !error.retryable && error.outcome === "unknown");
    const restarted = new OperationSender(h.config, h.client, h.queue, h.journal, h.clock);
    await assert.rejects(restarted.send(command), hasCode("outcome_unknown"));
    assert.equal(h.sdk.sends.length, 1); restarted.close(); await h.close();
  }
});

test("hung SDK send times out without releasing its lane and late acceptance does not become a receipt", async () => {
  const h = await setup(); const result = deferred<unknown>(); h.sdk.sendImpl = () => result.promise;
  const unknown = assert.rejects(h.sender.send(command), hasCode("outcome_unknown"));
  await h.clock.advance(100); await unknown;
  const queued = h.sender.send({ ...command, operationId: "next" });
  await flush(); assert.equal(h.sdk.sends.length, 1);
  result.resolve({ id: { _serialized: "late" } }); await flush(); await queued;
  assert.equal(h.journal.records.get(command.operationId)?.message, undefined);
  await assert.rejects(h.sender.send(command), hasCode("outcome_unknown"));
  await h.close();
});

test("reconnect before submission prevents old queued sends; reconnect after submission yields unknown", async () => {
  const h = await setup(); const result = deferred<unknown>(); h.sdk.sendImpl = () => result.promise;
  const first = assert.rejects(h.sender.send(command), hasCode("outcome_unknown"));
  const queued = assert.rejects(h.sender.send({ ...command, operationId: "queued" }), hasCode("stale_generation"));
  await flush(); await h.client.reconnect(); await flush(); h.clients[1].emit("ready");
  result.resolve({ id: { _serialized: "old-generation-receipt" } });
  await Promise.all([first, queued]);
  assert.equal(h.clients[1].sends.length, 0);
  assert.equal(h.journal.records.get(command.operationId)?.message, undefined);
  await h.close();
});

test("a reservation write failure prevents SDK submission; a receipt commit failure is ambiguous", async () => {
  const h = await setup();
  h.journal.reserveImpl = async () => { throw new BridgeError(503, "journal_unavailable", "Journal unavailable"); };
  await assert.rejects(h.sender.send(command), hasCode("journal_unavailable"));
  assert.equal(h.sdk.sends.length, 0);
  h.journal.reserveImpl = async () => undefined;
  h.journal.completeImpl = async () => { throw new Error("private disk failure"); };
  await assert.rejects(h.sender.send(command), hasCode("outcome_unknown"));
  await assert.rejects(h.sender.send(command), hasCode("outcome_unknown"));
  assert.equal(h.sdk.sends.length, 1); await h.close();
});

test("shutdown covers a pending journal lookup and cannot submit after it eventually resolves", async () => {
  const h = await setup(); const lookup = deferred<string | null>();
  h.journal.lookup = () => lookup.promise;
  const rejected = assert.rejects(h.sender.send(command), hasCode("shutting_down"));
  await flush(); h.sender.close(); await rejected;
  lookup.resolve(null); await flush(); assert.equal(h.sdk.sends.length, 0); await h.client.close();
});

test("shutdown during a journal reservation is not_started and a late reservation cannot send", async () => {
  const h = await setup(); const reservation = deferred<void>(); h.journal.reserveImpl = () => reservation.promise;
  const rejected = assert.rejects(h.sender.send(command), hasCode("shutting_down"));
  await flush(); h.sender.close(); await rejected;
  reservation.resolve(); await flush(); assert.equal(h.sdk.sends.length, 0); await h.client.close();
});
