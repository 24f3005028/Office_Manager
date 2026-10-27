import assert from "node:assert/strict";
import { test } from "node:test";
import { PreservingLocalAuth } from "./whatsapp-client.js";
import { deferred, FakeClient, flush, harness, hasCode } from "../testing/fakes.js";

test("start is prompt, idempotent and exposes the additive status contract", async () => {
  const init = deferred<void>();
  const h = harness({ create: () => { const sdk = new FakeClient(); sdk.initializeImpl = () => init.promise; return sdk; } });
  await Promise.all([h.client.start(), h.client.start(), h.client.reconnect()]);
  await flush();
  assert.equal(h.clients.length, 1);
  assert.equal(h.clients[0].initializes, 1);
  assert.deepEqual(h.client.status(), {
    status: "starting", connected: false, qr_available: false, initializing: true,
    requires_action: null, message: "Starting the saved WhatsApp session.", generation: 1, qr_revision: 1,
  });
  init.resolve(); await flush(); await h.client.close();
});

test("initialization rejection retries fresh clients and recovers without unhandled rejection", async () => {
  let created = 0;
  const h = harness({ create: () => {
    const sdk = new FakeClient();
    if (!created++) sdk.initializeImpl = async () => { throw new Error("private SDK detail"); };
    return sdk;
  } });
  await h.client.start(); await flush();
  assert.equal(h.client.status().status, "retrying");
  await h.clock.advance(10);
  assert.equal(h.clients.length, 2);
  assert.ok(h.clients[0].destroys >= 1);
  h.clients[1].emit("ready");
  assert.equal(h.client.status().connected, true);
  await h.client.close();
});

test("resolved initialize without ready has a bounded retry budget and repair action", async () => {
  const h = harness();
  await h.client.start(); await h.clock.advance(330);
  assert.equal(h.clients.length, 3);
  assert.equal(h.client.status().status, "error");
  assert.equal(h.client.status().requires_action, "repair");
  assert.equal(h.client.status().initializing, false);
  await h.client.close();
});

test("authenticated is not ready and repeated authentication does not extend its deadline", async () => {
  const h = harness();
  await h.client.start(); await flush();
  h.clients[0].emit("authenticated");
  assert.equal(h.client.status().initializing, true);
  assert.equal(h.client.status().requires_action, null);
  await h.clock.advance(50);
  h.clients[0].emit("authenticated");
  await h.clock.advance(50);
  assert.equal(h.client.status().status, "retrying");
  await h.client.close();
});

test("hung initializer fails closed instead of launching overlapping browsers; late completion is cleaned up", async () => {
  const init = deferred<void>();
  const h = harness({ create: () => { const sdk = new FakeClient(); sdk.initializeImpl = () => init.promise; return sdk; } });
  await h.client.start(); await h.clock.advance(110);
  assert.equal(h.client.status().requires_action, "repair");
  assert.equal(h.clients.length, 1);
  init.resolve(); await flush();
  assert.ok(h.clients[0].destroys >= 2);
  await h.client.close();
});

test("QR conversions are revision-guarded and cannot reappear after authentication", async () => {
  const first = deferred<string>(), second = deferred<string>();
  const h = harness({ qr: (qr) => qr === "one" ? first.promise : second.promise });
  await h.client.start(); await flush();
  h.clients[0].emit("qr", "one");
  h.clients[0].emit("qr", "two");
  second.resolve("<svg>two</svg>"); await flush();
  first.resolve("<svg>one</svg>"); await flush();
  assert.equal(h.client.qr(), "<svg>two</svg>");
  assert.equal(h.client.status().requires_action, "link");
  h.clients[0].emit("authenticated");
  assert.equal(h.client.qr(), null);
  assert.equal(h.client.status().status, "authenticated");
  await h.client.close();
});

test("old client callbacks and late QR failures cannot mutate a replacement session", async () => {
  const qr = deferred<string>();
  const h = harness({ qr: () => qr.promise });
  const old = await h.ready();
  old.emit("qr", "mock");
  old.emit("authenticated"); // ready client ignores repeated authenticated
  old.emit("disconnected", "NETWORK");
  await h.client.reconnect(); await flush();
  h.clients[1].emit("ready");
  const status = h.client.status();
  for (const event of ["ready", "authenticated", "auth_failure", "disconnected", "error", "loading_screen", "change_state"]) old.emit(event, "UNPAIRED");
  qr.reject(new Error("private")); await flush();
  assert.deepEqual(h.client.status(), status);
  await h.client.close();
});

test("actual auth failure requires relinking, transient disconnect does not", async () => {
  const h = harness(); const sdk = await h.ready();
  sdk.emit("disconnected", "NETWORK");
  assert.equal(h.client.status().requires_action, null);
  await h.client.reconnect(); await flush(); h.clients[1].emit("auth_failure");
  assert.equal(h.client.status().status, "auth_failure");
  assert.equal(h.client.status().requires_action, "relink");
  await h.client.close();
});

test("reconnect, start and close serialize and shutdown cannot be restarted", async () => {
  const h = harness(); const sdk = await h.ready();
  await Promise.all([h.client.reconnect(), h.client.start(), h.client.reconnect()]);
  const closing = h.client.close();
  await closing;
  assert.equal(h.client.status().status, "disconnected");
  assert.ok(sdk.destroys >= 1);
  assert.equal(h.client.close(), closing);
  await assert.rejects(h.client.start(), hasCode("shutting_down"));
});

test("preserving auth strategy never invokes filesystem deletion on logout", async () => {
  const auth = new PreservingLocalAuth({ clientId: "mock", dataPath: "unused-mock-auth" });
  await auth.logout(); // No browser or auth directory is created/read.
});

test("contacts resolve verified LIDs, retain same-name different phones and cache mappings", async () => {
  const h = harness(); const sdk = await h.ready();
  sdk.contactsImpl = async () => [
    { id: "lid-token-123456789012345@lid", name: "Customer", isMyContact: true },
    { id: "12025550102@c.us", name: "Customer", isMyContact: true },
    { id: "12025550101@c.us", name: "Alias", isMyContact: true },
  ];
  sdk.mappingImpl = async () => [
    { lid: "lid-token-123456789012345@lid", pn: "12025550101@c.us" },
    { lid: "999@lid", pn: "12025550999@c.us" },
  ];
  const contacts = await h.client.contacts();
  assert.deepEqual(contacts.map((c) => c.number), ["12025550101", "12025550102"]);
  await h.client.contacts();
  assert.equal(sdk.contactsCalls, 1);
  assert.equal(sdk.mappingCalls.length, 1);
  await h.client.close();
});

test("stale contacts are returned consistently to concurrent readers during refresh", async () => {
  const h = harness(); const sdk = await h.ready();
  sdk.contactsImpl = async () => [{ id: "12025550101@c.us", name: "First" }];
  const first = await h.client.contacts();
  await h.clock.advance(51);
  const refresh = deferred<Awaited<ReturnType<FakeClient["getContacts"]>>>();
  sdk.contactsImpl = () => refresh.promise;
  assert.deepEqual(await h.client.contacts(), first);
  assert.deepEqual(await h.client.contacts(), first);
  assert.equal(sdk.contactsCalls, 2);
  refresh.resolve([{ id: "12025550102@c.us", name: "Second" }]); await flush();
  assert.equal((await h.client.contacts())[0].name, "Second");
  await h.client.close();
});

test("contacts and LID promises from old generations cannot populate the new cache", async () => {
  const h = harness(); const sdk = await h.ready();
  const old = deferred<Awaited<ReturnType<FakeClient["getContacts"]>>>();
  sdk.contactsImpl = () => old.promise;
  const pending = h.client.contacts();
  const rejected = assert.rejects(pending, hasCode("stale_generation"));
  await h.client.reconnect(); await flush();
  h.clients[1].emit("ready");
  h.clients[1].contactsImpl = async () => [{ id: "12025550102@c.us", name: "New" }];
  old.resolve([{ id: "123456789@lid", name: "Old" }]);
  await rejected;
  assert.equal(sdk.mappingCalls.length, 0);
  assert.equal((await h.client.contacts())[0].name, "New");
  await h.client.close();
});

test("contact SDK hangs are bounded and disconnected callers never receive cached contacts", async () => {
  const h = harness(); const sdk = await h.ready();
  const pending = deferred<Awaited<ReturnType<FakeClient["getContacts"]>>>();
  sdk.contactsImpl = () => pending.promise;
  const rejected = assert.rejects(h.client.contacts(), hasCode("contacts_unavailable"));
  await h.clock.advance(100); await rejected;
  sdk.emit("disconnected", "NETWORK");
  await assert.rejects(h.client.contacts(), hasCode("session_not_ready"));
  pending.resolve([]); await flush(); await h.client.close();
});
