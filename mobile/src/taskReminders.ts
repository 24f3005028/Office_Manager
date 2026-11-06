import { Platform } from "react-native";
import * as BackgroundTask from "expo-background-task";
import * as TaskManager from "expo-task-manager";
import * as Notifications from "expo-notifications";
import * as SecureStore from "expo-secure-store";
import { Person, request, Session } from "./api";
import { OfficeTask, reminderPlan } from "./taskModel";

const WORKER = "office-shared-task-reminders-v1";
const ENABLED = "office-task-reminders-enabled";
const CHANNEL = "office-tasks";
const PREFIX = "office-task-";
export const SESSION_KEY = "office-session-v1";
if (Platform.OS !== "web") {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldPlaySound: true,
      shouldSetBadge: false,
      shouldShowBanner: true,
      shouldShowList: true,
    }),
  });
  TaskManager.defineTask(WORKER, async () => {
    try {
      await syncTaskReminders();
      return BackgroundTask.BackgroundTaskResult.Success;
    } catch {
      return BackgroundTask.BackgroundTaskResult.Failed;
    }
  });
}

let syncing: Promise<void> | null = null;
export async function syncTaskReminders(): Promise<void> {
  if (Platform.OS === "web") return;
  if (syncing) return syncing;
  syncing = reconcile().finally(() => {
    syncing = null;
  });
  return syncing;
}
async function reconcile() {
  if ((await SecureStore.getItemAsync(ENABLED)) !== "yes") return;
  const raw = await SecureStore.getItemAsync(SESSION_KEY);
  if (!raw) {
    await stopTaskReminders();
    return;
  }
  const session: Session = JSON.parse(raw);
  if (Date.parse(session.expires_at) <= Date.now()) {
    await stopTaskReminders();
    return;
  }
  if (!(await Notifications.getPermissionsAsync()).granted) return;
  let user: Person, tasks: OfficeTask[];
  try {
    user = await request<Person>(session.url, "/me", session.token);
    tasks = await request<OfficeTask[]>(session.url, "/tasks", session.token);
  } catch (error) {
    if (
      error instanceof Error &&
      /Access expired or was revoked/.test(error.message)
    )
      await stopTaskReminders();
    throw error;
  }
  const plan = reminderPlan(tasks, user.id).filter(
    (row) => row.at < Date.parse(session.expires_at),
  );
  const planned = new Set(plan.map((row) => PREFIX + row.id));
  const scheduled = await Notifications.getAllScheduledNotificationsAsync();
  for (const item of scheduled)
    if (
      item.identifier.startsWith(PREFIX) &&
      item.identifier !== PREFIX + "test" &&
      !planned.has(item.identifier)
    )
      await Notifications.cancelScheduledNotificationAsync(item.identifier);
  const existing = new Map(scheduled.map((item) => [item.identifier, item]));
  const markerKey = `task-notices-${user.id}`;
  const seen: Record<string, number> = JSON.parse(
    (await SecureStore.getItemAsync(markerKey)) ?? "{}",
  );
  for (const row of plan) {
    const identifier = PREFIX + row.id;
    const old = existing.get(identifier);
    if (seen[row.id] && !old && row.at <= Date.now()) continue;
    if (old && old.content.data?.revision === row.task.version) continue;
    if (old) await Notifications.cancelScheduledNotificationAsync(identifier);
    const immediate = row.at <= Date.now();
    await Notifications.scheduleNotificationAsync({
      identifier,
      content: {
        title: "Office task due",
        body: row.task.title,
        sound: "default",
        data: { taskId: row.task.id, revision: row.task.version },
        ...(Platform.OS === "android"
          ? { visibility: Notifications.AndroidNotificationVisibility.PRIVATE }
          : {}),
      },
      trigger: immediate
        ? { channelId: CHANNEL }
        : {
            type: Notifications.SchedulableTriggerInputTypes.DATE,
            date: row.at,
            channelId: CHANNEL,
            delivery: "bestEffort",
          },
    });
    seen[row.id] = row.at;
    await SecureStore.setItemAsync(markerKey, JSON.stringify(seen));
  }
  // Expire old catch-up markers after a year; only selected recipients are stored.
  for (const [key, value] of Object.entries(seen))
    if (value < Date.now() - 366 * 86400000) delete seen[key];
  await SecureStore.setItemAsync(markerKey, JSON.stringify(seen));
}
export async function enableTaskReminders(): Promise<string> {
  if (Platform.OS === "web")
    return "Phone reminders are available in the Android app.";
  await Notifications.setNotificationChannelAsync(CHANNEL, {
    name: "Office tasks",
    importance: Notifications.AndroidImportance.DEFAULT,
    lockscreenVisibility: Notifications.AndroidNotificationVisibility.PRIVATE,
  });
  const permission = await Notifications.requestPermissionsAsync();
  if (!permission.granted)
    throw new Error(
      "Notifications are off. Allow notifications for H.S. Traders Office in Android Settings.",
    );
  await SecureStore.setItemAsync(ENABLED, "yes");
  await BackgroundTask.registerTaskAsync(WORKER, { minimumInterval: 15 });
  await syncTaskReminders();
  return "Reminders enabled on this phone. Background changes can take 15 minutes or longer to sync.";
}
export async function stopTaskReminders() {
  if (Platform.OS === "web") return;
  await SecureStore.deleteItemAsync(ENABLED);
  if (await TaskManager.isTaskRegisteredAsync(WORKER))
    await BackgroundTask.unregisterTaskAsync(WORKER);
  for (const item of await Notifications.getAllScheduledNotificationsAsync())
    if (item.identifier.startsWith(PREFIX))
      await Notifications.cancelScheduledNotificationAsync(item.identifier);
  await Notifications.dismissAllNotificationsAsync();
}
export async function testTaskReminder() {
  if (!(await reminderStatus()))
    throw new Error("Enable phone reminders first.");
  await Notifications.scheduleNotificationAsync({
    identifier: PREFIX + "test",
    content: {
      title: "Office reminders are working",
      body: "This is a test reminder on your phone.",
      data: { taskId: "test" },
    },
    trigger: {
      type: Notifications.SchedulableTriggerInputTypes.DATE,
      date: Date.now() + 5000,
      channelId: CHANNEL,
      delivery: "bestEffort",
    },
  });
}
export async function reminderStatus(): Promise<boolean> {
  return (
    Platform.OS !== "web" &&
    (await SecureStore.getItemAsync(ENABLED)) === "yes" &&
    (await Notifications.getPermissionsAsync()).granted
  );
}
