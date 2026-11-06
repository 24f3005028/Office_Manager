import {
  ComponentRef,
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
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { todayIndia } from "./api";
import DateField from "./DateField";
import {
  Button,
  displayDate,
  Heading,
  Icon,
  Note,
  palette,
  styles,
  Steps,
  TaskTile,
} from "./ui";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
type Category = "bills" | "credit_notes" | "debit_notes" | "all";
type Document = {
  file_id: string;
  file_name: string;
  category: string;
  effective_date: string;
  date_source: string;
  matched_voucher_no?: string;
};
type Contact = {
  id: string;
  name: string;
  number?: string;
  phone_display?: string;
};
type Action = {
  id: string;
  kind: "pouncha" | "send";
  state: string;
  created_at: string;
  result: {
    status?: string;
    error?: string;
    start_date?: string;
    end_date?: string;
    preview_only?: boolean;
    exported_count?: number;
    existing_count?: number;
    new_count?: number;
    appended_count?: number;
    files?: { file_name: string; status: string; error?: string }[];
    recipient?: string;
  };
};
type SyncStatus = {
  last_date: string | null;
  last_bill: string | null;
  bill_count: number | null;
  sheet_error: string | null;
};
const terminal = new Set([
  "success",
  "failed",
  "cancelled",
  "completed",
  "needs_review",
  "reviewed",
]);
const errorMessage = (value: unknown) =>
  value instanceof Error ? value.message : "The office request failed.";
const newKey = () => `${Date.now()}-${Math.random().toString(36).slice(2)}`;

export type OfficeToolsHandle = { back: () => boolean };
export default forwardRef<
  OfficeToolsHandle,
  {
    api: Api;
    visible: boolean;
    mode: "tools" | "history";
    onShowActivity: () => void;
    onShowTasks: () => void;
  }
>(function OfficeToolsScreen(
  { api, visible, mode, onShowActivity, onShowTasks },
  ref,
) {
  const [tool, setTool] = useState<"menu" | "pouncha" | "send">("menu");
  const [sendStep, setSendStep] = useState(0);
  const [showResult, setShowResult] = useState(false);
  const scroll = useRef<ComponentRef<typeof ScrollView>>(null);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [syncStatus, setSyncStatus] = useState<SyncStatus | null>(null);
  const [start, setStart] = useState(""),
    [end, setEnd] = useState(todayIndia());
  const [customDates, setCustomDates] = useState(false);
  const [sendStart, setSendStart] = useState(todayIndia()),
    [sendEnd, setSendEnd] = useState(todayIndia());
  const [category, setCategory] = useState<Category>("bills"),
    [filter, setFilter] = useState("");
  const [documents, setDocuments] = useState<Document[] | null>(null),
    [selected, setSelected] = useState<string[]>([]);
  const [contactQuery, setContactQuery] = useState(""),
    [contacts, setContacts] = useState<Contact[]>([]),
    [contact, setContact] = useState<Contact | null>(null);
  const [message, setMessage] = useState("Please find the attached documents.");
  const [action, setAction] = useState<Action | null>(null),
    [actions, setActions] = useState<Action[]>([]);
  const [bridge, setBridge] = useState<{
    connected?: boolean;
    status?: string;
  } | null>(null);
  const pendingKey = useRef<string | null>(null);
  const active = Boolean(
    action &&
    (action.state === "submitting" ||
      (action.state === "accepted" &&
        !terminal.has(action.result.status ?? ""))),
  );
  const [previewDates, setPreviewDates] = useState("");
  const datesKey = JSON.stringify([customDates ? start : null, end]);
  const previewReady =
    action?.kind === "pouncha" &&
    action.result.preview_only &&
    action.result.status === "success" &&
    previewDates === datesKey;

  useImperativeHandle(
    ref,
    () => ({
      back: () => {
        if (busy) return true;
        if (showResult) {
          setShowResult(false);
          return true;
        }
        if (mode === "history") return false;
        if (tool === "send" && sendStep > 0) {
          setSendStep((step) => step - 1);
          return true;
        }
        if (tool !== "menu") {
          setTool("menu");
          setError("");
          return true;
        }
        return false;
      },
    }),
    [busy, showResult, mode, tool, sendStep],
  );
  useEffect(() => {
    if (visible) scroll.current?.scrollTo({ y: 0, animated: false });
  }, [visible, mode, tool, sendStep, showResult]);

  const run = useCallback(async (operation: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await operation();
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  }, []);
  const refresh = useCallback(async () => {
    const [status, rows] = await Promise.all([
      api<SyncStatus>("/office/pouncha"),
      api<Action[]>("/office/actions"),
    ]);
    setSyncStatus(status);
    setActions(rows);
    const pending = rows.find(
      (row) =>
        row.state === "submitting" ||
        (row.state === "accepted" && !terminal.has(row.result.status ?? "")),
    );
    if (pending) setAction(await api<Action>(`/office/actions/${pending.id}`));
  }, [api]);
  useEffect(() => {
    if (!visible) return;
    void run(refresh);
  }, [run, refresh, visible]);
  useEffect(() => {
    if (!visible || mode !== "tools" || tool !== "send") return;
    void api<{ connected?: boolean; status?: string }>("/office/whatsapp")
      .then(setBridge)
      .catch((reason) => {
        setBridge({ connected: false, status: "Unavailable" });
        setError(errorMessage(reason));
      });
  }, [api, tool, visible, mode]);
  useEffect(() => {
    if (
      !visible ||
      mode !== "tools" ||
      tool !== "send" ||
      sendStep !== 1 ||
      contact
    )
      return;
    let stopped = false;
    const timer = setTimeout(() => {
      void api<Contact[]>(
        `/office/contacts?q=${encodeURIComponent(contactQuery)}`,
      )
        .then((rows) => {
          if (!stopped) setContacts(rows);
        })
        .catch((reason) => {
          if (!stopped) setError(errorMessage(reason));
        });
    }, 300);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [api, contactQuery, contact, tool, visible, mode, sendStep]);
  useEffect(() => {
    if (!visible || !active || !action) return;
    let stopped = false;
    const timer = setInterval(() => {
      void api<Action>(`/office/actions/${action.id}`)
        .then((row) => {
          if (!stopped) {
            setAction(row);
            setActions((rows) =>
              rows.map((item) => (item.id === row.id ? row : item)),
            );
          }
        })
        .catch((reason) => {
          if (!stopped) setError(errorMessage(reason));
        });
    }, 2500);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [action?.id, active, api, visible]);

  async function submit(
    kind: "pouncha" | "send",
    payload: Record<string, unknown>,
  ) {
    await run(async () => {
      pendingKey.current ??= newKey();
      const row = await api<Action>(`/office/${kind}`, {
        ...payload,
        confirmed: true,
        request_key: pendingKey.current,
      });
      setAction(row);
      setShowResult(true);
      setActions((rows) => [row, ...rows.filter((item) => item.id !== row.id)]);
      pendingKey.current = null;
    });
  }
  function sync(preview: boolean) {
    if (
      !/^\d{4}-\d{2}-\d{2}$/.test(end) ||
      (customDates && !/^\d{4}-\d{2}-\d{2}$/.test(start))
    ) {
      setError("Enter dates as YYYY-MM-DD.");
      return;
    }
    const payload = {
      start_date: customDates ? start : null,
      end_date: end,
      preview_only: preview,
    };
    if (preview) {
      setPreviewDates(datesKey);
      void submit("pouncha", payload);
    } else
      Alert.alert(
        "Update the Pouncha sheet?",
        `Add the missing bills through ${displayDate(end)}. Existing rows are preserved. The office will get a five-second warning.`,
        [
          { text: "Cancel", style: "cancel" },
          {
            text: "Update sheet",
            onPress: () => void submit("pouncha", payload),
          },
        ],
      );
  }
  function loadDocuments() {
    void run(async () => {
      const params = `start_date=${encodeURIComponent(sendStart)}&end_date=${encodeURIComponent(sendEnd)}&category=${category}`;
      setDocuments(await api<Document[]>(`/office/documents?${params}`));
      setSelected([]);
    });
  }
  function confirmSend() {
    if (!contact || !documents) return;
    const chosen = documents.filter((row) => selected.includes(row.file_id));
    const fallback = chosen.filter(
      (row) => row.date_source === "file_fallback",
    ).length;
    Alert.alert(
      "Send these documents?",
      `${chosen.length} documents to ${contact.name}\n${contact.phone_display ?? contact.number ?? "Saved WhatsApp contact"}\n\nOldest first, with the dashboard's date labels and ordering.${fallback ? `\n\n${fallback} documents use the file date; verify before sending.` : ""}\n\nOpening message: ${message.trim() || "None"}`,
      [
        { text: "Go back", style: "cancel" },
        {
          text: "Confirm & send",
          onPress: () =>
            void submit("send", {
              file_ids: selected,
              recipient: contact.id,
              message: message.trim() || null,
            }),
        },
      ],
    );
  }
  function dateField(
    label: string,
    value: string,
    setter: (value: string) => void,
  ) {
    return (
      <DateField
        label={label}
        value={value}
        onChange={setter}
        disabled={busy || active}
        maximumDate={new Date()}
      />
    );
  }
  function actionCard(row: Action) {
    return (
      <View style={styles.card}>
        <Text style={styles.cardTitle}>
          {row.kind === "pouncha"
            ? row.result.preview_only
              ? "Sheet preview"
              : "Pouncha update"
            : "WhatsApp sending"}
        </Text>
        <Text style={styles.status}>
          {row.state === "accepted"
            ? row.result.status?.replaceAll("_", " ")
            : row.state.replaceAll("_", " ")}
        </Text>
        {row.result.error && (
          <Text style={styles.error}>{row.result.error}</Text>
        )}
        {row.kind === "pouncha" && (
          <>
            <Text style={styles.muted}>
              {row.result.start_date} → {row.result.end_date}
            </Text>
            <View style={{ gap: 9 }}>
              {[
                ["Bills checked", row.result.exported_count],
                ["Already saved", row.result.existing_count],
                ["New bills", row.result.new_count],
                ["Added & verified", row.result.appended_count],
              ].map(([label, count]) => (
                <View style={styles.sectionHead} key={label}>
                  <Text style={styles.muted}>{label}</Text>
                  <Text style={styles.sectionTitle}>{count ?? 0}</Text>
                </View>
              ))}
            </View>
          </>
        )}
        {row.kind === "send" && (
          <>
            <Text style={styles.muted}>Recipient: {row.result.recipient}</Text>
            {row.result.files?.map((file, i) => (
              <View key={i} style={{ gap: 4 }}>
                <Text style={styles.historyTitle}>{file.file_name}</Text>
                <Text style={styles.muted}>
                  {file.status}
                  {file.error ? ` · ${file.error}` : ""}
                </Text>
              </View>
            ))}
            {row.state === "accepted" &&
              ["queued", "running"].includes(row.result.status ?? "") && (
                <Button
                  title="Stop unsent documents"
                  secondary
                  disabled={busy}
                  onPress={() =>
                    Alert.alert(
                      "Stop this sending request?",
                      "Documents already sent cannot be recalled.",
                      [
                        { text: "Keep sending", style: "cancel" },
                        {
                          text: "Stop unsent",
                          onPress: () =>
                            void run(async () =>
                              setAction(
                                await api<Action>(
                                  `/office/actions/${row.id}/cancel`,
                                  {},
                                ),
                              ),
                            ),
                        },
                      ],
                    )
                  }
                />
              )}
          </>
        )}
        {row.kind === "pouncha" && row.result.status === "needs_review" && (
          <>
            <Button
              title="Verify saved rows"
              secondary
              disabled={busy}
              onPress={() =>
                void run(async () =>
                  setAction(
                    await api<Action>(`/office/actions/${row.id}/review`, {
                      confirmed: true,
                      operation: "verify",
                    }),
                  ),
                )
              }
            />
            <Button
              title="Release after manual sheet review"
              secondary
              disabled={busy}
              onPress={() =>
                Alert.alert(
                  "Have you checked the sheet?",
                  "Only release this run after checking its rows in Google Sheets. This does not resend anything.",
                  [
                    { text: "Go back", style: "cancel" },
                    {
                      text: "I checked · release",
                      onPress: () =>
                        void run(async () =>
                          setAction(
                            await api<Action>(
                              `/office/actions/${row.id}/review`,
                              { confirmed: true, operation: "release" },
                            ),
                          ),
                        ),
                    },
                  ],
                )
              }
            />
          </>
        )}
        <Button
          title="Refresh this request"
          secondary
          disabled={busy}
          onPress={() =>
            void run(async () =>
              setAction(await api<Action>(`/office/actions/${row.id}`)),
            )
          }
        />
        {row.state === "needs_review" && (
          <Note icon="info">
            Check the office dashboard before creating another request. This
            action will not be retried automatically.
          </Note>
        )}
      </View>
    );
  }
  const visibleDocuments =
    documents?.filter((row) =>
      (row.file_name + " " + (row.matched_voucher_no ?? ""))
        .toLowerCase()
        .includes(filter.toLowerCase()),
    ) ?? [];
  return (
    <ScrollView
      ref={scroll}
      contentContainerStyle={styles.content}
      keyboardShouldPersistTaps="handled"
    >
      <Heading
        eyebrow={mode === "history" ? "ACTIVITY" : "OFFICE"}
        title={
          mode === "history"
            ? "Office requests"
            : showResult
              ? "Request details"
              : tool === "menu"
                ? "What do you need?"
                : tool === "send"
                  ? "Send bills"
                  : "Update Pouncha"
        }
        subtitle={
          mode === "history"
            ? "Sheet updates and WhatsApp sends in one place."
            : showResult
              ? "Check progress and the result of your request."
              : tool === "menu"
                ? "Choose one task to get started."
                : tool === "send"
                  ? "Choose PDFs, choose a person, then review."
                  : "Preview missing bills, then confirm the update."
        }
      />
      {error && (
        <View style={styles.notice}>
          <Text style={[styles.error, styles.grow]}>{error}</Text>
        </View>
      )}
      {busy && <ActivityIndicator color={palette.blue} />}
      {showResult && action ? (
        <>
          {actionCard(action)}
          {mode === "tools" && previewReady && (
            <Button
              title={`Update sheet · ${action.result.new_count ?? 0} new bills`}
              icon="arrow"
              disabled={busy || active || !action.result.new_count}
              onPress={() => sync(false)}
            />
          )}
          <Button
            title={
              mode === "history"
                ? "Back to requests"
                : active
                  ? "Back to task"
                  : "Back to task options"
            }
            secondary
            disabled={busy}
            onPress={() => setShowResult(false)}
          />
        </>
      ) : mode === "tools" && tool === "menu" ? (
        <>
          <TaskTile
            title="Shared tasks"
            subtitle="Office to-dos, due dates and reminders."
            icon="check"
            onPress={onShowTasks}
          />
          <TaskTile
            title="Update Pouncha"
            subtitle="Add missing bills to the Google Sheet."
            icon="calendar"
            onPress={() => setTool("pouncha")}
          />
          <TaskTile
            title="Send bills"
            subtitle="Send saved PDFs to a WhatsApp contact."
            icon="whatsapp"
            onPress={() => setTool("send")}
          />
          {active && action && (
            <Button
              title="View your running request"
              icon="history"
              secondary
              onPress={() => setShowResult(true)}
            />
          )}
          {!active && action && (
            <Button
              title="View last request result"
              icon="history"
              secondary
              onPress={() => setShowResult(true)}
            />
          )}
          <TaskTile
            title="Office request history"
            subtitle="Check progress, results and sent documents."
            icon="history"
            onPress={onShowActivity}
          />
          <Note>Nothing starts until you choose and confirm a task.</Note>
        </>
      ) : mode === "tools" && tool === "pouncha" ? (
        <>
          <View style={styles.card}>
            <View style={styles.row}>
              <Icon name="statement" />
              <Text style={styles.sectionTitle}>Pouncha sync</Text>
            </View>
            <Text style={styles.muted}>
              Last bill: {syncStatus?.last_bill ?? "Not loaded"}
              {syncStatus?.last_date
                ? `\nLast date: ${displayDate(syncStatus.last_date)}`
                : ""}
            </Text>
            {syncStatus?.sheet_error && (
              <Text style={styles.error}>{syncStatus.sheet_error}</Text>
            )}
            {dateField("Update through", end, (value) => {
              setEnd(value);
              setPreviewDates("");
            })}
            <Pressable
              disabled={busy || active}
              style={styles.textButton}
              onPress={() => {
                setCustomDates(!customDates);
                setPreviewDates("");
              }}
            >
              <Text style={styles.link}>
                {customDates
                  ? "Continue from the last sheet entry"
                  : "Choose a custom start date"}
              </Text>
            </Pressable>
            {customDates &&
              dateField("Start date", start, (value) => {
                setStart(value);
                setPreviewDates("");
              })}
            <Button
              title="Preview missing bills"
              icon="search"
              disabled={busy || active}
              onPress={() => sync(true)}
            />
            <Note>
              Preview reads BUSY without changing the sheet. The office can
              cancel before desktop control begins.
            </Note>
          </View>
          {previewReady && (
            <Button
              title={`Update sheet · ${action?.result.new_count ?? 0} new bills`}
              icon="arrow"
              disabled={busy || active || !action?.result.new_count}
              onPress={() => sync(false)}
            />
          )}
        </>
      ) : mode === "tools" && tool === "send" ? (
        <>
          <Steps
            labels={["Documents", "Recipient", "Review"]}
            current={sendStep}
          />
          <Note icon="whatsapp">
            Office WhatsApp:{" "}
            {bridge?.connected ? "Connected" : (bridge?.status ?? "Checking…")}.
            Bills come from saved PDFs; BUSY is not operated.
          </Note>
          <Button
            title="Check office connection"
            secondary
            icon="shield"
            disabled={busy}
            onPress={() =>
              void run(async () => {
                setBridge(
                  await api<NonNullable<typeof bridge>>("/office/whatsapp"),
                );
                if (!contact)
                  setContacts(
                    await api<Contact[]>(
                      `/office/contacts?q=${encodeURIComponent(contactQuery)}`,
                    ),
                  );
              })
            }
          />
          {sendStep === 0 && (
            <View style={styles.card}>
              <Text style={styles.sectionTitle}>1. Choose documents</Text>
              <View style={styles.row}>
                {dateField("From", sendStart, (value) => {
                  setSendStart(value);
                  setDocuments(null);
                  setSelected([]);
                })}
                {dateField("Through", sendEnd, (value) => {
                  setSendEnd(value);
                  setDocuments(null);
                  setSelected([]);
                })}
              </View>
              <View style={styles.yearList}>
                {(
                  [
                    ["bills", "Bills"],
                    ["credit_notes", "Credit notes"],
                    ["debit_notes", "Debit notes"],
                    ["all", "All"],
                  ] as const
                ).map(([key, label]) => (
                  <Pressable
                    key={key}
                    disabled={busy || active}
                    onPress={() => {
                      setCategory(key);
                      setDocuments(null);
                      setSelected([]);
                    }}
                    style={[styles.year, category === key && styles.yearActive]}
                  >
                    <Text
                      style={[
                        styles.yearText,
                        category === key && styles.yearTextActive,
                      ]}
                    >
                      {label}
                    </Text>
                  </Pressable>
                ))}
              </View>
              <Button
                title="Load saved PDFs"
                icon="search"
                secondary
                disabled={busy || active}
                onPress={loadDocuments}
              />
              {documents && (
                <>
                  <TextInput
                    style={styles.input}
                    placeholder="Filter by filename or bill number"
                    value={filter}
                    onChangeText={setFilter}
                    accessibilityLabel="Filter documents"
                  />
                  <View style={styles.sectionHead}>
                    <Text style={styles.muted}>
                      {selected.length} selected · {documents.length} available
                    </Text>
                    <Pressable
                      disabled={busy || active}
                      style={styles.textButton}
                      onPress={() =>
                        setSelected((ids) =>
                          visibleDocuments.every((row) =>
                            ids.includes(row.file_id),
                          )
                            ? ids.filter(
                                (id) =>
                                  !visibleDocuments.some(
                                    (row) => row.file_id === id,
                                  ),
                              )
                            : [
                                ...new Set([
                                  ...ids,
                                  ...visibleDocuments.map((row) => row.file_id),
                                ]),
                              ].slice(0, 500),
                        )
                      }
                    >
                      <Text style={styles.link}>
                        {visibleDocuments.length &&
                        visibleDocuments.every((row) =>
                          selected.includes(row.file_id),
                        )
                          ? "Clear shown"
                          : "Select shown"}
                      </Text>
                    </Pressable>
                  </View>
                  {visibleDocuments.map((row) => (
                    <Pressable
                      key={row.file_id}
                      accessibilityRole="checkbox"
                      accessibilityState={{
                        checked: selected.includes(row.file_id),
                      }}
                      disabled={busy || active}
                      style={styles.party}
                      onPress={() =>
                        setSelected((ids) =>
                          ids.includes(row.file_id)
                            ? ids.filter((id) => id !== row.file_id)
                            : ids.length < 500
                              ? [...ids, row.file_id]
                              : ids,
                        )
                      }
                    >
                      <Icon
                        name={selected.includes(row.file_id) ? "check" : "file"}
                        color={
                          selected.includes(row.file_id)
                            ? palette.teal
                            : palette.muted
                        }
                      />
                      <View style={styles.grow}>
                        <Text style={styles.historyTitle}>{row.file_name}</Text>
                        <Text style={styles.historyMeta}>
                          {displayDate(row.effective_date)} ·{" "}
                          {row.category.replace("_", " ")}
                          {row.date_source === "file_fallback"
                            ? " · File date: verify"
                            : ""}
                        </Text>
                      </View>
                    </Pressable>
                  ))}
                  {!visibleDocuments.length && (
                    <Text style={styles.muted}>
                      No documents found for these filters.
                    </Text>
                  )}
                </>
              )}
              <Button
                title={`Continue · ${selected.length} selected`}
                icon="arrow"
                disabled={busy || active || !selected.length}
                onPress={() => setSendStep(1)}
              />
            </View>
          )}
          {sendStep === 1 && (
            <View style={styles.card}>
              <Text style={styles.sectionTitle}>2. Choose the recipient</Text>
              {contact ? (
                <>
                  <Text style={styles.cardTitle}>{contact.name}</Text>
                  <Text style={styles.muted}>
                    {contact.phone_display ??
                      contact.number ??
                      "Saved WhatsApp contact"}
                  </Text>
                  <Button
                    title="Choose another contact"
                    secondary
                    disabled={busy || active}
                    onPress={() => setContact(null)}
                  />
                </>
              ) : (
                <>
                  <TextInput
                    style={styles.input}
                    placeholder="Search WhatsApp name or number"
                    accessibilityLabel="Search WhatsApp contact"
                    value={contactQuery}
                    onChangeText={setContactQuery}
                    editable={!busy && !active}
                  />
                  {contacts.slice(0, 8).map((row) => (
                    <Pressable
                      key={row.id}
                      disabled={busy || active}
                      onPress={() => setContact(row)}
                      style={styles.party}
                    >
                      <View style={styles.grow}>
                        <Text style={styles.historyTitle}>{row.name}</Text>
                        <Text style={styles.historyMeta}>
                          {row.phone_display ?? row.number ?? "Saved contact"}
                        </Text>
                      </View>
                      <Icon name="chevron" size={17} />
                    </Pressable>
                  ))}
                </>
              )}
              {!contact && !contacts.length && (
                <Text style={styles.muted}>
                  Search for a saved WhatsApp contact by name or number.
                </Text>
              )}
              <Button
                title="Continue to review"
                icon="arrow"
                disabled={busy || active || !contact}
                onPress={() => setSendStep(2)}
              />
            </View>
          )}
          {sendStep === 2 && (
            <View style={styles.card}>
              <Text style={styles.sectionTitle}>3. Review & send</Text>
              <Text style={styles.cardTitle}>{contact?.name}</Text>
              <Text style={styles.muted}>
                {contact?.phone_display ?? contact?.number}
              </Text>
              <Text style={styles.noteText}>
                {displayDate(sendStart)} – {displayDate(sendEnd)} ·{" "}
                {category.replaceAll("_", " ")}
              </Text>
              {documents
                ?.filter((row) => selected.includes(row.file_id))
                .map((row) => (
                  <Text key={row.file_id} style={styles.historyTitle}>
                    {row.file_name}
                    {row.date_source === "file_fallback"
                      ? " · File date: verify"
                      : ""}
                  </Text>
                ))}
              <Text style={styles.label}>Opening message (optional)</Text>
              <TextInput
                style={styles.input}
                multiline
                value={message}
                maxLength={4096}
                onChangeText={setMessage}
                editable={!busy && !active}
                accessibilityLabel="Opening WhatsApp message"
              />
              <Text style={styles.muted}>
                {selected.length} selected PDFs ·{" "}
                {contact?.name ?? "No recipient chosen"}
              </Text>
              <Button
                title="Review & send"
                icon="whatsapp"
                green
                disabled={
                  busy ||
                  active ||
                  !selected.length ||
                  !contact ||
                  !bridge?.connected
                }
                onPress={confirmSend}
              />
            </View>
          )}
        </>
      ) : null}
      {!showResult && mode === "tools" && tool !== "menu" && (
        <Button
          title="Back"
          secondary
          icon="back"
          disabled={busy}
          onPress={() => {
            if (tool === "send" && sendStep > 0)
              setSendStep((step) => step - 1);
            else setTool("menu");
          }}
        />
      )}
      {!showResult && mode === "history" && (
        <>
          <View style={styles.sectionHead}>
            <Text style={styles.sectionTitle}>Your office requests</Text>
            <Pressable
              disabled={busy}
              style={styles.textButton}
              onPress={() => void run(refresh)}
            >
              <Text style={styles.link}>Refresh</Text>
            </Pressable>
          </View>
          {actions.map((row) => (
            <Pressable
              key={row.id}
              disabled={busy}
              style={styles.historyItem}
              onPress={() =>
                void run(async () => {
                  setAction(await api<Action>(`/office/actions/${row.id}`));
                  setShowResult(true);
                })
              }
            >
              <View style={styles.grow}>
                <Text style={styles.historyTitle}>
                  {row.kind === "send"
                    ? "WhatsApp documents"
                    : row.result.preview_only
                      ? "Pouncha preview"
                      : "Pouncha update"}
                </Text>
                <Text style={styles.historyMeta}>
                  {new Date(row.created_at).toLocaleString("en-IN")} ·{" "}
                  {row.result.status ?? row.state}
                </Text>
              </View>
              <Icon name="chevron" size={18} />
            </Pressable>
          ))}
          {!actions.length && (
            <View style={styles.empty}>
              <Icon name="history" size={32} />
              <Text style={styles.emptyTitle}>No office requests yet</Text>
              <Text style={styles.emptyCopy}>
                Sheet previews, updates and WhatsApp sends will appear here.
              </Text>
            </View>
          )}
          <Note>
            Actions run only when you confirm them. If a result is uncertain,
            check the office dashboard before retrying.
          </Note>
        </>
      )}
    </ScrollView>
  );
});
