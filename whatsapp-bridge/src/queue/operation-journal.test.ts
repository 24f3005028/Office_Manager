import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { digest, OperationJournal } from "./operation-journal.js";
import { hasCode } from "../testing/fakes.js";

const binding = { fingerprint: digest("mock payload"), account: digest("mock account") };
async function temporary() { return mkdtemp(path.join(os.tmpdir(), "agent-tmp", "bridge-journal-test-")); }

test("durable pending survives restart as unknown; completed duplicate returns the original receipt", async () => {
  const root = await temporary();
  try {
    const first = new OperationJournal(root);
    assert.equal(await first.lookup("mock-id", binding), null);
    assert.equal(await first.reserve("mock-id", binding), null);
    const restarted = new OperationJournal(root);
    await assert.rejects(restarted.lookup("mock-id", binding), hasCode("outcome_unknown"));
    await first.complete("mock-id", binding, "mock-message-id");
    assert.equal(await restarted.lookup("mock-id", binding), "mock-message-id");
    await assert.rejects(restarted.lookup("mock-id", { ...binding, account: digest("other account") }), hasCode("operation_conflict"));
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("atomic reservation has exactly one winner and stored files contain no request payload or paths", async () => {
  const root = await temporary();
  try {
    const first = new OperationJournal(root), second = new OperationJournal(root);
    const results = await Promise.allSettled([first.reserve("../mock-operation", binding), second.reserve("../mock-operation", binding)]);
    assert.equal(results.filter((r) => r.status === "fulfilled").length, 1);
    const files = await readdir(path.join(root, "operations-v1"));
    assert.deepEqual(files, [`${digest("../mock-operation")}.json`]);
    const record = await readFile(path.join(root, "operations-v1", files[0]), "utf8");
    assert.equal(record.includes("mock payload"), false);
    assert.equal(record.includes("mock account"), false);
    assert.equal(record.includes("../mock-operation"), false);
    assert.equal(record.includes(root), false);
  } finally { await rm(root, { recursive: true, force: true }); }
});

test("corrupt journal is fail-closed, never treated as a new operation", async () => {
  const root = await temporary();
  try {
    const journal = new OperationJournal(root); await journal.reserve("mock-id", binding);
    await writeFile(path.join(root, "operations-v1", `${digest("mock-id")}.json`), "{corrupt");
    await assert.rejects(journal.lookup("mock-id", binding), hasCode("journal_unavailable"));
    await assert.rejects(journal.reserve("mock-id", binding), hasCode("journal_unavailable"));
  } finally { await rm(root, { recursive: true, force: true }); }
});
