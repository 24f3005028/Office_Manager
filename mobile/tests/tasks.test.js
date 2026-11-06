import { expect, test } from "bun:test";
import {
  followingDue,
  indiaInputs,
  reminderPlan,
  taskDue,
} from "../src/taskModel";
const task = {
  id: "task",
  title: "Dispatch",
  notes: "",
  due_at: "2027-01-31T18:00:00+05:30",
  repeat_rule: "monthly",
  anchor_day: 31,
  assignees: ["selected"],
  status: "open",
  version: 1,
  created_by: "owner",
  last_completed_at: null,
  completed_count: 0,
};
test("month-end reminders preserve day 31 after February", () => {
  const feb = followingDue(task, Date.parse(task.due_at));
  expect(indiaInputs(new Date(feb).toISOString())).toEqual({
    date: "2027-02-28",
    time: "18:00",
  });
  expect(
    indiaInputs(new Date(followingDue(task, feb)).toISOString()).date,
  ).toBe("2027-03-31");
});
test("only selected recipients get open-task reminders", () => {
  const now = Date.parse("2026-11-06T00:00:00Z");
  expect(reminderPlan([task], "other", now)).toEqual([]);
  expect(reminderPlan([{ ...task, status: "done" }], "selected", now)).toEqual(
    [],
  );
  expect(reminderPlan([task], "selected", now)).toHaveLength(8);
});
test("overdue repeats have one catch-up plus future dates and stable identifiers", () => {
  const old = { ...task, due_at: "2026-01-31T18:00:00+05:30" };
  const now = Date.parse("2026-11-06T10:00:00Z");
  const plan = reminderPlan([old], "selected", now);
  expect(plan.filter((row) => row.at === now)).toHaveLength(1);
  expect(indiaInputs(new Date(plan[1].at).toISOString()).date).toBe(
    "2026-11-30",
  );
  expect(reminderPlan([old], "selected", now + 1000)[0].id).toBe(plan[0].id);
});
test("invalid calendar dates and times cannot become different deadlines", () => {
  expect(() => taskDue("2026-02-30", "18:00")).toThrow();
  expect(() => taskDue("2026-11-06", "25:00")).toThrow();
  expect(taskDue("2026-11-06", "18:00")).toBe("2026-11-06T18:00:00+05:30");
});
test("notification plan stays bounded across many tasks", () => {
  const tasks = Array.from({ length: 200 }, (_, i) => ({
    ...task,
    id: `task-${i}`,
  }));
  expect(
    reminderPlan(tasks, "selected", Date.parse("2026-11-06T00:00:00Z")),
  ).toHaveLength(50);
});
