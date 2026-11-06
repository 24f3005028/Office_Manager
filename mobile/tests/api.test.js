import { afterEach, expect, test } from "bun:test";
import { request } from "../src/api";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("empty 502 explains the stopped office instead of exposing a JSON error", async () => {
  globalThis.fetch = async () => new Response("", { status: 502 });
  await expect(
    request("https://office.invalid", "/office/whatsapp", "test-token"),
  ).rejects.toThrow("office service is offline or restarting");
});

test("HTML gateway errors are not shown as raw proxy content", async () => {
  globalThis.fetch = async () =>
    new Response("<html>Bad Gateway</html>", { status: 502 });
  await expect(
    request("https://office.invalid", "/office/contacts", "test-token"),
  ).rejects.toThrow("Start Office Dashboard");
});

test("successful but truncated JSON has an actionable message", async () => {
  globalThis.fetch = async () => new Response('{"status":', { status: 200 });
  await expect(
    request("https://office.invalid", "/office/whatsapp", "test-token"),
  ).rejects.toThrow("incomplete response");
});

test("empty write response never retries a possibly accepted send", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return new Response("", { status: 502 });
  };
  await expect(
    request("https://office.invalid", "/office/send", "test-token", {
      confirmed: true,
    }),
  ).rejects.toThrow("Check its result");
  expect(calls).toBe(1);
});

test("write connection loss never suggests a blind retry", async () => {
  globalThis.fetch = async () => {
    throw new Error("Network request failed");
  };
  await expect(
    request("https://office.invalid", "/office/send", "test-token", {}),
  ).rejects.toThrow("before confirmation");
});

test("valid JSON and known API rejections keep their original behaviour", async () => {
  globalThis.fetch = async () => Response.json([{ id: "contact" }]);
  expect(
    await request("https://office.invalid", "/office/contacts", "test-token"),
  ).toEqual([{ id: "contact" }]);
  globalThis.fetch = async () =>
    Response.json({ detail: "Choose a party" }, { status: 409 });
  await expect(
    request("https://office.invalid", "/reports", "test-token", {}),
  ).rejects.toThrow("Choose a party");
});
