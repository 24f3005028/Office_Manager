export interface OfficeTask {
  id: string;
  title: string;
  notes: string;
  due_at: string;
  repeat_rule: "none" | "daily" | "weekly" | "monthly";
  anchor_day: number;
  assignees: string[];
  status: "open" | "done" | "cancelled";
  version: number;
  created_by: string;
  creator_name?: string;
  last_completed_at: string | null;
  completed_by_name?: string;
  completed_count: number;
}
export interface TaskPerson {
  id: string;
  name: string;
}
const INDIA_OFFSET = 330 * 60000;
export function taskDate(value: string): string {
  return new Date(value).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
export function indiaInputs(value: string) {
  const text = new Date(Date.parse(value) + INDIA_OFFSET).toISOString();
  return { date: text.slice(0, 10), time: text.slice(11, 16) };
}
export function taskDue(date: string, time: string): string {
  if (
    !/^\d{4}-\d{2}-\d{2}$/.test(date) ||
    !/^([01]\d|2[0-3]):[0-5]\d$/.test(time)
  )
    throw new Error("Choose a valid date and time.");
  const value = `${date}T${time}:00+05:30`;
  if (
    !Number.isFinite(Date.parse(value)) ||
    indiaInputs(value).date !== date ||
    Number(date.slice(0, 4)) < 2020 ||
    Number(date.slice(0, 4)) > 2099
  )
    throw new Error("Choose a valid date from 2020 through 2099.");
  return value;
}
export function followingDue(task: OfficeTask, current: number): number {
  if (task.repeat_rule === "none") return Number.POSITIVE_INFINITY;
  if (task.repeat_rule === "daily" || task.repeat_rule === "weekly")
    return current + (task.repeat_rule === "daily" ? 1 : 7) * 86400000;
  const india = new Date(current + INDIA_OFFSET);
  const month = india.getUTCMonth() + 1;
  const year = india.getUTCFullYear();
  const day = Math.min(
    task.anchor_day,
    new Date(Date.UTC(year, month + 1, 0)).getUTCDate(),
  );
  return (
    Date.UTC(year, month, day, india.getUTCHours(), india.getUTCMinutes()) -
    INDIA_OFFSET
  );
}
export function reminderPlan(
  tasks: OfficeTask[],
  userId: string,
  now = Date.now(),
) {
  const plan: { id: string; task: OfficeTask; at: number }[] = [];
  for (const task of tasks) {
    if (task.status !== "open" || !task.assignees.includes(userId)) continue;
    let at = Date.parse(task.due_at);
    if (!Number.isFinite(at)) continue;
    // Keep one catch-up notice for this overdue occurrence, then future repeats.
    if (at <= now) plan.push({ id: `${task.id}-${at}`, task, at: now });
    let count = 0;
    while (at <= now && task.repeat_rule !== "none" && count++ < 40000)
      at = followingDue(task, at);
    for (let i = 0; i < 8 && Number.isFinite(at) && at > now; i++) {
      plan.push({ id: `${task.id}-${at}`, task, at });
      at = followingDue(task, at);
    }
  }
  return plan
    .sort((a, b) => a.at - b.at || a.id.localeCompare(b.id))
    .slice(0, 50);
}
