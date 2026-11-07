import { Platform } from "react-native";
import { requireOptionalNativeModule } from "expo";
import * as SecureStore from "expo-secure-store";
import * as BackgroundTask from "expo-background-task";
import * as TaskManager from "expo-task-manager";
import { Person, Session, request } from "./api";
import { OfficeTask } from "./taskModel";
import {
  defaultWidgetSettings,
  WidgetSettings,
  widgetSnapshot,
} from "./widgetModel";

const KEY = "office-home-widgets-v1";
const SESSION = "office-session-v1";
const WORKER = "office-home-widgets-read-v1";
type Bridge = {
  saveSnapshot: (data: string, connection: string) => Promise<void>;
  clearSnapshot: () => Promise<void>;
  pin: (kind: "tasks" | "party") => Promise<boolean>;
  hasWidgets: (kind: "tasks" | "party") => Promise<boolean>;
};
const bridge =
  Platform.OS === "android"
    ? requireOptionalNativeModule<Bridge>("OfficeWidgets")
    : null;
export const widgetsAvailable = Boolean(bridge);
let revision = 0;
let syncing: Promise<void> | null = null;

export async function widgetSettings(): Promise<WidgetSettings> {
  if (!bridge) return { ...defaultWidgetSettings };
  try {
    const raw = JSON.parse((await SecureStore.getItemAsync(KEY)) ?? "null");
    const legacy = raw && ("party" in raw || "enabled" in raw);
    const settings: WidgetSettings = {
      scope: !legacy && raw?.scope === "mine" ? "mine" : "all",
    };
    if (legacy) await SecureStore.setItemAsync(KEY, JSON.stringify(settings));
    return settings;
  } catch {
    return { ...defaultWidgetSettings };
  }
}
export async function saveWidgetSettings(settings: WidgetSettings) {
  if (!bridge) throw new Error("Home widgets require the updated Android APK.");
  const previous = await widgetSettings();
  revision++;
  await SecureStore.setItemAsync(KEY, JSON.stringify(settings));
  if (previous.scope !== settings.scope) await bridge.clearSnapshot();
  if (syncing) await syncing.catch(() => {});
  await refreshHomeWidgets();
}
export async function clearHomeWidgets() {
  revision++;
  if (!bridge) return;
  await SecureStore.deleteItemAsync(KEY);
  await bridge.clearSnapshot();
  if (await TaskManager.isTaskRegisteredAsync(WORKER))
    await BackgroundTask.unregisterTaskAsync(WORKER);
}
async function reconcile() {
  if (!bridge) return;
  const startRevision = revision;
  const settings = await widgetSettings();
  const raw = await SecureStore.getItemAsync(SESSION);
  let session: Session | null = null;
  try {
    session = raw ? JSON.parse(raw) : null;
  } catch {
    await clearHomeWidgets();
    return;
  }
  if (
    !session ||
    !Number.isFinite(Date.parse(session.expires_at)) ||
    Date.parse(session.expires_at) <= Date.now()
  ) {
    await clearHomeWidgets();
    return;
  }
  if (!(await TaskManager.isTaskRegisteredAsync(WORKER)))
    await BackgroundTask.registerTaskAsync(WORKER, { minimumInterval: 15 });
  try {
    const user = await request<Person>(session.url, "/me", session.token);
    const tasks = await request<OfficeTask[]>(
      session.url,
      "/tasks",
      session.token,
    );
    const currentRaw = await SecureStore.getItemAsync(SESSION);
    if (revision !== startRevision || currentRaw !== raw)
      return;
    await bridge.saveSnapshot(
      JSON.stringify(
        widgetSnapshot(settings, user.id, tasks, session.expires_at),
      ),
      JSON.stringify({
        url: session.url,
        token: session.token,
        expiresAt: Date.parse(session.expires_at),
      }),
    );
  } catch (error) {
    if (
      error instanceof Error &&
      /Access expired or was revoked/.test(error.message) &&
      revision === startRevision &&
      (await SecureStore.getItemAsync(SESSION)) === raw
    )
      await clearHomeWidgets();
    throw error;
  }
}
export function refreshHomeWidgets(afterTaskChange = false): Promise<void> {
  if (syncing)
    return afterTaskChange
      ? syncing.catch(() => {}).then(() => refreshHomeWidgets())
      : syncing;
  syncing = reconcile().finally(() => {
    syncing = null;
  });
  return syncing;
}
export async function pinHomeWidget(kind: "tasks" | "party") {
  if (!bridge) throw new Error("Home widgets require the updated Android APK.");
  if (kind === "tasks") void refreshHomeWidgets().catch(() => {});
  if (await bridge.hasWidgets(kind)) return "updated";
  return (await bridge.pin(kind)) ? "requested" : "manual";
}
if (Platform.OS === "android") {
  TaskManager.defineTask(WORKER, async () => {
    try {
      await refreshHomeWidgets();
      return BackgroundTask.BackgroundTaskResult.Success;
    } catch {
      return BackgroundTask.BackgroundTaskResult.Failed;
    }
  });
}
