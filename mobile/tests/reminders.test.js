import { afterEach, expect, mock, test } from "bun:test";
const values = new Map();
const scheduled = new Map();
const calls = [];
let worker;
let registered = false;
let tasks = [];
const originalFetch = globalThis.fetch;
mock.module("react-native", () => ({ Platform: { OS: "android" } }));
mock.module("expo-secure-store", () => ({
  getItemAsync: async (key) => values.get(key) ?? null,
  setItemAsync: async (key, value) => values.set(key, value),
  deleteItemAsync: async (key) => values.delete(key),
}));
mock.module("expo-task-manager", () => ({
  defineTask: (_, fn) => (worker = fn),
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
mock.module("expo-notifications", () => ({
  setNotificationHandler: () => {},
  getPermissionsAsync: async () => ({ granted: true }),
  requestPermissionsAsync: async () => ({ granted: true }),
  setNotificationChannelAsync: async () => {},
  getAllScheduledNotificationsAsync: async () => [...scheduled.values()],
  cancelScheduledNotificationAsync: async (id) => scheduled.delete(id),
  scheduleNotificationAsync: async (row) => {
    scheduled.set(row.identifier, row);
    return row.identifier;
  },
  dismissAllNotificationsAsync: async () => {},
  AndroidImportance: { DEFAULT: 3 },
  AndroidNotificationVisibility: { PRIVATE: 0 },
  SchedulableTriggerInputTypes: { DATE: "date" },
}));
const {
  enableTaskReminders,
  stopTaskReminders,
  syncTaskReminders,
  testTaskReminder,
} = await import("../src/taskReminders");
afterEach(async () => {
  await stopTaskReminders();
  values.clear();
  scheduled.clear();
  tasks = [];
  calls.length = 0;
  globalThis.fetch = originalFetch;
});
function setup() {
  values.set(
    "office-session-v1",
    JSON.stringify({
      url: "https://office.invalid",
      token: "test-only",
      expires_at: "2099-01-01",
    }),
  );
  globalThis.fetch = async (url, options) => {
    calls.push({ url, method: options.method });
    return Response.json(String(url).endsWith("/me") ? { id: "me" } : tasks);
  };
  tasks = [
    {
      id: "task1",
      title: "Dispatch",
      due_at: "2030-01-01T18:00:00+05:30",
      repeat_rule: "none",
      anchor_day: 1,
      assignees: ["me"],
      status: "open",
      version: 1,
    },
  ];
}
test("background reminders read only task data and schedule only selected users", async () => {
  setup();
  tasks.push({ ...tasks[0], id: "other-task", assignees: ["other"] });
  await enableTaskReminders();
  expect(registered).toBe(true);
  expect(scheduled.size).toBe(1);
  expect(await worker()).toBe(1);
  expect(
    calls.every(
      (call) => call.method === "GET" && /\/(me|tasks)$/.test(call.url),
    ),
  ).toBe(true);
});
test("refresh updates reminders and completion cancels them without duplicates", async () => {
  setup();
  await enableTaskReminders();
  await syncTaskReminders();
  expect(scheduled.size).toBe(1);
  tasks[0] = { ...tasks[0], title: "New title", version: 2 };
  await syncTaskReminders();
  expect([...scheduled.values()][0].content.body).toBe("New title");
  tasks[0] = { ...tasks[0], status: "done", version: 3 };
  await syncTaskReminders();
  expect(scheduled.size).toBe(0);
});
test("turning reminders off clears schedules and unregisters background reads", async () => {
  setup();
  await enableTaskReminders();
  await stopTaskReminders();
  expect(registered).toBe(false);
  expect(scheduled.size).toBe(0);
  const before = calls.length;
  await syncTaskReminders();
  expect(calls.length).toBe(before);
});
test("session expiry removes previously scheduled reminders without contacting the office", async () => {
  setup();
  await enableTaskReminders();
  values.set(
    "office-session-v1",
    JSON.stringify({
      url: "https://office.invalid",
      token: "test-only",
      expires_at: "2020-01-01",
    }),
  );
  const before = calls.length;
  await syncTaskReminders();
  expect(scheduled.size).toBe(0);
  expect(registered).toBe(false);
  expect(calls.length).toBe(before);
});
test("ordinary refresh does not cancel the pending test notification", async () => {
  setup();
  await enableTaskReminders();
  await testTaskReminder();
  await syncTaskReminders();
  expect(scheduled.has("office-task-test")).toBe(true);
});
test("revoked access clears reminders and stops the background reader", async () => {
  setup();
  await enableTaskReminders();
  globalThis.fetch = async () =>
    Response.json(
      {
        detail:
          "Access expired or was revoked. Ask the office for a new invite.",
      },
      { status: 401 },
    );
  await expect(syncTaskReminders()).rejects.toThrow("Access expired");
  expect(scheduled.size).toBe(0);
  expect(registered).toBe(false);
});
