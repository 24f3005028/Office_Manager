import { Platform } from "react-native";
import { requireOptionalNativeModule } from "expo";
import * as SecureStore from "expo-secure-store";
import * as BackgroundTask from "expo-background-task";
import * as TaskManager from "expo-task-manager";
import { Person, Report, Session, request } from "./api";
import { OfficeTask } from "./taskModel";
import { defaultWidgetSettings, WidgetSettings, widgetSnapshot } from "./widgetModel";

const KEY = "office-home-widgets-v1";
const SESSION = "office-session-v1";
const WORKER = "office-home-widgets-read-v1";
type Bridge = {
  saveSnapshot: (data: string) => Promise<void>;
  clearSnapshot: () => Promise<void>;
  pin: (kind: "tasks" | "party") => Promise<boolean>;
  hasWidgets: (kind: "tasks" | "party") => Promise<boolean>;
};
const bridge = Platform.OS === "android" ? requireOptionalNativeModule<Bridge>("OfficeWidgets") : null;
export const widgetsAvailable = Boolean(bridge);
let revision = 0;
let syncing: Promise<void> | null = null;

export async function widgetSettings(): Promise<WidgetSettings> {
  if (!bridge) return { ...defaultWidgetSettings };
  try {
    const raw = JSON.parse((await SecureStore.getItemAsync(KEY)) ?? "null");
    return {
      enabled: raw?.enabled === true,
      scope: raw?.scope === "all" ? "all" : "mine",
      party: typeof raw?.party?.id === "string" && typeof raw.party.name === "string" ? raw.party : null,
    };
  } catch { return { ...defaultWidgetSettings }; }
}
export async function saveWidgetSettings(settings: WidgetSettings) {
  if (!bridge) throw new Error("Home widgets require the updated Android APK.");
  const previous = await widgetSettings();
  revision++;
  await SecureStore.setItemAsync(KEY, JSON.stringify(settings));
  // Remove the previous party immediately, even when the office is offline.
  if (!settings.enabled || previous.party?.id !== settings.party?.id || previous.scope !== settings.scope)
    await bridge.clearSnapshot();
  if (settings.enabled) {
    await BackgroundTask.registerTaskAsync(WORKER, { minimumInterval: 15 });
    // Let an older settings revision finish; its response cannot overwrite this one.
    if (syncing) await syncing.catch(() => {});
    await refreshHomeWidgets();
  } else if (await TaskManager.isTaskRegisteredAsync(WORKER)) {
    await BackgroundTask.unregisterTaskAsync(WORKER);
  }
}
export async function clearHomeWidgets() {
  revision++;
  if (!bridge) return;
  await SecureStore.deleteItemAsync(KEY);
  await bridge.clearSnapshot();
  if (await TaskManager.isTaskRegisteredAsync(WORKER)) await BackgroundTask.unregisterTaskAsync(WORKER);
}
async function reconcile() {
  if (!bridge) return;
  const startRevision = revision;
  const settings = await widgetSettings();
  if (!settings.enabled) return;
  const raw = await SecureStore.getItemAsync(SESSION);
  let session: Session | null = null;
  try { session = raw ? JSON.parse(raw) : null; } catch {
    await clearHomeWidgets();
    return;
  }
  if (!session || !Number.isFinite(Date.parse(session.expires_at)) || Date.parse(session.expires_at) <= Date.now()) {
    await clearHomeWidgets();
    return;
  }
  try {
    const user = await request<Person>(session.url, "/me", session.token);
    const [tasks, reports] = await Promise.all([
      request<OfficeTask[]>(session.url, "/tasks", session.token),
      request<Report[]>(session.url, "/reports", session.token),
    ]);
    if (revision !== startRevision || await SecureStore.getItemAsync(SESSION) !== raw) return;
    await bridge.saveSnapshot(JSON.stringify(widgetSnapshot(settings, user.id, tasks, reports, session.expires_at)));
  } catch (error) {
    if (error instanceof Error && /Access expired or was revoked/.test(error.message) &&
      revision === startRevision && await SecureStore.getItemAsync(SESSION) === raw) await clearHomeWidgets();
    throw error;
  }
}
export function refreshHomeWidgets(): Promise<void> {
  if (syncing) return syncing;
  syncing = reconcile().finally(() => { syncing = null; });
  return syncing;
}
export async function pinHomeWidget(kind: "tasks" | "party") {
  if (!bridge) throw new Error("Home widgets require the updated Android APK.");
  if (await bridge.hasWidgets(kind)) return "updated";
  return await bridge.pin(kind) ? "requested" : "manual";
}
if (Platform.OS === "android") {
  TaskManager.defineTask(WORKER, async () => {
    try {
      await refreshHomeWidgets();
      return BackgroundTask.BackgroundTaskResult.Success;
    } catch { return BackgroundTask.BackgroundTaskResult.Failed; }
  });
}
