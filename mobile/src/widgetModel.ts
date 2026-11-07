import { Party, Report } from "./api";
import { OfficeTask, taskDate } from "./taskModel";

export interface WidgetSettings {
  enabled: boolean;
  scope: "mine" | "all";
  party: Party | null;
}
export const defaultWidgetSettings: WidgetSettings = {
  enabled: false, scope: "mine", party: null,
};
export function widgetRoute(url: string | null | undefined): "tasks" | "party" | "setup" | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "hstraders-office:" || parsed.hostname !== "widget" || parsed.username || parsed.password || parsed.port || parsed.search || parsed.hash) return null;
    const route = parsed.pathname.slice(1);
    return route === "tasks" || route === "party" || route === "setup" ? route : null;
  } catch { return null; }
}
export function widgetSnapshot(
  settings: WidgetSettings, userId: string, tasks: OfficeTask[], reports: Report[],
  sessionExpiry: string, now = Date.now(),
) {
  const open = tasks.filter((row) => row.status === "open" &&
    (settings.scope === "all" || row.assignees.includes(userId)) && Number.isFinite(Date.parse(row.due_at)))
    .sort((a, b) => Date.parse(a.due_at) - Date.parse(b.due_at) || a.id.localeCompare(b.id));
  const overdue = open.filter((row) => Date.parse(row.due_at) < now).length;
  const report = reports.filter((row) => row.party_id === settings.party?.id && row.status === "ready" &&
    row.details && Number.isFinite(Date.parse(row.finished_at ?? "")))
    .sort((a, b) => Date.parse(b.finished_at!) - Date.parse(a.finished_at!))[0];
  const availableUntil = report ? Date.parse(report.finished_at!) + 48 * 3600000 : 0;
  const amount = report?.details?.pending_amount;
  const validAmount = typeof amount === "string" && /^-?\d+(\.\d{1,2})?$/.test(amount) && Number.isFinite(Number(amount));
  const available = availableUntil > now && validAmount;
  return {
    expiresAt: Math.min(Date.parse(sessionExpiry), now + 24 * 3600000),
    taskHeading: settings.scope === "mine" ? "My office tasks" : "Office tasks",
    taskSummary: open.length ? `${open.length} open${overdue ? ` · ${overdue} overdue` : ""}` : "No open tasks",
    tasks: open.slice(0, 3).map((row) => `${row.title.slice(0, 100)}\n${taskDate(row.due_at)}${row.repeat_rule !== "none" ? ` · ${row.repeat_rule}` : ""}`),
    updatedLabel: `Updated ${taskDate(new Date(now).toISOString())}`,
    party: settings.party ? {
      id: settings.party.id, name: settings.party.name.slice(0, 160),
      amount: available ? `₹${Number(amount).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}` : "",
      asOfLabel: available ? `Statement as of ${report.as_of}` : "",
      availableUntil: available ? availableUntil : 0,
    } : null,
  };
}
