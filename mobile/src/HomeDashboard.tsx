import { ReactNode, useCallback, useEffect, useState } from "react";
import {
  AppState,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { Person } from "./api";
import { NavigationScreen } from "./NavigationDrawer";
import { OfficeTask } from "./taskModel";
import { Icon, Logo, palette, styles, TaskTile } from "./ui";

export default function HomeDashboard({
  person,
  api,
  onOpen,
  disabled,
  children,
}: {
  person: Person | null;
  api: <T>(path: string, body?: unknown) => Promise<T>;
  onOpen: (screen: NavigationScreen) => void;
  disabled: boolean;
  children: ReactNode;
}) {
  const [tasks, setTasks] = useState<OfficeTask[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      setTasks(await api<OfficeTask[]>("/tasks"));
      setUnavailable(false);
    } catch {
      setUnavailable(true);
    } finally {
      setRefreshing(false);
    }
  }, [api]);
  useEffect(() => {
    void refresh();
    const listener = AppState.addEventListener("change", (state) => {
      if (state === "active") void refresh();
    });
    return () => listener.remove();
  }, [refresh]);
  const open = tasks?.filter((task) => task.status === "open");
  const overdue = open?.filter(
    (task) => Date.parse(task.due_at) < Date.now(),
  ).length;
  return (
    <ScrollView
      contentContainerStyle={styles.content}
      refreshControl={
        <RefreshControl
          refreshing={refreshing}
          onRefresh={() => void refresh()}
          tintColor={palette.blue}
        />
      }
    >
      <View style={[styles.row, { justifyContent: "space-between" }]}>
        <View style={styles.grow}>
          <Text style={styles.eyebrow}>
            {new Date().toLocaleDateString("en-IN", {
              weekday: "long",
              day: "numeric",
              month: "short",
              timeZone: "Asia/Kolkata",
            })}
          </Text>
          <Text
            accessibilityRole="header"
            style={[styles.title, { marginTop: 8 }]}
          >
            Hello{person ? `, ${person.name.split(" ")[0]}` : ""}
          </Text>
        </View>
        <Logo />
      </View>
      <Pressable
        accessibilityRole="button"
        disabled={disabled}
        accessibilityLabel="Open office tasks"
        onPress={() => onOpen("tasks")}
        style={({ pressed }) => [local.summary, pressed && styles.pressed]}
      >
        <View style={styles.sectionHead}>
          <Text style={local.summaryLabel}>OFFICE TASKS</Text>
          <Icon name="arrow" color="white" size={21} />
        </View>
        <Text style={local.summaryNumber}>
          {unavailable
            ? "Check connection"
            : open
              ? `${open.length} open`
              : "Loading tasks…"}
        </Text>
        <Text style={local.summaryCopy}>
          {unavailable
            ? "Pull down to retry"
            : overdue
              ? `${overdue} overdue · Review your team’s work`
              : open?.length === 0
                ? "You’re all caught up"
                : "Keep your team’s work moving"}
        </Text>
      </Pressable>
      <Text style={styles.sectionTitle}>Quick actions</Text>
      <View style={{ flexDirection: "row", gap: 12 }}>
        {(
          [
            ["outstanding", "statement", "Party statement", "Pending bills"],
            ["invoices", "search", "Find a bill", "Search bill number"],
          ] as const
        ).map(([key, icon, title, copy]) => (
          <Pressable
            key={key}
            accessibilityRole="button"
            disabled={disabled}
            onPress={() => onOpen(key)}
            style={({ pressed }) => [local.quick, pressed && styles.pressed]}
          >
            <View style={styles.tileIcon}>
              <Icon name={icon} size={24} />
            </View>
            <Text style={local.quickTitle}>{title}</Text>
            <Text style={styles.noteText}>{copy}</Text>
          </Pressable>
        ))}
      </View>
      <Text style={styles.sectionTitle}>Office</Text>
      <View style={{ gap: 10 }}>
        <TaskTile
          title="All outstanding"
          subtitle="Every party, in one report"
          icon="statement"
          disabled={disabled}
          onPress={() => onOpen("allOutstanding")}
        />
        <TaskTile
          title="Update sheet & send bills"
          subtitle="Pouncha and WhatsApp"
          icon="calendar"
          disabled={disabled}
          onPress={() => onOpen("tools")}
        />
        <TaskTile
          title="Copy account & balances"
          subtitle="Party ledgers and account groups"
          icon="file"
          disabled={disabled}
          onPress={() => onOpen("accounts")}
        />
      </View>
      {children}
    </ScrollView>
  );
}
const local = StyleSheet.create({
  summary: {
    backgroundColor: palette.navy,
    borderRadius: 24,
    padding: 22,
    gap: 10,
  },
  summaryLabel: {
    fontSize: 11,
    fontWeight: "700",
    letterSpacing: 1.6,
    color: "#d1e1f3",
  },
  summaryNumber: {
    fontSize: 30,
    lineHeight: 39,
    fontWeight: "700",
    color: "white",
  },
  summaryCopy: { fontSize: 13, lineHeight: 20, color: "#d1e1f3" },
  quick: {
    flex: 1,
    backgroundColor: "white",
    borderColor: palette.border,
    borderWidth: 1,
    borderRadius: 22,
    padding: 16,
    gap: 12,
    minHeight: 156,
  },
  quickTitle: {
    color: palette.ink,
    fontWeight: "700",
    fontSize: 16,
    lineHeight: 22,
  },
});
