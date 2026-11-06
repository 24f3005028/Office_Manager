import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  BackHandler,
  FlatList,
  KeyboardAvoidingView,
  Keyboard,
  Platform,
  Pressable,
  ScrollView,
  StatusBar,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import OfficeToolsScreen, { OfficeToolsHandle } from "./src/OfficeToolsScreen";
import InviteManager from "./src/InviteManager";
import TasksScreen, { TasksHandle } from "./src/TasksScreen";
import DateField from "./src/DateField";
import NavigationDrawer, { NavigationScreen } from "./src/NavigationDrawer";
import AllOutstandingScreen, {
  AllOutstandingHandle,
} from "./src/AllOutstandingScreen";
import {
  SESSION_KEY,
  stopTaskReminders,
  syncTaskReminders,
} from "./src/taskReminders";
import * as Notifications from "expo-notifications";
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
import {
  Button,
  displayDate,
  Heading,
  Icon,
  initials,
  Logo,
  Note,
  palette,
  styles,
  TaskTile,
  Steps,
} from "./src/ui";

const statusText: Record<string, string> = {
  queued: "Waiting for the office…",
  warning: "Checking whether someone is using BUSY…",
  generating: "Creating your statement…",
  ready: "Statement ready",
  cancelled: "Someone is using BUSY",
  failed: "Report could not be created",
};
type Screen = NavigationScreen;
const errorText = (error: unknown) =>
  error instanceof Error
    ? error.message
    : "Something went wrong. Please try again.";
function OfficeApp() {
  const [session, setSession] = useState<Session | null>(null),
    [restoring, setRestoring] = useState(true);
  const [url, setUrl] = useState(process.env.EXPO_PUBLIC_OFFICE_URL ?? ""),
    [code, setCode] = useState(""),
    [countryCode, setCountryCode] = useState("91"),
    [mobileNumber, setMobileNumber] = useState(""),
    [person, setPerson] = useState<Person | null>(null);
  const [screen, setScreen] = useState<Screen>("home"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [query, setQuery] = useState(""),
    [parties, setParties] = useState<Party[]>([]),
    [searching, setSearching] = useState(false),
    [party, setParty] = useState<Party | null>(null);
  const [asOf, setAsOf] = useState(todayIndia()),
    [advanced, setAdvanced] = useState(false),
    [report, setReport] = useState<Report | null>(null);
  const [years, setYears] = useState<string[]>([]),
    [year, setYear] = useState("26-27"),
    [bill, setBill] = useState(""),
    [invoices, setInvoices] = useState<Invoice[] | null>(null);
  const [history, setHistory] = useState<Report[]>([]);
  const [activityTab, setActivityTab] = useState<"statements" | "office">(
    "statements",
  );
  const officeTools = useRef<OfficeToolsHandle>(null);
  const taskScreen = useRef<TasksHandle>(null);
  const allScreen = useRef<AllOutstandingHandle>(null);
  const [allSelected, setAllSelected] = useState<Report | null>(null);
  const onAllReport = useCallback(
    (row: Report) =>
      setHistory((rows) => [row, ...rows.filter((item) => item.id !== row.id)]),
    [],
  );
  const tasksFrom = useRef<Screen>("home");
  const accountFrom = useRef<Screen>("home");
  const statementFrom = useRef<Screen>("home");
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
    void syncTaskReminders().catch(() => {});
    const foreground = AppState.addEventListener("change", (state) => {
      if (state === "active") void syncTaskReminders().catch(() => {});
    });
    if (Platform.OS === "web") return () => foreground.remove();
    const showTasks = () => {
      tasksFrom.current = "home";
      setScreen("tasks");
      void Notifications.clearLastNotificationResponseAsync().catch(() => {});
    };
    const response = Notifications.addNotificationResponseReceivedListener(
      (event) => {
        if (event.notification.request.content.data?.taskId) showTasks();
      },
    );
    void Notifications.getLastNotificationResponseAsync()
      .then((event) => {
        if (event?.notification.request.content.data?.taskId) showTasks();
      })
      .catch(() => {});
    return () => {
      foreground.remove();
      response.remove();
    };
  }, [session]);
  useEffect(() => {
    if (!session) return;
    void api<Person>("/me")
      .then(async (current) => {
        setPerson(current);
        const rows = await api<Report[]>("/reports");
        setHistory(rows);
        const pending = rows.find(
          (row) =>
            row.party_id !== "all-accounts" &&
            ["queued", "warning", "generating"].includes(row.status),
        );
        if (pending) setReport(pending);
        setAllSelected(
          rows.find((row) => row.party_id === "all-accounts") ?? null,
        );
      })
      .catch((reason) => setError(errorText(reason)));
  }, [session, api]);
  useEffect(() => {
    if (!session || screen !== "outstanding") return;
    const revision = ++searchRevision.current;
    setSearching(true);
    const timer = setTimeout(() => {
      void api<Party[]>(`/parties?q=${encodeURIComponent(query)}`)
        .then((rows) => {
          if (revision === searchRevision.current) setParties(rows);
        })
        .catch((reason) => {
          if (revision === searchRevision.current) setError(errorText(reason));
        })
        .finally(() => {
          if (revision === searchRevision.current) setSearching(false);
        });
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
      if (
        !/^[1-9][0-9]{0,3}$/.test(countryCode) ||
        !/^[0-9]{6,14}$/.test(mobileNumber) ||
        (countryCode === "91" && !/^[6-9][0-9]{9}$/.test(mobileNumber)) ||
        countryCode.length + mobileNumber.length > 15
      ) {
        throw new Error(
          "Check the country code and mobile number. For India, choose +91 and enter the 10-digit number without a leading 0.",
        );
      }
      const paired = await request<{ token: string; expires_at: string }>(
        base,
        "/pair",
        undefined,
        { invite_code: code.trim(), phone: countryCode + mobileNumber },
      );
      const next = { url: base, ...paired };
      await SecureStore.setItemAsync(SESSION_KEY, JSON.stringify(next));
      setCode("");
      setSession(next);
    });
  }
  async function open(next: Screen) {
    Keyboard.dismiss();
    setMenuOpen(false);
    setScreen(next);
    setError("");
    if (next === "history")
      await action(async () => setHistory(await api<Report[]>("/reports")));
    if (next === "invoices" && !years.length)
      await action(async () => {
        const data = await api<{ years: string[]; default: string | null }>(
          "/financial-years",
        );
        setYears(data.years);
        setYear(data.default ?? "26-27");
      });
  }
  function back() {
    if (menuOpen) {
      setMenuOpen(false);
      return true;
    }
    if (busy) return true;
    if (screen === "allOutstanding" && allScreen.current?.back()) return true;
    Keyboard.dismiss();
    setError("");
    if (screen === "tasks") {
      if (!taskScreen.current?.back()) setScreen(tasksFrom.current);
      return true;
    }
    if (
      (screen === "tools" ||
        (screen === "history" && activityTab === "office")) &&
      officeTools.current?.back()
    )
      return true;
    if (screen === "account") {
      setScreen(accountFrom.current);
      return true;
    }
    if (screen === "outstanding") {
      if (report) {
        if (!activeReport) {
          setReport(null);
          setParty(null);
        }
        setScreen(statementFrom.current);
        return true;
      }
      if (party) {
        setParty(null);
        return true;
      }
    }
    if (screen !== "home") {
      setScreen("home");
      return true;
    }
    return false;
  }
  useEffect(() => {
    if (!session) return;
    const listener = BackHandler.addEventListener("hardwareBackPress", back);
    return () => listener.remove();
  }, [screen, session, busy, report, party, activityTab, menuOpen]);
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
      const row = await api<Report>("/reports", {
        party_id: party.id,
        as_of: asOf,
        request_key: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      });
      statementFrom.current = "home";
      setReport(row);
      setHistory((rows) => [row, ...rows.filter((item) => item.id !== row.id)]);
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
    filename: string,
  ) {
    await action(async () => {
      if (!session) return;
      const directory = FileSystem.cacheDirectory;
      if (!directory) throw new Error("Phone storage is unavailable.");
      const folder = directory + `office-${id}/`;
      await FileSystem.makeDirectoryAsync(folder, { intermediates: true });
      const target = folder + filename;
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
            filename,
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
  function pdfActions(kind: "reports" | "invoices", id: string, label: string) {
    const filename =
      (label
        .replace(/[<>:"/\\|?*\x00-\x1f]/g, "-")
        .replace(/^[ .]+|[ .]+$/g, "")
        .slice(0, 140) || "Statement") + ".pdf";
    return (
      <View style={styles.actions}>
        <Button
          title="Open PDF"
          icon="file"
          disabled={busy}
          onPress={() => void getPdf(kind, id, "open", filename)}
        />
        <Button
          title="Send to my WhatsApp"
          icon="whatsapp"
          green
          disabled={busy || !person}
          onPress={() => sendToMe(kind, id)}
        />
        <View style={styles.smallActions}>
          {(
            [
              ["save", "download", "Download"],
              ["share", "share", "Share"],
            ] as const
          ).map(([mode, icon, title]) => (
            <Pressable
              key={mode}
              accessibilityRole="button"
              accessibilityState={{ disabled: busy }}
              disabled={busy}
              onPress={() => void getPdf(kind, id, mode, filename)}
              style={({ pressed }) => [
                styles.smallAction,
                busy && styles.disabled,
                pressed && styles.pressed,
              ]}
            >
              <Icon name={icon} size={18} />
              <Text style={styles.smallActionText}>{title}</Text>
            </Pressable>
          ))}
        </View>
      </View>
    );
  }
  function reportCard(row: Report) {
    const pending = ["queued", "warning", "generating"].includes(row.status);
    return (
      <View style={styles.card}>
        <View style={styles.row}>
          <View style={styles.tileIcon}>
            <Icon name="statement" />
          </View>
          <View style={styles.grow}>
            <Text style={styles.eyebrow}>PARTY STATEMENT</Text>
          </View>
          {row.status === "ready" && (
            <View style={styles.statusBadge}>
              <Icon name="check" color={palette.teal} size={13} />
              <Text style={styles.successText}>Ready</Text>
            </View>
          )}
        </View>
        <View style={{ gap: 6 }}>
          <Text style={styles.cardTitle}>{row.party_name}</Text>
          <Text style={styles.muted}>As of {displayDate(row.as_of)}</Text>
        </View>
        {pending && (
          <View style={styles.progress}>
            <ActivityIndicator size="large" color={palette.blue} />
            <Text style={styles.status}>{statusText[row.status]}</Text>
            <Text style={styles.emptyCopy}>
              The office is preparing your PDF. You can leave this screen and
              check Activity.
            </Text>
          </View>
        )}
        {!pending && row.status !== "ready" && (
          <Text style={styles.status}>
            {statusText[row.status] ?? row.status}
          </Text>
        )}
        {row.error && <Text style={styles.error}>{row.error}</Text>}
        {row.status === "ready" && (
          <>
            <View style={styles.amountBox}>
              <Text style={styles.amountLabel}>TOTAL OUTSTANDING</Text>
              <Text
                style={styles.amount}
                adjustsFontSizeToFit
                numberOfLines={1}
              >
                ₹
                {Number(row.details?.pending_amount ?? 0).toLocaleString(
                  "en-IN",
                  { minimumFractionDigits: 2, maximumFractionDigits: 2 },
                )}
              </Text>
            </View>
            {pdfActions("reports", row.id, row.party_name)}
            <Text style={styles.noteText}>
              Created{" "}
              {row.finished_at
                ? new Date(row.finished_at).toLocaleString("en-IN")
                : "just now"}
              . Available for 48 hours.
            </Text>
          </>
        )}
      </View>
    );
  }
  function historyRow(row: Report) {
    return (
      <Pressable
        key={row.id}
        accessibilityRole="button"
        accessibilityLabel={`View statement for ${row.party_name}`}
        disabled={busy}
        onPress={() => {
          if (row.party_id === "all-accounts") {
            setAllSelected({ ...row });
            setScreen("allOutstanding");
            return;
          }
          statementFrom.current = screen;
          setReport(row);
          setParty(null);
          setScreen("outstanding");
        }}
        style={({ pressed }) => [styles.historyItem, pressed && styles.pressed]}
      >
        <View style={styles.partyMark}>
          <Icon name={row.status === "ready" ? "file" : "history"} size={20} />
        </View>
        <View style={styles.grow}>
          <Text style={styles.historyTitle}>{row.party_name}</Text>
          <Text style={styles.historyMeta}>
            {displayDate(row.as_of)} ·{" "}
            {row.status === "ready"
              ? "PDF ready"
              : (statusText[row.status] ?? row.status)}
          </Text>
        </View>
        <Icon name="chevron" color={palette.muted} size={17} />
      </Pressable>
    );
  }
  function resetStatement() {
    setReport(null);
    setParty(null);
    setQuery("");
  }
  if (restoring)
    return (
      <View style={styles.loading}>
        <Logo large />
        <ActivityIndicator color={palette.blue} />
      </View>
    );
  return (
    <SafeAreaView style={styles.root}>
      <StatusBar barStyle="dark-content" />
      <KeyboardAvoidingView
        style={styles.screen}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View style={styles.header}>
          {session ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Open navigation menu"
              accessibilityState={{ expanded: menuOpen }}
              onPress={() => {
                Keyboard.dismiss();
                setMenuOpen(true);
              }}
              style={styles.menuButton}
            >
              <View style={styles.hamburgerLine} />
              <View style={styles.hamburgerLine} />
              <View style={styles.hamburgerLine} />
            </Pressable>
          ) : (
            <Logo />
          )}
          <View style={styles.headerText}>
            <Text style={styles.brand}>H.S. TRADERS</Text>
            <Text style={styles.brandSub}>Your office, wherever you are</Text>
          </View>
          {session && (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={
                screen === "account"
                  ? "Close account"
                  : "Your account and connection"
              }
              disabled={busy}
              onPress={() => {
                if (screen === "account") back();
                else {
                  accountFrom.current = screen;
                  void open("account");
                }
              }}
              style={styles.avatar}
            >
              {screen === "account" ? (
                <Icon name="close" size={19} />
              ) : (
                <Text style={styles.avatarText}>
                  {initials(person?.name ?? "HS")}
                </Text>
              )}
            </Pressable>
          )}
        </View>
        {error !== "" && (
          <View accessibilityRole="alert" style={styles.notice}>
            <Icon name="info" color="#a23932" size={20} />
            <Text style={[styles.error, styles.grow]}>{error}</Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Dismiss error"
              onPress={() => setError("")}
              style={styles.dismiss}
            >
              <Icon name="close" size={17} color="#a23932" />
            </Pressable>
          </View>
        )}
        {busy && (
          <ActivityIndicator
            color={palette.blue}
            style={{ marginTop: 10 }}
            accessibilityLabel="Working"
          />
        )}
        {!session ? (
          <ScrollView
            contentContainerStyle={styles.content}
            keyboardShouldPersistTaps="handled"
          >
            <View style={styles.welcome}>
              <Logo large />
              <Text style={styles.welcomeTitle}>
                {"The office.\nIn your pocket."}
              </Text>
              <Text style={styles.welcomeCopy}>
                Party statements and bill PDFs, ready whenever you need them.
              </Text>
            </View>
            <View style={styles.card}>
              <View style={styles.sectionHead}>
                <Text style={styles.sectionTitle}>Connect your phone</Text>
                <Icon name="shield" size={20} color={palette.teal} />
              </View>
              <Text style={styles.muted}>
                Turn on Tailscale and enter the invite from your office
                dashboard.
              </Text>
              <View>
                <Text style={styles.label}>Office address</Text>
                <TextInput
                  autoCapitalize="none"
                  autoCorrect={false}
                  keyboardType="url"
                  placeholder="https://your-office.ts.net"
                  value={url}
                  onChangeText={setUrl}
                  style={styles.input}
                  accessibilityLabel="Office HTTPS address"
                />
              </View>
              <View>
                <Text style={styles.label}>Your WhatsApp number</Text>
                <View style={styles.row}>
                  <View style={{ width: 105 }}>
                    <Text style={styles.noteText}>Country code</Text>
                    <View
                      style={[styles.searchBox, { paddingLeft: 12, gap: 2 }]}
                    >
                      <Text style={styles.muted}>+</Text>
                      <TextInput
                        value={countryCode}
                        onChangeText={(value) =>
                          setCountryCode(value.replace(/\D/g, "").slice(0, 4))
                        }
                        keyboardType="phone-pad"
                        maxLength={4}
                        style={styles.searchInput}
                        accessibilityLabel="Country calling code"
                        placeholder="91"
                      />
                    </View>
                  </View>
                  <View style={styles.grow}>
                    <Text style={styles.noteText}>Mobile number</Text>
                    <TextInput
                      value={mobileNumber}
                      onChangeText={(value) =>
                        setMobileNumber(value.replace(/\D/g, "").slice(0, 14))
                      }
                      keyboardType="phone-pad"
                      maxLength={14}
                      style={styles.input}
                      accessibilityLabel="Mobile number without country code"
                      placeholder="9876543210"
                    />
                  </View>
                </View>
                <Text style={[styles.noteText, { marginTop: 8 }]}>
                  Use the same WhatsApp number the office entered on your
                  invite.
                </Text>
              </View>
              <View>
                <Text style={styles.label}>Your invite code</Text>
                <TextInput
                  autoCapitalize="none"
                  autoCorrect={false}
                  secureTextEntry
                  value={code}
                  onChangeText={setCode}
                  placeholder="Paste your invite code"
                  style={styles.input}
                  accessibilityLabel="Invite code"
                />
              </View>
              <Button
                title="Connect to office"
                icon="arrow"
                disabled={
                  busy ||
                  !url.trim() ||
                  !code.trim() ||
                  !countryCode ||
                  !mobileNumber
                }
                onPress={() => void pairPhone()}
              />
            </View>
            <Note>
              Ask the owner for an invite in Mobile access. Each code works once
              and is valid for 15 minutes.
            </Note>
          </ScrollView>
        ) : (
          <View style={styles.screen}>
            {screen !== "home" && (
              <View style={styles.backRow}>
                <Pressable
                  accessibilityRole="button"
                  accessibilityLabel="Go back"
                  disabled={busy}
                  style={styles.backButton}
                  onPress={back}
                >
                  <Icon name="back" size={17} />
                  <Text style={styles.backLabel}>Back</Text>
                </Pressable>
              </View>
            )}
            {screen === "history" && (
              <View
                style={[
                  styles.smallActions,
                  { paddingHorizontal: 22, paddingTop: 12 },
                ]}
              >
                {(
                  [
                    ["statements", "Statements"],
                    ["office", "Office requests"],
                  ] as const
                ).map(([key, label]) => (
                  <Pressable
                    key={key}
                    accessibilityRole="tab"
                    accessibilityState={{ selected: activityTab === key }}
                    onPress={() => setActivityTab(key)}
                    style={[
                      styles.year,
                      styles.grow,
                      activityTab === key && styles.yearActive,
                    ]}
                  >
                    <Text
                      style={[
                        styles.yearText,
                        activityTab === key && styles.yearTextActive,
                      ]}
                    >
                      {label}
                    </Text>
                  </Pressable>
                ))}
              </View>
            )}
            {screen === "home" ? (
              <ScrollView contentContainerStyle={styles.content}>
                <Heading
                  eyebrow="YOUR WORKSPACE"
                  title={`Hello${person ? ", " + person.name.split(" ")[0] : ""}.`}
                  subtitle="Choose what you want to do."
                />
                <TaskTile
                  title="Outstanding statement"
                  subtitle="Choose a party and get their pending bills."
                  icon="statement"
                  disabled={busy}
                  onPress={() => void open("outstanding")}
                />
                <Pressable
                  accessibilityRole="button"
                  disabled={busy}
                  onPress={() => void open("invoices")}
                  style={({ pressed }) => [
                    styles.billTile,
                    pressed && styles.pressed,
                  ]}
                >
                  <View style={styles.tileIcon}>
                    <Icon name="search" size={25} />
                  </View>
                  <View style={styles.grow}>
                    <Text style={styles.tileTitle}>Find a bill</Text>
                    <Text style={styles.tileCopy}>
                      Enter a bill number to get its PDF.
                    </Text>
                  </View>
                  <Icon name="chevron" size={18} />
                </Pressable>
                <TaskTile
                  title="All accounts outstanding"
                  subtitle="Pending bills and totals for every party."
                  icon="statement"
                  disabled={busy}
                  onPress={() => void open("allOutstanding")}
                />
                <TaskTile
                  title="Office tools"
                  subtitle="Update Pouncha or send saved bill PDFs."
                  icon="calendar"
                  disabled={busy}
                  onPress={() => void open("tools")}
                />
                <TaskTile
                  title="Shared tasks"
                  subtitle="Office to-dos, due dates and reminders."
                  icon="check"
                  disabled={busy}
                  onPress={() => {
                    tasksFrom.current = "home";
                    void open("tasks");
                  }}
                />
                {person?.can_invite_users && (
                  <Button
                    title="Invite new users"
                    secondary
                    icon="share"
                    disabled={busy}
                    onPress={() => {
                      accountFrom.current = "home";
                      void open("account");
                    }}
                  />
                )}
                <View style={styles.sectionHead}>
                  <Text style={styles.sectionTitle}>Recent statements</Text>
                  <Pressable
                    accessibilityRole="button"
                    disabled={busy}
                    style={styles.textButton}
                    onPress={() => void open("history")}
                  >
                    <Text style={styles.link}>View all</Text>
                  </Pressable>
                </View>
                {history.length ? (
                  <View style={{ gap: 10 }}>
                    {history.slice(0, 2).map(historyRow)}
                  </View>
                ) : (
                  <View style={styles.card}>
                    <Text style={styles.muted}>
                      Your statements will appear here after your first request.
                    </Text>
                  </View>
                )}
                <Note>
                  Fresh statements use the office computer. The office can pause
                  a request if someone is working.
                </Note>
              </ScrollView>
            ) : screen === "outstanding" ? (
              <FlatList
                data={party || report ? [] : parties}
                keyExtractor={(row) => row.id}
                keyboardShouldPersistTaps="handled"
                contentContainerStyle={styles.content}
                ListHeaderComponent={
                  <View style={styles.listHeader}>
                    <Heading
                      eyebrow="OUTSTANDING BILLS"
                      title={report ? "Your statement" : "Choose a party"}
                      subtitle={
                        report
                          ? "Your report, straight from the office."
                          : "Search by name to get a pending-bill statement."
                      }
                    />
                    <Steps
                      labels={["Party", "Create", "PDF"]}
                      current={
                        report
                          ? report.status === "ready"
                            ? 2
                            : 1
                          : party
                            ? 1
                            : 0
                      }
                    />
                    {!report && !party && (
                      <>
                        <View style={styles.searchBox}>
                          <Icon name="search" size={20} color={palette.muted} />
                          <TextInput
                            style={styles.searchInput}
                            placeholder="Search party name…"
                            placeholderTextColor={palette.muted}
                            value={query}
                            editable={!busy}
                            onChangeText={setQuery}
                            autoCorrect={false}
                            accessibilityLabel="Search party"
                          />
                        </View>
                        <Text style={styles.eyebrow}>
                          {query ? "SEARCH RESULTS" : "PARTIES"}
                        </Text>
                      </>
                    )}
                    {party && !report && (
                      <View style={styles.card}>
                        <View style={styles.row}>
                          <View style={styles.partyMark}>
                            <Text style={styles.partyInitials}>
                              {initials(party.name)}
                            </Text>
                          </View>
                          <Text style={[styles.cardTitle, styles.grow]}>
                            {party.name}
                          </Text>
                        </View>
                        <View style={styles.divider} />
                        <View style={styles.row}>
                          <Icon
                            name="calendar"
                            color={palette.muted}
                            size={19}
                          />
                          <View style={styles.grow}>
                            <Text style={styles.label}>Statement as of</Text>
                            <Text style={styles.muted}>
                              {displayDate(asOf)}
                            </Text>
                          </View>
                          <Pressable
                            accessibilityRole="button"
                            disabled={busy}
                            style={styles.textButton}
                            onPress={() => setAdvanced(!advanced)}
                          >
                            <Text style={styles.link}>
                              {advanced ? "Done" : "Change"}
                            </Text>
                          </Pressable>
                        </View>
                        {advanced && (
                          <DateField
                            label="Statement status date"
                            value={asOf}
                            onChange={setAsOf}
                            disabled={busy}
                            maximumDate={new Date()}
                          />
                        )}
                        <Button
                          title="Create statement"
                          icon="arrow"
                          disabled={busy}
                          onPress={() => void generate()}
                        />
                        <Pressable
                          accessibilityRole="button"
                          disabled={busy}
                          style={styles.textButton}
                          onPress={() => setParty(null)}
                        >
                          <Text style={styles.link}>
                            Choose a different party
                          </Text>
                        </Pressable>
                      </View>
                    )}
                    {report && reportCard(report)}
                    {report && (
                      <Button
                        title="Get another statement"
                        icon="statement"
                        secondary
                        disabled={busy || activeReport}
                        onPress={resetStatement}
                      />
                    )}
                    {(party || report) && (
                      <Note>
                        Includes pending bills from 16 January 2025. Fresh
                        reports require the office PC to be online with BUSY
                        open.
                      </Note>
                    )}
                  </View>
                }
                renderItem={({ item }) => (
                  <Pressable
                    accessibilityRole="button"
                    disabled={busy}
                    onPress={() => {
                      setParty(item);
                      setReport(null);
                    }}
                    style={({ pressed }) => [
                      styles.party,
                      pressed && styles.pressed,
                    ]}
                  >
                    <View style={styles.partyMark}>
                      <Text style={styles.partyInitials}>
                        {initials(item.name)}
                      </Text>
                    </View>
                    <Text style={styles.partyName}>{item.name}</Text>
                    <Icon name="chevron" size={17} color={palette.muted} />
                  </Pressable>
                )}
                ListEmptyComponent={
                  !party && !report ? (
                    <View style={styles.empty}>
                      {searching ? (
                        <>
                          <ActivityIndicator color={palette.blue} />
                          <Text style={styles.emptyCopy}>Finding parties…</Text>
                        </>
                      ) : (
                        <>
                          <Icon name="search" color={palette.muted} size={32} />
                          <Text style={styles.emptyTitle}>
                            No parties to show
                          </Text>
                          <Text style={styles.emptyCopy}>
                            Try another spelling, or ask the office to update
                            the party list.
                          </Text>
                        </>
                      )}
                    </View>
                  ) : undefined
                }
              />
            ) : screen === "invoices" ? (
              <ScrollView
                contentContainerStyle={styles.content}
                keyboardShouldPersistTaps="handled"
              >
                <Heading
                  eyebrow="BILL PDFS"
                  title="Find a bill"
                  subtitle="Select the year, then enter your bill number."
                />
                <View style={styles.card}>
                  <View>
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
                          style={[
                            styles.year,
                            year === value && styles.yearActive,
                          ]}
                        >
                          <Text
                            style={[
                              styles.yearText,
                              year === value && styles.yearTextActive,
                            ]}
                          >
                            {value}
                          </Text>
                        </Pressable>
                      ))}
                    </View>
                  </View>
                  {!years.length && (
                    <Text style={styles.muted}>
                      No saved bill PDFs are available yet.
                    </Text>
                  )}
                  <View>
                    <Text style={styles.label}>Bill number</Text>
                    <TextInput
                      style={styles.input}
                      value={bill}
                      editable={!busy}
                      autoCapitalize="characters"
                      autoCorrect={false}
                      onChangeText={(value) => {
                        setBill(value);
                        setInvoices(null);
                      }}
                      placeholder="e.g. 74"
                      accessibilityLabel="Bill number"
                      returnKeyType="search"
                      onSubmitEditing={() => {
                        if (!busy && bill.trim()) void findBill();
                      }}
                    />
                    <Text style={[styles.noteText, { marginTop: 9 }]}>
                      You can also enter a full number: HST/L/26-27/74
                    </Text>
                  </View>
                  <Button
                    title="Find bill PDF"
                    icon="search"
                    disabled={busy || !bill.trim() || !years.length}
                    onPress={() => void findBill()}
                  />
                </View>
                {invoices === null && (
                  <Note icon="file">
                    Finds saved invoices from the office archive. This does not
                    operate BUSY.
                  </Note>
                )}
                {invoices?.length === 0 && (
                  <View style={styles.empty}>
                    <Icon name="search" color={palette.muted} size={34} />
                    <Text style={styles.emptyTitle}>Bill not found</Text>
                    <Text style={styles.emptyCopy}>
                      Check the year and bill number, or ask the office to save
                      a copy.
                    </Text>
                  </View>
                )}
                {Boolean(invoices?.length) && (
                  <Text style={styles.eyebrow}>
                    {invoices!.length === 1
                      ? "YOUR BILL"
                      : "MATCHING BILLS · CHOOSE THE SERIES"}
                  </Text>
                )}
                {invoices?.map((row) => (
                  <View key={row.file_id} style={styles.card}>
                    <View style={styles.row}>
                      <View style={styles.tileIcon}>
                        <Icon name="file" />
                      </View>
                      <View style={styles.grow}>
                        <Text style={styles.cardTitle}>{row.bill_number}</Text>
                        <Text style={styles.muted}>
                          {displayDate(row.date)}
                        </Text>
                      </View>
                    </View>
                    <Text style={styles.sectionTitle}>{row.party_name}</Text>
                    {row.conflicting_copies ? (
                      <Text style={styles.error}>
                        Different PDFs exist for this bill. Ask the office to
                        resolve them before downloading or sending.
                      </Text>
                    ) : !row.party_name ||
                      row.party_name === "See PDF for party name" ? (
                      <Text style={styles.error}>
                        The party name could not be read. Ask the office to
                        check this bill PDF.
                      </Text>
                    ) : (
                      pdfActions(
                        "invoices",
                        row.file_id,
                        row.bill_number + " - " + row.party_name,
                      )
                    )}
                  </View>
                ))}
              </ScrollView>
            ) : screen === "history" && activityTab === "statements" ? (
              <ScrollView contentContainerStyle={styles.content}>
                <Heading
                  eyebrow="ACTIVITY"
                  title="Your statements"
                  subtitle="Open a report to view, download or send its PDF."
                />
                <View style={styles.sectionHead}>
                  <Text style={styles.sectionTitle}>
                    {history.length}{" "}
                    {history.length === 1 ? "statement" : "statements"}
                  </Text>
                  <Pressable
                    accessibilityRole="button"
                    disabled={busy}
                    style={styles.textButton}
                    onPress={() => void open("history")}
                  >
                    <Text style={styles.link}>Refresh</Text>
                  </Pressable>
                </View>
                {history.map(historyRow)}
                {!history.length && (
                  <View style={styles.empty}>
                    <Icon name="history" size={38} color={palette.muted} />
                    <Text style={styles.emptyTitle}>A fresh start</Text>
                    <Text style={styles.emptyCopy}>
                      Statements you request will appear here.
                    </Text>
                    <Button
                      title="Get your first statement"
                      onPress={() => void open("outstanding")}
                    />
                  </View>
                )}
                <Note icon="info">
                  PDFs are available for 48 hours. Request a new statement
                  whenever you need updated figures.
                </Note>
              </ScrollView>
            ) : screen === "tools" ||
              screen === "history" ||
              screen === "tasks" ||
              screen === "allOutstanding" ? null : (
              <ScrollView contentContainerStyle={styles.content}>
                <Heading
                  eyebrow="YOUR ACCOUNT"
                  title="Office access"
                  subtitle="Your phone’s connection to H.S. Traders."
                />
                <View style={styles.card}>
                  <View style={styles.row}>
                    <View style={styles.avatar}>
                      <Text style={styles.avatarText}>
                        {initials(person?.name ?? "HS")}
                      </Text>
                    </View>
                    <View style={styles.grow}>
                      <Text style={styles.cardTitle}>
                        {person?.name ?? "Office user"}
                      </Text>
                      <Text style={styles.muted}>
                        +{person?.phone ?? "Approved phone"}
                      </Text>
                    </View>
                  </View>
                  <View style={styles.divider} />
                  <Text style={styles.label}>Private office address</Text>
                  <Text selectable style={styles.muted}>
                    {session.url}
                  </Text>
                  <Button
                    title="Check office connection"
                    icon="shield"
                    secondary
                    disabled={busy}
                    onPress={() =>
                      void action(async () => {
                        setPerson(await api<Person>("/me"));
                        Alert.alert(
                          "Office connected",
                          "Your private connection is working.",
                        );
                      })
                    }
                  />
                </View>
                {person?.can_invite_users && <InviteManager api={api} />}
                <Note>
                  Keep Tailscale connected on your phone. You can use the app
                  from anywhere with internet access.
                </Note>
                <View style={styles.card}>
                  <Text style={styles.sectionTitle}>
                    Need a fresh statement?
                  </Text>
                  <Text style={styles.muted}>
                    The office PC must be powered on, online and unlocked, with
                    BUSY logged in. Someone at the office can cancel a request
                    before it starts.
                  </Text>
                </View>
                <Pressable
                  accessibilityRole="button"
                  disabled={busy}
                  style={[styles.textButton, { alignSelf: "center" }]}
                  onPress={() =>
                    Alert.alert(
                      "Disconnect this phone?",
                      "You will need a new invite to connect again.",
                      [
                        { text: "Cancel", style: "cancel" },
                        {
                          text: "Disconnect",
                          style: "destructive",
                          onPress: () =>
                            void action(async () => {
                              try {
                                await api("/logout", {});
                              } finally {
                                await stopTaskReminders().catch(() => {});
                                await SecureStore.deleteItemAsync(SESSION_KEY);
                                setSession(null);
                                setPerson(null);
                                setReport(null);
                                setHistory([]);
                                setParties([]);
                                setInvoices(null);
                                setScreen("home");
                              }
                            }),
                        },
                      ],
                    )
                  }
                >
                  <Text style={styles.dangerText}>Disconnect this phone</Text>
                </Pressable>
                <Text style={[styles.noteText, { textAlign: "center" }]}>
                  H.S. Traders Office · Version 1.4.1
                </Text>
              </ScrollView>
            )}
            <View
              style={[
                styles.screen,
                {
                  display:
                    screen === "tools" ||
                    (screen === "history" && activityTab === "office")
                      ? "flex"
                      : "none",
                },
              ]}
            >
              <OfficeToolsScreen
                ref={officeTools}
                api={api}
                visible={
                  screen === "tools" ||
                  (screen === "history" && activityTab === "office")
                }
                mode={screen === "history" ? "history" : "tools"}
                onShowActivity={() => {
                  setActivityTab("office");
                  void open("history");
                }}
                onShowTasks={() => {
                  tasksFrom.current = "tools";
                  void open("tasks");
                }}
              />
            </View>
            <View
              style={[
                styles.screen,
                { display: screen === "tasks" ? "flex" : "none" },
              ]}
            >
              <TasksScreen
                ref={taskScreen}
                api={api}
                person={person}
                visible={screen === "tasks"}
              />
            </View>
            <View
              style={[
                styles.screen,
                { display: screen === "allOutstanding" ? "flex" : "none" },
              ]}
            >
              <AllOutstandingScreen
                ref={allScreen}
                api={api}
                visible={screen === "allOutstanding"}
                selected={allSelected}
                onReport={onAllReport}
                pdfActions={(id) =>
                  pdfActions("reports", id, "All accounts outstanding")
                }
              />
            </View>
          </View>
        )}
        {session && (
          <NavigationDrawer
            visible={menuOpen}
            current={screen}
            name={person?.name ?? "Office user"}
            disabled={busy}
            onClose={() => setMenuOpen(false)}
            onSelect={(next) => {
              if (next === "account" && screen !== "account")
                accountFrom.current = screen;
              void open(next);
            }}
          />
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
