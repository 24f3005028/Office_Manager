import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { Person, todayIndia } from "./api";
import DateField from "./DateField";
import { pinHomeWidget, refreshHomeWidgets, saveWidgetSettings, widgetSettings, widgetsAvailable } from "./homeWidgets";
import {
  OfficeTask,
  TaskPerson,
  indiaInputs,
  taskDate,
  taskDue,
} from "./taskModel";
import {
  enableTaskReminders,
  reminderStatus,
  stopTaskReminders,
  syncTaskReminders,
  testTaskReminder,
} from "./taskReminders";
import { Button, Heading, Icon, Note, palette, styles } from "./ui";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
export type TasksHandle = { back: () => boolean; showOpen: (scope: "mine" | "all") => void };
export default forwardRef<
  TasksHandle,
  { api: Api; person: Person | null; visible: boolean }
>(function TasksScreen({ api, person, visible }, ref) {
  const [tasks, setTasks] = useState<OfficeTask[]>([]),
    [people, setPeople] = useState<TaskPerson[]>([]);
  const [filter, setFilter] = useState<"mine" | "all" | "done">("all");
  const [editing, setEditing] = useState<OfficeTask | null>(null),
    [form, setForm] = useState(false);
  const [title, setTitle] = useState(""),
    [notes, setNotes] = useState(""),
    [date, setDate] = useState(todayIndia()),
    [time, setTime] = useState("18:00");
  const [repeat, setRepeat] = useState<OfficeTask["repeat_rule"]>("none"),
    [assignees, setAssignees] = useState<string[]>([]);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [enabled, setEnabled] = useState(false);
  const saveKey = useRef<string | null>(null),
    scroll = useRef<React.ComponentRef<typeof ScrollView>>(null);
  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update tasks.");
    } finally {
      setBusy(false);
    }
  }, []);
  const refresh = useCallback(async () => {
    const [rows, members, on] = await Promise.all([
      api<OfficeTask[]>("/tasks"),
      api<TaskPerson[]>("/task-people"),
      reminderStatus(),
    ]);
    setTasks(rows);
    void refreshHomeWidgets().catch(() => {});
    setPeople(members);
    setEnabled(on);
    try {
      await syncTaskReminders();
    } catch {
      setNotice(
        "Tasks loaded. Phone reminders could not refresh; check your office connection.",
      );
    }
  }, [api]);
  useEffect(() => {
    if (visible) void run(refresh);
  }, [visible, refresh, run]);
  useEffect(() => {
    if (!visible) return;
    const listener = AppState.addEventListener("change", (state) => {
      if (state === "active") void run(refresh);
    });
    return () => listener.remove();
  }, [visible, run, refresh]);
  useEffect(() => {
    scroll.current?.scrollTo({ y: 0, animated: false });
  }, [form]);
  useImperativeHandle(
    ref,
    () => ({
      showOpen: (scope) => setFilter(scope),
      back: () => {
        if (busy) return true;
        if (form) {
          closeForm();
          return true;
        }
        return false;
      },
    }),
    [busy, form, title, notes, date, time, repeat, assignees, editing],
  );
  function closeForm() {
    Alert.alert("Leave this task?", "Unsaved changes will be discarded.", [
      { text: "Keep editing", style: "cancel" },
      {
        text: "Discard",
        onPress: () => {
          setForm(false);
          setEditing(null);
          saveKey.current = null;
          setError("");
        },
      },
    ]);
  }
  function start(task?: OfficeTask) {
    setEditing(task ?? null);
    setTitle(task?.title ?? "");
    setNotes(task?.notes ?? "");
    const due = task
      ? indiaInputs(task.due_at)
      : { date: todayIndia(), time: "18:00" };
    setDate(due.date);
    setTime(due.time);
    setRepeat(task?.repeat_rule ?? "none");
    setAssignees(task?.assignees ?? (person ? [person.id] : []));
    saveKey.current = null;
    setError("");
    setNotice("");
    setForm(true);
  }
  function save() {
    void run(async () => {
      if (!title.trim()) throw new Error("Enter a task title.");
      const payload = {
        title: title.trim(),
        notes: notes.trim(),
        due_at: taskDue(date, time),
        repeat_rule: repeat,
        assignees,
      };
      saveKey.current ??= `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      await api(
        editing ? `/tasks/${editing.id}/update` : "/tasks",
        editing
          ? { ...payload, version: editing.version }
          : { ...payload, request_key: saveKey.current },
      );
      setForm(false);
      setEditing(null);
      saveKey.current = null;
      await refresh();
      setNotice("Task saved for the office.");
    });
  }
  function complete(task: OfficeTask) {
    Alert.alert(
      "Mark this task done?",
      task.repeat_rule === "none"
        ? task.title
        : `${task.title}\nThe next ${task.repeat_rule} occurrence will remain open.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Mark done",
          onPress: () =>
            void run(async () => {
              await api(`/tasks/${task.id}/complete`, {
                version: task.version,
              });
              await refresh();
              setNotice(
                task.repeat_rule === "none"
                  ? "Task completed."
                  : "Completed. The next due date is ready.",
              );
            }),
        },
      ],
    );
  }
  const shown = tasks.filter((task) =>
    filter === "done"
      ? task.status === "done"
      : task.status === "open" &&
        (filter !== "mine" || task.assignees.includes(person?.id ?? "")),
  );
  return (
    <ScrollView
      ref={scroll}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Heading
        eyebrow="SHARED TASKS"
        title={
          form
            ? editing
              ? "Edit task"
              : "New office task"
            : "Office to-do list"
        }
        subtitle={
          form
            ? "Set a due time and choose who gets reminded."
            : "Everyone can add tasks and mark shared work done."
        }
      />
      {error !== "" && (
        <View
          accessibilityRole="alert"
          style={[styles.notice, { marginHorizontal: 0 }]}
        >
          <Text style={[styles.error, styles.grow]}>{error}</Text>
        </View>
      )}
      {notice !== "" && <Note icon="info">{notice}</Note>}
      {busy && <ActivityIndicator color={palette.blue} />}
      {!form && widgetsAvailable && <Button title="Add tasks home widget" secondary disabled={busy} onPress={() => void run(async () => {
        await saveWidgetSettings({ ...await widgetSettings(), enabled: true });
        const result = await pinHomeWidget("tasks");
        setNotice(result === "updated" ? "Your existing tasks widget is updated." : result === "requested" ? "Confirm Add on your home-screen prompt. Change My tasks / All tasks under Account & connection → Home-screen widgets."
          : "Long-press your home screen → Widgets → H.S. Traders Office → Office tasks.");
      })} />}
      {form ? (
        <View style={styles.card}>
          <View>
            <Text style={styles.label}>What needs doing?</Text>
            <TextInput
              style={styles.input}
              value={title}
              onChangeText={setTitle}
              placeholder="e.g. Follow up pending delivery"
              accessibilityLabel="Task title"
              maxLength={160}
              editable={!busy}
            />
          </View>
          <View>
            <Text style={styles.label}>Notes (optional)</Text>
            <TextInput
              style={styles.input}
              value={notes}
              onChangeText={setNotes}
              multiline
              placeholder="Details for the team"
              accessibilityLabel="Task notes"
              maxLength={2000}
              editable={!busy}
            />
          </View>
          <View style={styles.row}>
            <DateField
              label="Due date"
              value={date}
              onChange={setDate}
              disabled={busy}
            />
            <DateField
              label="Time (IST)"
              value={time}
              onChange={setTime}
              mode="time"
              disabled={busy}
            />
          </View>
          <Text style={styles.noteText}>
            All due dates and times use India time.
          </Text>
          <View>
            <Text style={styles.label}>Repeat</Text>
            <View style={styles.yearList}>
              {(
                [
                  ["none", "Once"],
                  ["daily", "Daily"],
                  ["weekly", "Weekly"],
                  ["monthly", "Monthly"],
                ] as const
              ).map(([key, label]) => (
                <Pressable
                  key={key}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: repeat === key }}
                  disabled={busy}
                  onPress={() => setRepeat(key)}
                  style={[styles.year, repeat === key && styles.yearActive]}
                >
                  <Text
                    style={[
                      styles.yearText,
                      repeat === key && styles.yearTextActive,
                    ]}
                  >
                    {label}
                  </Text>
                </Pressable>
              ))}
            </View>
          </View>
          <View>
            <Text style={styles.label}>Remind these people</Text>
            <Text style={styles.noteText}>
              All approved users can see the task. Only selected people receive
              reminders on their enabled phones.
            </Text>
          </View>
          {people.map((member) => (
            <Pressable
              key={member.id}
              accessibilityRole="checkbox"
              accessibilityState={{ checked: assignees.includes(member.id) }}
              accessibilityLabel={`Remind ${member.name}`}
              disabled={busy}
              style={styles.party}
              onPress={() =>
                setAssignees((ids) =>
                  ids.includes(member.id)
                    ? ids.filter((id) => id !== member.id)
                    : [...ids, member.id],
                )
              }
            >
              <View style={styles.partyMark}>
                <Icon
                  name={assignees.includes(member.id) ? "check" : "settings"}
                  color={
                    assignees.includes(member.id) ? palette.teal : palette.muted
                  }
                />
              </View>
              <Text style={styles.partyName}>
                {member.name}
                {member.id === person?.id ? " (you)" : ""}
              </Text>
            </Pressable>
          ))}
          {!assignees.length && (
            <Note icon="info">
              No recipients selected. This task will appear in the shared list
              without phone reminders.
            </Note>
          )}
          <Button
            title={editing ? "Save changes" : "Add task"}
            icon="check"
            disabled={busy || !title.trim()}
            onPress={save}
          />
          <Button
            title="Cancel"
            secondary
            disabled={busy}
            onPress={closeForm}
          />
        </View>
      ) : (
        <>
          <Button
            title="Add task"
            icon="check"
            disabled={busy}
            onPress={() => start()}
          />
          <View style={styles.yearList}>
            {(
              [
                ["all", "All open"],
                ["mine", "For me"],
                ["done", "Completed"],
              ] as const
            ).map(([key, label]) => (
              <Pressable
                key={key}
                accessibilityRole="tab"
                accessibilityState={{ selected: filter === key }}
                disabled={busy}
                onPress={() => setFilter(key)}
                style={[styles.year, filter === key && styles.yearActive]}
              >
                <Text
                  style={[
                    styles.yearText,
                    filter === key && styles.yearTextActive,
                  ]}
                >
                  {label}
                </Text>
              </Pressable>
            ))}
          </View>
          <View style={styles.sectionHead}>
            <Text style={styles.sectionTitle}>
              {shown.length} {shown.length === 1 ? "task" : "tasks"}
            </Text>
            <Pressable
              style={styles.textButton}
              accessibilityRole="button"
              disabled={busy}
              onPress={() => void run(refresh)}
            >
              <Text style={styles.link}>Refresh</Text>
            </Pressable>
          </View>
          {shown.map((task) => (
            <View key={task.id} style={styles.card}>
              <View style={styles.row}>
                <View style={styles.tileIcon}>
                  <Icon name={task.status === "done" ? "check" : "calendar"} />
                </View>
                <Text style={[styles.cardTitle, styles.grow]}>
                  {task.title}
                </Text>
              </View>
              <Text
                style={[
                  styles.status,
                  task.status === "open" && Date.parse(task.due_at) < Date.now()
                    ? styles.error
                    : task.status === "done"
                      ? styles.success
                      : null,
                ]}
              >
                {task.status === "done"
                  ? "Completed"
                  : Date.parse(task.due_at) < Date.now()
                    ? "Overdue"
                    : "Due"}{" "}
                · {taskDate(task.due_at)} IST
              </Text>
              {task.notes !== "" && (
                <Text style={styles.muted}>{task.notes}</Text>
              )}
              <Text style={styles.noteText}>
                Repeat:{" "}
                {task.repeat_rule === "none" ? "Once" : task.repeat_rule} ·
                Added by {task.creator_name ?? "Office user"}
              </Text>
              <Text style={styles.noteText}>
                Reminders:{" "}
                {task.assignees
                  .map(
                    (id) =>
                      people.find((member) => member.id === id)?.name ??
                      "Former user",
                  )
                  .join(", ") || "No recipients"}
              </Text>
              {task.last_completed_at && (
                <Text style={styles.noteText}>
                  Last done {taskDate(task.last_completed_at)}
                  {task.completed_by_name
                    ? ` by ${task.completed_by_name}`
                    : ""}{" "}
                  · {task.completed_count} completed
                </Text>
              )}
              {task.status === "open" && (
                <Button
                  title="Mark done"
                  icon="check"
                  disabled={busy}
                  onPress={() => complete(task)}
                />
              )}
              {(task.created_by === person?.id || person?.can_invite_users) &&
                task.status === "open" && (
                  <View style={styles.smallActions}>
                    <View style={styles.grow}>
                      <Button
                        title="Edit"
                        secondary
                        disabled={busy}
                        onPress={() => start(task)}
                      />
                    </View>
                    <View style={styles.grow}>
                      <Button
                        title="Cancel task"
                        secondary
                        disabled={busy}
                        onPress={() =>
                          Alert.alert(
                            "Cancel this task?",
                            "It will be removed from the shared list and its reminders will stop after phones sync.",
                            [
                              { text: "Keep task", style: "cancel" },
                              {
                                text: "Cancel task",
                                style: "destructive",
                                onPress: () =>
                                  void run(async () => {
                                    await api(`/tasks/${task.id}/cancel`, {
                                      version: task.version,
                                    });
                                    await refresh();
                                  }),
                              },
                            ],
                          )
                        }
                      />
                    </View>
                  </View>
                )}
            </View>
          ))}
          {!shown.length && (
            <View style={styles.empty}>
              <Icon name="check" size={32} color={palette.teal} />
              <Text style={styles.emptyTitle}>Nothing here yet</Text>
              <Text style={styles.emptyCopy}>
                Add an office task or choose another filter.
              </Text>
            </View>
          )}
          <View style={styles.card}>
            <Text style={styles.sectionTitle}>Reminders on this phone</Text>
            <Text style={styles.muted}>
              {enabled
                ? "Enabled for your selected tasks."
                : "Off. Enable to receive reminders for tasks assigned to you."}
            </Text>
            <Button
              title={enabled ? "Refresh reminders" : "Enable phone reminders"}
              secondary
              icon="calendar"
              disabled={busy}
              onPress={() =>
                void run(async () => {
                  setNotice(await enableTaskReminders());
                  setEnabled(await reminderStatus());
                })
              }
            />
            {enabled && (
              <Button
                title="Test notification"
                secondary
                icon="check"
                disabled={busy}
                onPress={() =>
                  void run(async () => {
                    await testTaskReminder();
                    setNotice(
                      "Test reminder scheduled for a few seconds from now. Android may delay it under battery restrictions.",
                    );
                  })
                }
              />
            )}
            {enabled && (
              <Button
                title="Turn reminders off"
                secondary
                disabled={busy}
                onPress={() =>
                  void run(async () => {
                    await stopTaskReminders();
                    setEnabled(false);
                  })
                }
              />
            )}
            <Note icon="info">
              Background refresh takes 15 minutes or longer. Keep Tailscale
              connected. Android battery restrictions or force-stopping the app
              can delay reminders; open the app to refresh. Repeats move to the
              next due date when marked done.
            </Note>
          </View>
        </>
      )}
    </ScrollView>
  );
});
