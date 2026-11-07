import { afterEach, expect, mock, test } from "bun:test";

const values = new Map();
const snapshots = [];
const connections = [];
const calls = [];
let clears = 0,
  registered = false,
  worker;
let existingWidget = false,
  pinCalls = 0;
const originalFetch = globalThis.fetch;
mock.module("react-native", () => ({ Platform: { OS: "android" } }));
mock.module("expo", () => ({
  requireOptionalNativeModule: () => ({
    saveSnapshot: async (value, connection) => {
      connections.push(JSON.parse(connection));
      snapshots.push(JSON.parse(value));
    },
    clearSnapshot: async () => {
      clears++;
    },
    pin: async () => {
      pinCalls++;
      return true;
    },
    hasWidgets: async () => existingWidget,
  }),
}));
mock.module("expo-secure-store", () => ({
  getItemAsync: async (key) => values.get(key) ?? null,
  setItemAsync: async (key, value) => values.set(key, value),
  deleteItemAsync: async (key) => values.delete(key),
}));
mock.module("expo-task-manager", () => ({
  defineTask: (_, fn) => {
    worker = fn;
  },
  isTaskRegisteredAsync: async () => registered,
}));
mock.module("expo-background-task", () => ({
  BackgroundTaskResult: { Success: 1, Failed: 2 },
  registerTaskAsync: async () => {
    registered = true;
  },
  unregisterTaskAsync: async () => {
    registered = false;
  },
}));
const {
  clearHomeWidgets,
  refreshHomeWidgets,
  saveWidgetSettings,
  pinHomeWidget,
  widgetSettings,
} = await import("../src/homeWidgets");
const config = { scope: "mine" };
function setup() {
  values.set("office-home-widgets-v1", JSON.stringify(config));
  values.set(
    "office-session-v1",
    JSON.stringify({
      url: "https://office.invalid",
      token: "private-test-token",
      expires_at: "2099-01-01",
    }),
  );
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options.method });
    return Response.json(String(url).endsWith("/me") ? { id: "me" } : []);
  };
}
afterEach(async () => {
  await clearHomeWidgets();
  values.clear();
  snapshots.length = 0;
  connections.length = 0;
  calls.length = 0;
  clears = 0;
  existingWidget = false;
  pinCalls = 0;
  globalThis.fetch = originalFetch;
});
test("widget background refresh makes only authenticated reads and never requests BUSY or WhatsApp", async () => {
  setup();
  await saveWidgetSettings(config);
  expect(registered).toBe(true);
  expect(await worker()).toBe(1);
  expect(calls.every((call) => call.method === "GET")).toBe(true);
  expect(
    calls.map((call) =>
      call.url.replace("https://office.invalid/mobile/v1", ""),
    ),
  ).toEqual(["/me", "/tasks", "/me", "/tasks"]);
  expect(JSON.stringify(snapshots)).not.toContain("private-test-token");
  expect(connections.at(-1).url).toBe("https://office.invalid");
  expect(connections.at(-1).token).toBe("private-test-token");
});
test("expired or revoked access clears displayed data and stops widget reads", async () => {
  setup();
  values.set("office-session-v1", JSON.stringify({ expires_at: "2000-01-01" }));
  await refreshHomeWidgets();
  expect(clears).toBe(1);
  expect(calls).toHaveLength(0);
  setup();
  globalThis.fetch = async () =>
    Response.json(
      { detail: "Access expired or was revoked." },
      { status: 401 },
    );
  await expect(refreshHomeWidgets()).rejects.toThrow("Access expired");
  expect(snapshots).toHaveLength(0);
  expect(values.has("office-home-widgets-v1")).toBe(false);
});
test("offline reads preserve the last snapshot rather than replacing it with a zero balance", async () => {
  setup();
  await refreshHomeWidgets();
  globalThis.fetch = async () => {
    throw new Error("Network request failed");
  };
  await expect(refreshHomeWidgets()).rejects.toThrow("Cannot reach the office");
  expect(snapshots).toHaveLength(1);
  expect(clears).toBe(0);
});
test("malformed local access data clears widgets without contacting the office", async () => {
  setup();
  values.set("office-session-v1", "broken");
  await refreshHomeWidgets();
  expect(clears).toBe(1);
  expect(calls).toHaveLength(0);
});
test("logout during a slow request cannot republish the previous account's data", async () => {
  setup();
  let release;
  const paused = new Promise((resolve) => {
    release = resolve;
  });
  globalThis.fetch = async (url) => {
    if (String(url).endsWith("/me")) await paused;
    return Response.json(String(url).endsWith("/me") ? { id: "me" } : []);
  };
  const pending = refreshHomeWidgets();
  await new Promise((resolve) => setTimeout(resolve, 5));
  await clearHomeWidgets();
  values.delete("office-session-v1");
  release();
  await pending;
  expect(snapshots).toHaveLength(0);
});
test("simultaneous foreground and background refreshes share one read", async () => {
  setup();
  await Promise.all([
    refreshHomeWidgets(),
    refreshHomeWidgets(),
    refreshHomeWidgets(),
  ]);
  expect(calls).toHaveLength(2);
  expect(snapshots).toHaveLength(1);
});
test("a task change waits for an older read then fetches fresh data", async () => {
  setup();
  const older = refreshHomeWidgets();
  const changed = refreshHomeWidgets(true);
  await Promise.all([older, changed]);
  expect(calls).toHaveLength(4);
  expect(snapshots).toHaveLength(2);
});
test("reconfiguring an existing widget updates it without prompting for a duplicate", async () => {
  existingWidget = true;
  expect(await pinHomeWidget("party")).toBe("updated");
  expect(pinCalls).toBe(0);
  existingWidget = false;
  expect(await pinHomeWidget("party")).toBe("requested");
  expect(pinCalls).toBe(1);
});
test("an old account's late revocation response does not clear a newly paired account", async () => {
  setup();
  let release;
  const paused = new Promise((resolve) => {
    release = resolve;
  });
  globalThis.fetch = async () => {
    await paused;
    return Response.json(
      { detail: "Access expired or was revoked." },
      { status: 401 },
    );
  };
  const pending = refreshHomeWidgets();
  await new Promise((resolve) => setTimeout(resolve, 5));
  values.set(
    "office-session-v1",
    JSON.stringify({ token: "different-account", expires_at: "2099-01-01" }),
  );
  release();
  await expect(pending).rejects.toThrow("Access expired");
  expect(clears).toBe(0);
  expect(values.has("office-home-widgets-v1")).toBe(true);
});
test("a signed-in phone loads all office tasks without any saved widget settings", async () => {
  setup();
  values.delete("office-home-widgets-v1");
  await refreshHomeWidgets();
  expect(registered).toBe(true);
  expect(snapshots[0].taskHeading).toBe("Office tasks");
  expect(calls).toHaveLength(2);
});
test("unused legacy setup and fixed-party preferences are removed automatically", async () => {
  setup();
  for (const enabled of [false, true]) {
    values.set(
      "office-home-widgets-v1",
      JSON.stringify({
        enabled,
        scope: "mine",
        party: { id: "old", name: "Old choice" },
      }),
    );
    expect(await widgetSettings()).toEqual({ scope: "all" });
    expect(JSON.parse(values.get("office-home-widgets-v1"))).toEqual({
      scope: "all",
    });
  }
});
