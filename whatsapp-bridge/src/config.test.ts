import assert from "node:assert/strict";
import { test } from "node:test";
import { loadConfig } from "./config.js";

test("configuration is pure, defaults to loopback, and does not require an API key", () => {
  const config = loadConfig({});
  assert.equal(config.host, "127.0.0.1"); assert.equal(config.apiKey, undefined);
  assert.deepEqual(config.allowedRoots, []);
  assert.equal(config.sendCapacity, 8); assert.equal(config.sendDeadlineMs, 120_000);
});

test("configuration rejects unsafe hosts, zero/fractional deadlines and invalid queue limits", () => {
  for (const env of [{ WHATSAPP_BRIDGE_HOST: "0.0.0.0" }, { WHATSAPP_SEND_CAPACITY: "0" }, { WHATSAPP_SEND_CAPACITY: "1.5" }, { WHATSAPP_INIT_TIMEOUT_MS: "0" }, { WHATSAPP_SEND_DEADLINE_MS: "Infinity" }, { WHATSAPP_SEND_DELAY_MS: "-1" }]) assert.throws(() => loadConfig(env));
  assert.equal(loadConfig({ WHATSAPP_SEND_DELAY_MS: "0" }).sendDelayMs, 0);
});
