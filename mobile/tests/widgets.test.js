import { expect, test } from "bun:test";
import { widgetRoute, widgetSnapshot } from "../src/widgetModel";

const now = Date.parse("2026-11-07T10:00:00Z");
const settings = { enabled: true, scope: "mine", party: { id: "party-a", name: "Test Party" } };
const task = { id: "one", title: "Follow up", status: "open", due_at: "2026-11-07T09:00:00Z", assignees: ["me"], repeat_rule: "weekly" };
const report = { id: "ready", party_id: "party-a", status: "ready", finished_at: "2026-11-07T09:00:00Z", as_of: "2026-11-07", details: { pending_amount: "123456.78" } };
function snapshot(tasks = [], reports = [], config = settings) {
  return widgetSnapshot(config, "me", tasks, reports, "2026-12-01T00:00:00Z", now);
}
test("widgets show only assigned open tasks by default, ordered by due date", () => {
  const data = snapshot([task, { ...task, id: "other", assignees: ["someone"] }, { ...task, id: "done", status: "done" },
    { ...task, id: "next", title: "Next", due_at: "2026-11-08T09:00:00Z" }]);
  expect(data.taskSummary).toBe("2 open · 1 overdue");
  expect(data.tasks[0]).toContain("Follow up");
  expect(data.tasks[0]).toContain("weekly");
  expect(data.tasks[1]).toContain("Next");
  expect(data.tasks.join(" ")).not.toContain("someone");
  expect(snapshot([task, { ...task, id: "other", assignees: ["someone"] }], [], { ...settings, scope: "all" }).taskSummary).toBe("2 open · 2 overdue");
});
test("party balance comes only from the selected party's most recently completed ready report", () => {
  const data = snapshot([], [report, { ...report, id: "wrong", party_id: "party-b", details: { pending_amount: "999" } },
    { ...report, id: "failed", status: "failed", finished_at: "2026-11-07T09:30:00Z" }]);
  expect(data.party.name).toBe("Test Party");
  expect(data.party.amount).toBe("₹1,23,456.78");
  expect(data.party.asOfLabel).toBe("Statement as of 2026-11-07");
  expect(data.party.availableUntil).toBe(Date.parse(report.finished_at) + 48 * 3600000);
});
test("expired, invalid and absent reports never display a guessed outstanding balance", () => {
  for (const reports of [[], [{ ...report, finished_at: "2026-11-05T09:00:00Z" }],
    [{ ...report, details: { pending_amount: "Not available" } }], [{ ...report, finished_at: null }]]) {
    expect(snapshot([], reports).party.amount).toBe("");
    expect(snapshot([], reports).party.availableUntil).toBe(0);
  }
  expect(snapshot([], [report], { ...settings, party: null }).party).toBeNull();
});
test("snapshot lifetime is bounded by access expiry and 24 hours, with at most three task rows", () => {
  const tasks = Array.from({ length: 40 }, (_, n) => ({ ...task, id: String(n) }));
  expect(snapshot(tasks).tasks).toHaveLength(3);
  expect(snapshot().expiresAt).toBe(now + 24 * 3600000);
  expect(widgetSnapshot(settings, "me", [], [], "2026-11-07T10:01:00Z", now).expiresAt).toBe(now + 60000);
});
test("only the three known widget deep links navigate, without accepting arbitrary queries or IDs", () => {
  expect(widgetRoute("hstraders-office://widget/tasks")).toBe("tasks");
  expect(widgetRoute("hstraders-office://widget/party")).toBe("party");
  expect(widgetRoute("hstraders-office://widget/setup")).toBe("setup");
  for (const url of [null, undefined, "https://widget/tasks", "hstraders-office://widget/party?id=secret", "hstraders-office://widget/tasks#token", "hstraders-office://widget/logout"]) expect(widgetRoute(url)).toBeNull();
});
