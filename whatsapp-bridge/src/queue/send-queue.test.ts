import assert from "node:assert/strict";
import { test } from "node:test";
import { SendQueue } from "./send-queue.js";
import { deferred, FakeClock, flush, hasCode } from "../testing/fakes.js";

test("send receipt is acknowledged before cooldown; cooldown delays only the next send", async () => {
  const clock = new FakeClock(); const queue = new SendQueue(50, 3, 1000, clock);
  const seen: number[] = [];
  const first = queue.enqueue(async (context) => { context.markSubmitted(); seen.push(1); return "receipt"; });
  const second = queue.enqueue(async (context) => { context.markSubmitted(); seen.push(2); return "second"; });
  assert.equal(await first, "receipt");
  assert.equal(clock.now(), 0);
  await flush(); assert.deepEqual(seen, [1]);
  await clock.advance(49); assert.deepEqual(seen, [1]);
  await clock.advance(1); assert.equal(await second, "second");
  queue.close();
});

test("capacity and queue deadlines bound work; hung submitted work retains its lane", async () => {
  const clock = new FakeClock(); const queue = new SendQueue(0, 2, 100, clock);
  const hung = deferred<void>(); let started = 0;
  const first = queue.enqueue(async (context) => { context.markSubmitted(); started++; await hung.promise; });
  const firstRejected = assert.rejects(first, hasCode("outcome_unknown"));
  const secondRejected = assert.rejects(queue.enqueue(async () => { started++; }), hasCode("send_deadline"));
  await assert.rejects(queue.enqueue(async () => undefined), hasCode("queue_full"));
  await clock.advance(100); await Promise.all([firstRejected, secondRejected]);
  const later = queue.enqueue(async () => { started++; });
  await flush(); assert.equal(started, 1);
  hung.resolve(); await flush(); await later;
  assert.equal(started, 2); queue.close();
});

test("timed-out preparation cannot subsequently submit", async () => {
  const clock = new FakeClock(); const queue = new SendQueue(0, 2, 100, clock);
  const preparing = deferred<void>(); let submitted = false;
  const pending = queue.enqueue(async (context) => {
    await preparing.promise; context.markSubmitted(); submitted = true;
  });
  const rejected = assert.rejects(pending, hasCode("send_deadline"));
  await clock.advance(100); await rejected;
  preparing.resolve(); await flush();
  assert.equal(submitted, false); queue.close();
});

test("shutdown rejects queued work as not_started and submitted work as unknown", async () => {
  const clock = new FakeClock(); const queue = new SendQueue(0, 2, 100, clock);
  const hung = deferred<void>();
  const active = assert.rejects(queue.enqueue(async (context) => { context.markSubmitted(); await hung.promise; }), hasCode("outcome_unknown"));
  const queued = assert.rejects(queue.enqueue(async () => undefined), hasCode("shutting_down"));
  await flush(); queue.close(); await Promise.all([active, queued]);
  await assert.rejects(queue.enqueue(async () => undefined), hasCode("shutting_down"));
  hung.resolve(); await flush();
});
