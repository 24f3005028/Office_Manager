import { Report } from "./api";
import { OfficeTask, taskDate } from "./taskModel";

export interface WidgetSettings {
  scope: "mine" | "all";
}
export const defaultWidgetSettings: WidgetSettings = {
  scope: "all",
};
export function widgetRoute(
  url: string | null | undefined,
): "tasks" | "party" | "setup" | "new-task" | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (
      parsed.protocol !== "hstraders-office:" ||
      parsed.hostname !== "widget" ||
      parsed.username ||
      parsed.password ||
      parsed.port ||
      parsed.search ||
      parsed.hash
    )
      return null;
    const route = parsed.pathname.slice(1);
    return route === "tasks" ||
      route === "party" ||
      route === "setup" ||
      route === "new-task"
      ? route
      : null;
  } catch {
    return null;
  }
}
export function widgetSnapshot(
  settings: WidgetSettings,
  userId: string,
  tasks: OfficeTask[],
  sessionExpiry: string,
  now = Date.now(),
) {
  const open = tasks
    .filter(
      (row) =>
        row.status === "open" &&
        (settings.scope === "all" || row.assignees.includes(userId)) &&
        Number.isFinite(Date.parse(row.due_at)),
    )
    .sort(
      (a, b) =>
        Date.parse(a.due_at) - Date.parse(b.due_at) || a.id.localeCompare(b.id),
    );
  const overdue = open.filter((row) => Date.parse(row.due_at) < now).length;
  return {
    expiresAt: Math.min(Date.parse(sessionExpiry), now + 24 * 3600000),
    scope: settings.scope,
    userId,
    taskRows: open
      .slice(0, 3)
      .map(({ id, version, title, due_at, repeat_rule }) => ({
        id,
        version,
        title,
        due_at,
        repeat_rule,
      })),
    taskHeading: settings.scope === "mine" ? "My office tasks" : "Office tasks",
    taskSummary: open.length
      ? `${open.length} open${overdue ? ` · ${overdue} overdue` : ""}`
      : "No open tasks",
    tasks: open
      .slice(0, 3)
      .map(
        (row) =>
          `${row.title.slice(0, 100)}\n${taskDate(row.due_at)}${row.repeat_rule !== "none" ? ` · ${row.repeat_rule}` : ""}`,
      ),
    updatedLabel: `Updated ${taskDate(new Date(now).toISOString())}`,
  };
}

export function latestPartyStatement(
  reports: Report[],
  partyId: string,
  now = Date.now(),
): Report | null {
  const matching = reports.filter((row) => row.party_id === partyId);
  const pending = matching.find((row) =>
    ["queued", "warning", "generating"].includes(row.status),
  );
  if (pending) return pending;
  return (
    matching
      .filter(
        (row) =>
          row.status === "ready" &&
          typeof row.details?.pending_amount === "string" &&
          /^-?\d+(\.\d{1,2})?$/.test(row.details.pending_amount) &&
          Number.isFinite(Number(row.details.pending_amount)) &&
          Number.isFinite(Date.parse(row.finished_at ?? "")) &&
          Date.parse(row.finished_at!) + 48 * 3600000 > now,
      )
      .sort(
        (a, b) => Date.parse(b.finished_at!) - Date.parse(a.finished_at!),
      )[0] ?? null
  );
}
