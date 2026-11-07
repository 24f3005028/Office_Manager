import { expect, test } from "bun:test";
import {
  defaultWidgetSettings,
  latestPartyStatement,
  widgetRoute,
  widgetSnapshot,
} from "../src/widgetModel";

const now = Date.parse("2026-11-07T10:00:00Z");
const task = {
  id: "one",
  title: "Follow up",
  status: "open",
  due_at: "2026-11-07T09:00:00Z",
  assignees: ["me"],
  repeat_rule: "weekly",
};
const report = {
  id: "ready",
  party_id: "party-a",
  status: "ready",
  finished_at: "2026-11-07T09:00:00Z",
  as_of: "2026-11-07",
  details: { pending_amount: "123456.78" },
};
const snapshot = (tasks = [], settings = defaultWidgetSettings) =>
  widgetSnapshot(settings, "me", tasks, "2026-12-01T00:00:00Z", now);

test("office tasks populate by default without an enable switch or party selection", () => {
  expect(defaultWidgetSettings).toEqual({ scope: "all" });
  const tasks = [task, { ...task, id: "other", assignees: ["someone"] }];
  expect(snapshot(tasks).taskSummary).toBe("2 open · 2 overdue");
  expect(snapshot(tasks, { scope: "mine" }).taskSummary).toBe(
    "1 open · 1 overdue",
  );
  expect(snapshot(tasks)).not.toHaveProperty("party");
});
test("widget tasks are open, ordered by due date, with bounded rows and lifetime", () => {
  const tasks = Array.from({ length: 40 }, (_, n) => ({
    ...task,
    id: String(n),
  }));
  tasks.push({ ...task, id: "done", title: "Completed", status: "done" });
  expect(snapshot(tasks).tasks).toHaveLength(3);
  expect(snapshot(tasks).tasks.join(" ")).not.toContain("Completed");
  expect(snapshot().expiresAt).toBe(now + 24 * 3600000);
  expect(
    widgetSnapshot({ scope: "all" }, "me", [], "2026-11-07T10:01:00Z", now)
      .expiresAt,
  ).toBe(now + 60000);
  expect(
    snapshot([
      { ...task, title: "Later", due_at: "2026-11-08T09:00:00Z" },
      task,
    ]).tasks[0],
  ).toContain("Follow up");
});
test("party search opens the newest available saved report for exactly the selected party", () => {
  const newer = { ...report, id: "newer", finished_at: "2026-11-07T09:30:00Z" };
  expect(
    latestPartyStatement(
      [report, { ...newer, party_id: "other" }, newer],
      "party-a",
      now,
    )?.id,
  ).toBe("newer");
});
test("expired, failed and incomplete reports cannot become quick-share statements", () => {
  for (const rows of [
    [],
    [{ ...report, finished_at: "2026-11-05T09:00:00Z" }],
    [{ ...report, status: "failed" }],
    [{ ...report, finished_at: null }],
    [{ ...report, details: null }],
    [{ ...report, details: {} }],
    [{ ...report, details: { pending_amount: "Unavailable" } }],
  ]) {
    expect(latestPartyStatement(rows, "party-a", now)).toBeNull();
  }
});
test("an existing running request is reused rather than inviting a duplicate export", () => {
  const pending = {
    ...report,
    id: "running",
    status: "generating",
    finished_at: null,
    details: null,
  };
  expect(latestPartyStatement([report, pending], "party-a", now)?.id).toBe(
    "running",
  );
});
test("only known widget navigation routes are accepted", () => {
  for (const route of ["tasks", "party", "setup"])
    expect(widgetRoute(`hstraders-office://widget/${route}`)).toBe(route);
  for (const url of [
    null,
    undefined,
    "https://widget/tasks",
    "hstraders-office://widget/party?id=secret",
    "hstraders-office://widget/tasks#token",
    "hstraders-office://widget/logout",
  ])
    expect(widgetRoute(url)).toBeNull();
});

test("widget add route is explicit and task actions retain server versions", () => {
  expect(widgetRoute("hstraders-office://widget/new-task")).toBe("new-task");
  expect(widgetRoute("hstraders-office://widget/new-task?complete=1")).toBe(
    null,
  );
  const result = snapshot([
    { ...task, version: 7, notes: "Not needed in the widget" },
  ]);
  expect(result.taskRows[0].version).toBe(7);
  expect(result.taskRows[0]).not.toHaveProperty("notes");
});
