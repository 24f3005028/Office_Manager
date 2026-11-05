import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import * as SecureStore from "expo-secure-store";
import * as FileSystem from "expo-file-system/legacy";
import * as Sharing from "expo-sharing";
import * as Print from "expo-print";
import {
  Invoice,
  officeUrl,
  Party,
  Person,
  Report,
  request,
  Session,
  todayIndia,
} from "./src/api";

const SESSION_KEY = "office-session-v1";
const statusText: Record<string, string> = {
  queued: "Waiting for the office…",
  warning: "Checking whether someone is using BUSY…",
  generating: "Creating your statement…",
  ready: "Statement ready",
  cancelled: "Someone is using BUSY",
  failed: "Report could not be created",
};
type Screen = "home" | "outstanding" | "invoices" | "history";
const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
function Button({
  title,
  onPress,
  disabled = false,
  secondary = false,
}: {
  title: string;
  onPress: () => void;
  disabled?: boolean;
  secondary?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        secondary && styles.secondary,
        disabled && styles.disabled,
        pressed && styles.pressed,
      ]}
    >
      <Text style={[styles.buttonText, secondary && styles.secondaryText]}>
        {title}
      </Text>
    </Pressable>
  );
}

function OfficeApp() {
  const [session, setSession] = useState<Session | null>(null),
    [restoring, setRestoring] = useState(true);
  const [url, setUrl] = useState(process.env.EXPO_PUBLIC_OFFICE_URL ?? ""),
    [code, setCode] = useState(""),
    [person, setPerson] = useState<Person | null>(null);
  const [screen, setScreen] = useState<Screen>("home"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [query, setQuery] = useState(""),
    [parties, setParties] = useState<Party[]>([]),
    [party, setParty] = useState<Party | null>(null);
  const [asOf, setAsOf] = useState(todayIndia()),
    [advanced, setAdvanced] = useState(false),
    [report, setReport] = useState<Report | null>(null);
  const [years, setYears] = useState<string[]>([]),
    [year, setYear] = useState("26-27"),
    [bill, setBill] = useState(""),
    [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [history, setHistory] = useState<Report[]>([]);
  const mounted = useRef(true),
    searchRevision = useRef(0);
  const activeReport = Boolean(
    report && ["queued", "warning", "generating"].includes(report.status),
  );
  const api = useCallback(
    <T,>(path: string, body?: unknown) => {
      if (!session)
        return Promise.reject(new Error("Connect this phone first."));
      return request<T>(session.url, path, session.token, body);
    },
    [session],
  );
  useEffect(() => {
    mounted.current = true;
    void SecureStore.getItemAsync(SESSION_KEY)
      .then((value) => {
        if (value) setSession(JSON.parse(value));
      })
      .catch(() => setError("Please connect this phone again."))
      .finally(() => setRestoring(false));
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    if (!session) return;
    void api<Person>("/me")
      .then(async (current) => {
        setPerson(current);
        const rows = await api<Report[]>("/reports");
        setHistory(rows);
        const pending = rows.find((row) =>
          ["queued", "warning", "generating"].includes(row.status),
        );
        if (pending) setReport(pending);
      })
      .catch((reason) => setError(errorText(reason)));
  }, [session, api]);
  useEffect(() => {
    if (!session || screen !== "outstanding") return;
    const revision = ++searchRevision.current;
    const timer = setTimeout(() => {
      void api<Party[]>(`/parties?q=${encodeURIComponent(query)}`)
        .then((rows) => {
          if (revision === searchRevision.current) setParties(rows);
        })
        .catch((reason) => setError(errorText(reason)));
    }, 300);
    return () => {
      clearTimeout(timer);
      searchRevision.current++;
    };
  }, [query, session, screen, api]);
  useEffect(() => {
    if (!session || !report || !activeReport) return;
    let stopped = false;
    const tick = () => {
      if (AppState.currentState === "active")
        void api<Report>(`/reports/${report.id}`)
          .then((row) => {
            if (!stopped) {
              setReport(row);
              setHistory((rows) =>
                rows.map((item) => (item.id === row.id ? row : item)),
              );
            }
          })
          .catch((reason) => {
            if (!stopped) setError(errorText(reason));
          });
    };
    const timer = setInterval(tick, 2500);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [session, report?.id, activeReport, api]);
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (reason) {
      setError(errorText(reason));
    } finally {
      if (mounted.current) setBusy(false);
    }
  }
  async function pairPhone() {
    await action(async () => {
      const base = officeUrl(url);
      const paired = await request<{ token: string; expires_at: string }>(
        base,
        "/pair",
        undefined,
        { invite_code: code.trim() },
      );
      const next = { url: base, ...paired };
      await SecureStore.setItemAsync(SESSION_KEY, JSON.stringify(next));
      setCode("");
      setSession(next);
    });
  }
  async function open(next: Screen) {
    setScreen(next);
    setError("");
    if (next === "history")
      await action(async () => setHistory(await api<Report[]>("/reports")));
    if (next === "invoices")
      await action(async () => {
        setInvoices(null);
        const data = await api<{ years: string[]; default: string | null }>(
          "/financial-years",
        );
        setYears(data.years);
        setYear(data.default ?? "26-27");
      });
  }
  async function generate() {
    if (!party) return;
    await action(async () => {
      if (
        !/^\d{4}-\d{2}-\d{2}$/.test(asOf) ||
        Number.isNaN(Date.parse(asOf)) ||
        asOf < "2025-01-16" ||
        asOf > todayIndia()
      ) {
        throw new Error(
          "Choose a date from 2025-01-16 through today, using YYYY-MM-DD.",
        );
      }
      setReport(
        await api<Report>("/reports", {
          party_id: party.id,
          as_of: asOf,
          request_key: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
        }),
      );
    });
  }
  async function findBill() {
    await action(async () =>
      setInvoices(
        await api<Invoice[]>(
          `/invoices?year=${encodeURIComponent(year)}&bill=${encodeURIComponent(bill.trim())}`,
        ),
      ),
    );
  }
  async function getPdf(
    kind: "reports" | "invoices",
    id: string,
    mode: "open" | "save" | "share",
  ) {
    await action(async () => {
      if (!session) return;
      const directory = FileSystem.cacheDirectory;
      if (!directory) throw new Error("Phone storage is unavailable.");
      const target = directory + `office-${id}.pdf`;
      const downloaded = await FileSystem.downloadAsync(
        `${session.url}/mobile/v1/${kind}/${id}/pdf`,
        target,
        { headers: { Authorization: `Bearer ${session.token}` } },
      );
      if (downloaded.status !== 200) {
        await FileSystem.deleteAsync(target, { idempotent: true });
        throw new Error(
          "PDF unavailable or access expired. Request a fresh copy.",
        );
      }
      if (mode === "save" && Platform.OS === "android") {
        const permission =
          await FileSystem.StorageAccessFramework.requestDirectoryPermissionsAsync();
        if (!permission.granted) return;
        const destination =
          await FileSystem.StorageAccessFramework.createFileAsync(
            permission.directoryUri,
            `Office-${id}.pdf`,
            "application/pdf",
          );
        const content = await FileSystem.readAsStringAsync(target, {
          encoding: FileSystem.EncodingType.Base64,
        });
        await FileSystem.writeAsStringAsync(destination, content, {
          encoding: FileSystem.EncodingType.Base64,
        });
        Alert.alert(
          "PDF saved",
          "Your PDF was saved in the folder you selected.",
        );
      } else if (mode === "open") {
        await Print.printAsync({ uri: target });
      } else if (await Sharing.isAvailableAsync()) {
        await Sharing.shareAsync(target, {
          mimeType: "application/pdf",
          dialogTitle: "Save or share PDF",
        });
      } else throw new Error("File sharing is unavailable on this phone.");
    });
  }
  function sendToMe(kind: "reports" | "invoices", id: string) {
    Alert.alert(
      "Send to your WhatsApp?",
      `Send this PDF to +${person?.phone ?? "your approved number"}?`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Send PDF",
          onPress: () =>
            void action(async () => {
              const delivery = await api<{
                status: string;
                error: string | null;
              }>(`/${kind}/${id}/send-to-me`, {});
              if (delivery.status === "sent")
                Alert.alert(
                  "Sent to WhatsApp",
                  "The office WhatsApp account accepted this PDF for sending.",
                );
              else
                throw new Error(
                  delivery.error ??
                    "Check WhatsApp before trying again. This document was not automatically resent.",
                );
            }),
        },
      ],
    );
  }
  function pdfActions(kind: "reports" | "invoices", id: string) {
    return (
      <View style={styles.actions}>
        <Button
          title="Open PDF"
          disabled={busy}
          onPress={() => void getPdf(kind, id, "open")}
        />
        <Button
          title="Download PDF"
          disabled={busy}
          secondary
          onPress={() => void getPdf(kind, id, "save")}
        />
        <Button
          title="Send to my WhatsApp"
          disabled={busy || !person}
          secondary
          onPress={() => sendToMe(kind, id)}
        />
        <Button
          title="Share PDF…"
          disabled={busy}
          secondary
          onPress={() => void getPdf(kind, id, "share")}
        />
      </View>
    );
  }
  function reportCard(row: Report) {
    return (
      <View style={styles.card}>
        <Text style={styles.cardTitle}>{row.party_name}</Text>
        <Text style={styles.muted}>Status as of {row.as_of}</Text>
        <Text style={styles.status}>
          {statusText[row.status] ?? row.status}
        </Text>
        {["queued", "warning", "generating"].includes(row.status) && (
          <>
            <ActivityIndicator color="#2256c4" />
            <Text style={styles.muted}>
              The office can cancel if someone is working in BUSY.
            </Text>
          </>
        )}
        {row.error && <Text style={styles.error}>{row.error}</Text>}
        {row.status === "ready" && (
          <>
            <Text style={styles.amount}>
              ₹
              {Number(row.details?.pending_amount ?? 0).toLocaleString(
                "en-IN",
                { minimumFractionDigits: 2 },
              )}
            </Text>
            <Text style={styles.muted}>
              Generated{" "}
              {row.finished_at
                ? new Date(row.finished_at).toLocaleString()
                : ""}
              . Saved reports expire after 48 hours.
            </Text>
            {pdfActions("reports", row.id)}
          </>
        )}
      </View>
    );
  }
  if (restoring)
    return (
      <View style={styles.loading}>
        <ActivityIndicator color="#2256c4" />
      </View>
    );
  return (
    <SafeAreaView style={styles.root}>
      <KeyboardAvoidingView
        style={styles.root}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View style={styles.header}>
          <Text style={styles.brand}>H.S. TRADERS</Text>
          <Text style={styles.muted}>
            {person ? `Hello, ${person.name}` : "Office on your phone"}
          </Text>
        </View>
        {error !== "" && (
          <View accessibilityRole="alert" style={styles.notice}>
            <Text style={styles.error}>{error}</Text>
            <Pressable onPress={() => setError("")}>
              <Text style={styles.link}>Dismiss</Text>
            </Pressable>
          </View>
        )}
        {busy && <ActivityIndicator color="#2256c4" style={{ margin: 8 }} />}
        {!session ? (
          <ScrollView
            contentContainerStyle={styles.content}
            keyboardShouldPersistTaps="handled"
          >
            <Text style={styles.title}>Connect this phone</Text>
            <Text style={styles.muted}>
              Turn on Tailscale, then enter the office address and your personal
              invite code.
            </Text>
            <Text style={styles.label}>Office HTTPS address</Text>
            <TextInput
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
              placeholder="https://office-computer.example.ts.net"
              value={url}
              onChangeText={setUrl}
              style={styles.input}
              accessibilityLabel="Office HTTPS address"
            />
            <Text style={styles.label}>Invite code</Text>
            <TextInput
              autoCapitalize="none"
              autoCorrect={false}
              secureTextEntry
              value={code}
              onChangeText={setCode}
              style={styles.input}
              accessibilityLabel="Invite code"
            />
            <Button
              title="Connect phone"
              disabled={busy || !url.trim() || !code.trim()}
              onPress={() => void pairPhone()}
            />
            <Text style={styles.muted}>
              Ask the owner to create an invite under Mobile access on the
              office dashboard. Each code works once and expires in 15 minutes.
            </Text>
          </ScrollView>
        ) : (
          <>
            <View style={styles.tabs}>
              {(
                [
                  ["home", "Home"],
                  ["outstanding", "Outstanding"],
                  ["invoices", "Find bill"],
                  ["history", "History"],
                ] as const
              ).map(([key, title]) => (
                <Pressable
                  key={key}
                  accessibilityRole="tab"
                  accessibilityState={{
                    selected: screen === key,
                    disabled: busy,
                  }}
                  disabled={busy}
                  onPress={() => void open(key)}
                  style={[styles.tab, screen === key && styles.activeTab]}
                >
                  <Text
                    style={[
                      styles.tabText,
                      screen === key && styles.activeTabText,
                    ]}
                  >
                    {title}
                  </Text>
                </Pressable>
              ))}
            </View>
            {screen === "home" ? (
              <ScrollView contentContainerStyle={styles.content}>
                <Text style={styles.title}>What do you need?</Text>
                <View style={styles.card}>
                  <Text style={styles.cardTitle}>Outstanding bills</Text>
                  <Text style={styles.muted}>
                    Choose a party and get their latest pending-bill statement.
                  </Text>
                  <Button
                    title="Get outstanding statement"
                    onPress={() => void open("outstanding")}
                  />
                </View>
                <View style={styles.card}>
                  <Text style={styles.cardTitle}>Find a bill</Text>
                  <Text style={styles.muted}>
                    Choose a financial year and enter the bill number.
                  </Text>
                  <Button
                    title="Find bill PDF"
                    onPress={() => void open("invoices")}
                  />
                </View>
                <Text style={styles.muted}>
                  Fresh statements require the office computer to be online,
                  unlocked and logged into BUSY. Saved bill lookup does not
                  operate BUSY.
                </Text>
                <Button
                  title="Check connection"
                  secondary
                  disabled={busy}
                  onPress={() =>
                    void action(async () => {
                      setPerson(await api<Person>("/me"));
                      Alert.alert("Connected", "The office is reachable.");
                    })
                  }
                />
                <Button
                  title="Disconnect this phone"
                  secondary
                  onPress={() =>
                    Alert.alert(
                      "Disconnect phone?",
                      "You will need a new invite to connect again.",
                      [
                        { text: "Cancel", style: "cancel" },
                        {
                          text: "Disconnect",
                          onPress: () =>
                            void action(async () => {
                              try {
                                await api("/logout", {});
                              } finally {
                                await SecureStore.deleteItemAsync(SESSION_KEY);
                                setSession(null);
                                setPerson(null);
                                setReport(null);
                                setHistory([]);
                                setParties([]);
                                setInvoices(null);
                              }
                            }),
                        },
                      ],
                    )
                  }
                />
              </ScrollView>
            ) : screen === "outstanding" ? (
              <FlatList
                data={party ? [] : parties}
                keyExtractor={(row) => row.id}
                keyboardShouldPersistTaps="handled"
                contentContainerStyle={styles.content}
                ListHeaderComponent={
                  <>
                    <Text style={styles.title}>Outstanding bills</Text>
                    <Text style={styles.label}>Search party</Text>
                    <TextInput
                      style={styles.input}
                      placeholder="Type party name"
                      value={query}
                      editable={!activeReport && !busy}
                      onChangeText={(value) => {
                        setQuery(value);
                        setParty(null);
                        setReport(null);
                      }}
                      accessibilityLabel="Search party"
                    />
                    {party && (
                      <View style={styles.card}>
                        <Text style={styles.cardTitle}>{party.name}</Text>
                        <Pressable
                          disabled={activeReport || busy}
                          onPress={() => {
                            setParty(null);
                            setReport(null);
                          }}
                        >
                          <Text style={styles.link}>Choose another party</Text>
                        </Pressable>
                        <Button
                          title={
                            activeReport
                              ? "Preparing statement…"
                              : "Get latest statement"
                          }
                          disabled={busy || activeReport}
                          onPress={() => void generate()}
                        />
                        <Pressable onPress={() => setAdvanced(!advanced)}>
                          <Text style={styles.link}>
                            {advanced
                              ? "Hide dates"
                              : "Choose a historical status date"}
                          </Text>
                        </Pressable>
                        {advanced && (
                          <>
                            <Text style={styles.label}>
                              Status date (YYYY-MM-DD)
                            </Text>
                            <TextInput
                              style={styles.input}
                              value={asOf}
                              onChangeText={setAsOf}
                              placeholder="2026-11-05"
                              accessibilityLabel="Statement status date"
                            />
                          </>
                        )}
                        <Text style={styles.muted}>
                          Includes pending bills from 16 January 2025 through{" "}
                          {asOf}.
                        </Text>
                      </View>
                    )}
                    {report && reportCard(report)}
                  </>
                }
                renderItem={({ item }) => (
                  <Pressable
                    accessibilityRole="button"
                    disabled={activeReport || busy}
                    onPress={() => {
                      setParty(item);
                      setReport(null);
                    }}
                    style={styles.party}
                  >
                    <Text style={styles.partyName}>{item.name}</Text>
                    <Text style={styles.link}>Choose →</Text>
                  </Pressable>
                )}
                ListEmptyComponent={
                  !party ? (
                    <Text style={styles.muted}>
                      No parties found. Try another spelling or ask the office
                      to update the account list.
                    </Text>
                  ) : undefined
                }
              />
            ) : screen === "invoices" ? (
              <ScrollView
                contentContainerStyle={styles.content}
                keyboardShouldPersistTaps="handled"
              >
                <Text style={styles.title}>Find a bill</Text>
                <Text style={styles.label}>Financial year</Text>
                <View style={styles.yearList}>
                  {years.map((value) => (
                    <Pressable
                      accessibilityRole="radio"
                      accessibilityState={{
                        selected: year === value,
                        disabled: busy,
                      }}
                      disabled={busy}
                      key={value}
                      onPress={() => {
                        setYear(value);
                        setInvoices(null);
                      }}
                      style={[styles.year, year === value && styles.activeTab]}
                    >
                      <Text>{value}</Text>
                    </Pressable>
                  ))}
                </View>
                {!years.length && (
                  <Text style={styles.muted}>
                    No indexed bill PDFs are available yet.
                  </Text>
                )}
                <Text style={styles.label}>Bill number</Text>
                <TextInput
                  style={styles.input}
                  value={bill}
                  editable={!busy}
                  onChangeText={(value) => {
                    setBill(value);
                    setInvoices(null);
                  }}
                  autoCapitalize="characters"
                  placeholder="74 or HST/L/26-27/74"
                  accessibilityLabel="Bill number"
                  onSubmitEditing={() => {
                    if (!busy && bill.trim()) void findBill();
                  }}
                />
                <Button
                  title="Find bill"
                  disabled={busy || !bill.trim() || !years.length}
                  onPress={() => void findBill()}
                />
                {invoices?.length === 0 && (
                  <Text style={styles.muted}>
                    No saved bill PDF found for this number and year. Check the
                    year and number, or ask the office for the PDF.
                  </Text>
                )}
                {invoices?.map((row) => (
                  <View key={row.file_id} style={styles.card}>
                    <Text style={styles.cardTitle}>{row.bill_number}</Text>
                    <Text>{row.party_name}</Text>
                    <Text style={styles.muted}>{row.date}</Text>
                    {row.conflicting_copies ? (
                      <Text style={styles.error}>
                        Different PDFs exist for this bill. Ask the office to
                        resolve them before downloading or sending.
                      </Text>
                    ) : (
                      pdfActions("invoices", row.file_id)
                    )}
                  </View>
                ))}
              </ScrollView>
            ) : (
              <ScrollView contentContainerStyle={styles.content}>
                <Text style={styles.title}>Your statements</Text>
                <Button
                  title="Refresh history"
                  disabled={busy}
                  secondary
                  onPress={() => void open("history")}
                />
                {!history.length && (
                  <Text style={styles.muted}>
                    Your requested statements will appear here.
                  </Text>
                )}
                {history.map((row) => (
                  <View key={row.id}>{reportCard(row)}</View>
                ))}
              </ScrollView>
            )}
          </>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}
export default function App() {
  return (
    <SafeAreaProvider>
      <OfficeApp />
    </SafeAreaProvider>
  );
}
const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: "#f4f6fa" },
  loading: { flex: 1, alignItems: "center", justifyContent: "center" },
  header: {
    padding: 20,
    backgroundColor: "white",
    borderBottomColor: "#dce1ea",
    borderBottomWidth: 1,
  },
  brand: { fontWeight: "800", fontSize: 20, color: "#17263b" },
  content: { padding: 20, gap: 18, paddingBottom: 40 },
  title: { fontSize: 29, fontWeight: "800", color: "#17263b" },
  muted: { fontSize: 14, lineHeight: 22, color: "#5c687b" },
  label: { fontSize: 15, fontWeight: "700", color: "#25344a" },
  input: {
    backgroundColor: "white",
    borderColor: "#b9c3d3",
    borderWidth: 1,
    borderRadius: 10,
    padding: 14,
    fontSize: 17,
    minHeight: 52,
    color: "#17263b",
  },
  card: {
    padding: 20,
    backgroundColor: "white",
    borderRadius: 15,
    borderColor: "#dce1ea",
    borderWidth: 1,
    gap: 14,
  },
  cardTitle: { fontSize: 21, fontWeight: "700", color: "#17263b" },
  button: {
    backgroundColor: "#2256c4",
    minHeight: 52,
    borderRadius: 10,
    padding: 14,
    alignItems: "center",
    justifyContent: "center",
  },
  buttonText: { color: "white", fontSize: 16, fontWeight: "700" },
  secondary: {
    backgroundColor: "#eff3fb",
    borderColor: "#cbd6eb",
    borderWidth: 1,
  },
  secondaryText: { color: "#214c9b" },
  disabled: { opacity: 0.45 },
  pressed: { opacity: 0.75 },
  error: { fontSize: 15, color: "#a82b32", lineHeight: 23 },
  notice: { padding: 16, backgroundColor: "#fff1ef", gap: 10 },
  link: {
    color: "#2256c4",
    fontWeight: "600",
    fontSize: 15,
    paddingVertical: 6,
  },
  tabs: { flexDirection: "row", backgroundColor: "white", padding: 8, gap: 2 },
  tab: { flex: 1, paddingVertical: 12, alignItems: "center", borderRadius: 8 },
  tabText: { fontSize: 13, color: "#5c687b", fontWeight: "600" },
  activeTab: { backgroundColor: "#e8effe" },
  activeTabText: { color: "#2256c4" },
  party: {
    backgroundColor: "white",
    padding: 17,
    marginBottom: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#dce1ea",
  },
  partyName: { fontSize: 16, color: "#17263b", fontWeight: "600" },
  yearList: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  year: {
    padding: 14,
    borderWidth: 1,
    borderColor: "#cbd6eb",
    borderRadius: 9,
  },
  actions: { gap: 10 },
  amount: { fontSize: 29, fontWeight: "800", color: "#173b82" },
  status: { fontWeight: "700", fontSize: 17, color: "#2256c4" },
});
