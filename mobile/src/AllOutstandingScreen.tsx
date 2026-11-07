import YarnProgress from "./YarnProgress";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import {
  Alert,
  AppState,
  FlatList,
  Pressable,
  Text,
  TextInput,
  View,
} from "react-native";
import { Report, todayIndia } from "./api";
import DateField from "./DateField";
import {
  Button,
  displayDate,
  Heading,
  Icon,
  Note,
  palette,
  styles,
} from "./ui";

type Bill = {
  bill_number: string;
  date: string;
  pending_amount: string;
  reference_amount: string | null;
  due_date: string | null;
  due_days: number | null;
  type: string;
  broker?: string | null;
  discount?: string | null;
};
type Account = {
  party_name: string;
  pending_amount: string;
  bills: Bill[];
  broker?: string;
};
type Snapshot = {
  as_of: string;
  pending_amount: string;
  account_count: number;
  bill_count: number | null;
  layout: "bills" | "summary";
  accounts: Account[];
};
type Api = <T>(path: string, body?: unknown) => Promise<T>;
const running = (row: Report | null) =>
  !!row && ["queued", "warning", "generating"].includes(row.status);
const amount = (value: string) =>
  "₹" +
  Number(value).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
export type AllOutstandingHandle = { back: () => boolean };
export default forwardRef<
  AllOutstandingHandle,
  {
    api: Api;
    visible: boolean;
    selected: Report | null;
    onReport: (row: Report) => void;
    pdfActions: (id: string) => React.ReactNode;
  }
>(function AllOutstandingScreen(
  { api, visible, selected, onReport, pdfActions },
  ref,
) {
  const [asOf, setAsOf] = useState(todayIndia()),
    [report, setReport] = useState<Report | null>(null),
    [data, setData] = useState<Snapshot | null>(null);
  const [query, setQuery] = useState(""),
    [expanded, setExpanded] = useState<string | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [showOptions, setShowOptions] = useState(false),
    [showSharing, setShowSharing] = useState(false);
  const pendingKey = useRef<string | null>(null),
    loaded = useRef<string | null>(null);
  useImperativeHandle(
    ref,
    () => ({
      back: () => {
        if (busy) return true;
        if (expanded) {
          setExpanded(null);
          return true;
        }
        return false;
      },
    }),
    [busy, expanded],
  );
  useEffect(() => {
    if (selected) {
      setReport(selected);
      setAsOf(selected.as_of);
      setData(null);
      loaded.current = null;
    }
  }, [selected]);
  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not load outstanding bills.",
      );
    } finally {
      setBusy(false);
    }
  }, []);
  const refresh = useCallback(async () => {
    if (!report) return;
    const row = await api<Report>(`/reports/${report.id}`);
    setReport(row);
    onReport(row);
  }, [api, report?.id, onReport]);
  useEffect(() => {
    if (!visible || !running(report)) return;
    const tick = () => {
      if (AppState.currentState === "active")
        void refresh().catch((e) =>
          setError(
            e instanceof Error ? e.message : "Could not refresh this request.",
          ),
        );
    };
    tick();
    const timer = setInterval(tick, 2500);
    return () => clearInterval(timer);
  }, [visible, report?.id, report?.status, refresh]);
  useEffect(() => {
    if (
      !visible ||
      !report ||
      report.status !== "ready" ||
      loaded.current === report.id
    )
      return;
    const id = report.id;
    let stopped = false;
    void run(async () => {
      const snapshot = await api<Snapshot>(`/reports/${id}/outstanding`);
      if (!stopped) {
        setData(snapshot);
        loaded.current = id;
      }
    });
    return () => {
      stopped = true;
    };
  }, [visible, report?.id, report?.status, api, run]);
  function create() {
    Alert.alert(
      "Refresh all-account outstanding?",
      `Create a fresh outstanding report for all parties through ${displayDate(asOf)}. The office gets a five-second warning and can cancel.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Create report",
          onPress: () =>
            void run(async () => {
              pendingKey.current ??= `${Date.now()}-${Math.random().toString(36).slice(2)}`;
              const row = await api<Report>("/outstanding/all", {
                as_of: asOf,
                request_key: pendingKey.current,
              });
              setReport(row);
              onReport(row);
              setData(null);
              loaded.current = null;
              pendingKey.current = null;
              setExpanded(null);
            }),
        },
      ],
    );
  }
  const needle = query.trim().toLowerCase();
  const accounts =
    data?.accounts.filter(
      (account) =>
        account.party_name.toLowerCase().includes(needle) ||
        account.bills.some((bill) =>
          bill.bill_number.toLowerCase().includes(needle),
        ),
    ) ?? [];
  return (
    <FlatList
      data={accounts}
      keyExtractor={(account) => account.party_name}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={styles.content}
      ListHeaderComponent={
        <View style={styles.listHeader}>
          <Heading
            eyebrow="OUTSTANDING"
            title="All accounts"
            subtitle="Pending bills and totals, grouped by party."
          />
          {error !== "" && (
            <View
              accessibilityRole="alert"
              style={[styles.notice, { marginHorizontal: 0 }]}
            >
              <Text style={[styles.error, styles.grow]}>{error}</Text>
            </View>
          )}
          {(!data || showOptions) && (
            <View style={styles.card}>
              <DateField
                label="Bills status as of"
                value={asOf}
                onChange={setAsOf}
                disabled={busy || running(report)}
                maximumDate={new Date()}
              />
              <Button
                title={data ? "Create fresh report" : "Get all-account report"}
                icon="statement"
                disabled={busy || running(report)}
                onPress={create}
              />
              <Note details>
                Includes pending bills from 16 January 2025. The office can
                pause before a fresh report starts.
              </Note>
            </View>
          )}
          {(busy || running(report)) && (
            <View style={styles.card}>
              <YarnProgress color={palette.blue} />
              <Text style={styles.status}>
                {report?.status === "warning"
                  ? "Checking whether someone is using BUSY…"
                  : report?.status === "generating"
                    ? "Preparing the all-account report…"
                    : "Loading…"}
              </Text>
              <Text style={styles.noteText}>
                You can leave this screen and return from the menu or Activity.
              </Text>
            </View>
          )}
          {report && ["failed", "cancelled"].includes(report.status) && (
            <View style={styles.card}>
              <Text style={styles.error}>
                {report.error ?? "The report could not be prepared."}
              </Text>
            </View>
          )}
          {report && !data && (
            <Button
              title="Refresh this request"
              secondary
              icon="history"
              disabled={busy}
              onPress={() =>
                void run(async () => {
                  await refresh();
                  loaded.current = null;
                  if (report.status === "ready")
                    setData(
                      await api<Snapshot>(`/reports/${report.id}/outstanding`),
                    );
                })
              }
            />
          )}
          {data && (
            <>
              <View style={styles.card}>
                <Text style={styles.amountLabel}>TOTAL OUTSTANDING</Text>
                <Text
                  style={styles.amount}
                  adjustsFontSizeToFit
                  numberOfLines={1}
                >
                  {amount(data.pending_amount)}
                </Text>
                <Text style={styles.muted}>
                  As of {displayDate(data.as_of)} · {data.account_count}{" "}
                  accounts
                  {data.bill_count !== null
                    ? ` · ${data.bill_count} bills`
                    : ""}
                </Text>
                <Text style={styles.noteText}>
                  This is a saved snapshot. Create a fresh report for updated
                  amounts. Available for 48 hours.
                </Text>
                <View style={styles.smallActions}>
                  <View style={styles.grow}>
                    <Button
                      title={showSharing ? "Hide sharing" : "Share report"}
                      icon="share"
                      onPress={() => setShowSharing((value) => !value)}
                    />
                  </View>
                  <View style={styles.grow}>
                    <Button
                      title="Refresh options"
                      secondary
                      icon="calendar"
                      onPress={() => setShowOptions((value) => !value)}
                    />
                  </View>
                </View>
                {showSharing && report && pdfActions(report.id)}
              </View>
              <View style={styles.searchBox}>
                <Icon name="search" color={palette.muted} />
                <TextInput
                  style={styles.searchInput}
                  placeholder="Search party or bill number"
                  accessibilityLabel="Search all-account outstanding"
                  value={query}
                  onChangeText={setQuery}
                />
              </View>
              <Text style={styles.sectionTitle}>
                {accounts.length} accounts shown
              </Text>
              {data.layout === "summary" && (
                <Note icon="info">
                  This report contains party totals. Open a party statement for
                  individual bills.
                </Note>
              )}
            </>
          )}
        </View>
      }
      renderItem={({ item }) => (
        <View style={[styles.card, { marginBottom: 12 }]}>
          <Pressable
            accessibilityRole="button"
            accessibilityState={{ expanded: expanded === item.party_name }}
            onPress={() =>
              setExpanded((value) =>
                value === item.party_name ? null : item.party_name,
              )
            }
            style={styles.row}
          >
            <View style={styles.partyMark}>
              <Icon name="statement" />
            </View>
            <View style={styles.grow}>
              <Text style={styles.historyTitle}>{item.party_name}</Text>
              <Text style={styles.historyMeta}>
                {item.bills.length
                  ? `${item.bills.length} pending bills`
                  : "Account total"}
              </Text>
            </View>
            <Text style={styles.status}>{amount(item.pending_amount)}</Text>
          </Pressable>
          {expanded === item.party_name &&
            item.bills.map((bill, index) => (
              <View
                key={`${bill.bill_number}-${index}`}
                style={{
                  gap: 5,
                  borderTopWidth: 1,
                  borderTopColor: palette.border,
                  paddingTop: 12,
                }}
              >
                <Text style={styles.historyTitle}>{bill.bill_number}</Text>
                <View style={styles.sectionHead}>
                  <Text style={styles.noteText}>
                    {displayDate(bill.date)}
                    {bill.due_days !== null
                      ? ` · ${bill.due_days} due days`
                      : ""}
                  </Text>
                  <Text style={styles.status}>
                    {amount(bill.pending_amount)}
                  </Text>
                </View>
                {bill.due_date && (
                  <Text style={styles.noteText}>
                    Due {displayDate(bill.due_date)}
                  </Text>
                )}
                {bill.broker && (
                  <Text style={styles.noteText}>Broker: {bill.broker}</Text>
                )}
                {bill.discount && bill.discount !== "0" && (
                  <Text style={styles.noteText}>Discount: {bill.discount}</Text>
                )}
              </View>
            ))}
        </View>
      )}
      ListEmptyComponent={
        data ? (
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>
              {needle ? "No matching accounts" : "No outstanding bills"}
            </Text>
          </View>
        ) : undefined
      }
    />
  );
});
