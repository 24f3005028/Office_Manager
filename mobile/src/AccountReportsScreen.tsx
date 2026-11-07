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
  AppState,
  FlatList,
  Modal,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { todayIndia } from "./api";
import {
  AccountGroup,
  AccountMode,
  AccountOptions,
  AccountReport,
  BalanceView,
  LedgerAccount,
  accountDateError,
  accountReportLabel,
  accountReportRunning,
  currentAccountYear,
  formatAccountMoney,
} from "./accountModel";
import DateField from "./DateField";
import {
  Button,
  Heading,
  Icon,
  Note,
  displayDate,
  palette,
  styles,
} from "./ui";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
export type AccountReportsHandle = { back: () => boolean };
const amounts = formatAccountMoney;
const statusLabel: Record<string, string> = {
  queued: "Waiting for the office",
  warning: "Checking whether BUSY is in use",
  generating: "Preparing report",
  ready: "Ready",
  failed: "Could not create report",
  cancelled: "Paused by the office",
};

export default forwardRef<
  AccountReportsHandle,
  {
    api: Api;
    visible: boolean;
    pdfActions: (id: string, label: string) => React.ReactNode;
  }
>(function AccountReportsScreen({ api, visible, pdfActions }, ref) {
  const [mode, setMode] = useState<AccountMode>("ledger");
  const [options, setOptions] = useState<AccountOptions>(() =>
    currentAccountYear(todayIndia()),
  );
  const [from, setFrom] = useState(options.start_date),
    [through, setThrough] = useState(options.as_of),
    [asOf, setAsOf] = useState(options.as_of);
  const [groups, setGroups] = useState<AccountGroup[]>([]),
    [selectedGroups, setSelectedGroups] = useState<
      Partial<Record<AccountMode, AccountGroup | null>>
    >({});
  const group = selectedGroups[mode] ?? null;
  const setGroup = (next: AccountGroup | null) =>
    setSelectedGroups((old) => ({ ...old, [mode]: next }));
  const [picker, setPicker] = useState(false),
    [groupQuery, setGroupQuery] = useState("");
  const [query, setQuery] = useState(""),
    [accounts, setAccounts] = useState<LedgerAccount[]>([]),
    [account, setAccount] = useState<LedgerAccount | null>(null);
  const [reports, setReports] = useState<
      Partial<Record<AccountMode, AccountReport>>
    >({}),
    [history, setHistory] = useState<AccountReport[]>([]);
  const [balances, setBalances] = useState<BalanceView | null>(null),
    [balanceQuery, setBalanceQuery] = useState("");
  const [balancePage, setBalancePage] = useState(0);
  const [busy, setBusy] = useState(false),
    [searching, setSearching] = useState(false),
    [error, setError] = useState("");
  const datesChanged = useRef({ ledger: false, group_balances: false }),
    requestKey = useRef<string | null>(null),
    scroll = useRef<React.ComponentRef<typeof ScrollView>>(null);
  const report = reports[mode] ?? null;
  const running = accountReportRunning(report);
  const run = useCallback(async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "The office request could not finish.",
      );
    } finally {
      setBusy(false);
    }
  }, []);
  const remember = useCallback((row: AccountReport) => {
    setReports((old) => ({ ...old, [row.report_kind]: row }));
    setHistory((old) => [row, ...old.filter((item) => item.id !== row.id)]);
  }, []);
  useEffect(() => {
    if (!visible) return;
    let stopped = false;
    void run(async () => {
      const [settings, items, recent] = await Promise.all([
        api<AccountOptions>("/account-reports/options"),
        api<AccountGroup[]>("/account-groups"),
        api<AccountReport[]>(`/account-reports?kind=${mode}`),
      ]);
      if (stopped) return;
      setOptions(settings);
      setGroups(items);
      setHistory(recent);
      if (!datesChanged.current.ledger) {
        setFrom(settings.start_date);
        setThrough(settings.as_of);
      }
      if (!datesChanged.current.group_balances) setAsOf(settings.as_of);
      const pending = recent.find((row) => accountReportRunning(row));
      if (pending) remember(pending);
    });
    return () => {
      stopped = true;
    };
  }, [api, visible, mode, run, remember]);
  useEffect(() => {
    if (!visible || mode !== "ledger" || account || report) return;
    let stopped = false;
    setSearching(true);
    const timer = setTimeout(() => {
      void api<LedgerAccount[]>(
        `/accounts?q=${encodeURIComponent(query)}${group ? `&group_id=${group.id}` : ""}`,
      )
        .then((rows) => {
          if (!stopped) setAccounts(rows);
        })
        .catch((e) => {
          if (!stopped)
            setError(
              e instanceof Error ? e.message : "Could not load accounts.",
            );
        })
        .finally(() => {
          if (!stopped) setSearching(false);
        });
    }, 220);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [api, visible, mode, query, group?.id, account, report?.id]);
  useEffect(() => {
    if (!visible || !report || !running) return;
    let stopped = false,
      timer: ReturnType<typeof setTimeout>;
    const check = async () => {
      try {
        const row = await api<AccountReport>(`/reports/${report.id}`);
        if (!stopped) {
          remember(row);
          if (accountReportRunning(row)) timer = setTimeout(check, 2000);
        }
      } catch (e) {
        if (!stopped) {
          setError(
            e instanceof Error
              ? e.message
              : "Could not check progress. Tap Refresh.",
          );
        }
      }
    };
    timer = setTimeout(check, 1000);
    const listener = AppState.addEventListener("change", (state) => {
      if (state === "active") {
        clearTimeout(timer);
        void check();
      }
    });
    return () => {
      stopped = true;
      clearTimeout(timer);
      listener.remove();
    };
  }, [api, visible, report?.id, running, remember]);
  useEffect(() => {
    setBalances(null);
    setBalanceQuery("");
    if (!visible || mode !== "group_balances" || report?.status !== "ready")
      return;
    let stopped = false;
    void run(async () => {
      const data = await api<BalanceView>(`/reports/${report.id}/balances`);
      if (!stopped) setBalances(data);
    });
    return () => {
      stopped = true;
    };
  }, [api, visible, mode, report?.id, report?.status, run]);
  function newReport() {
    setReports((old) => {
      const next = { ...old };
      delete next[mode];
      return next;
    });
    requestKey.current = null;
    setError("");
  }
  useImperativeHandle(
    ref,
    () => ({
      back: () => {
        if (busy) return true;
        if (picker) {
          setPicker(false);
          return true;
        }
        if (report) {
          if (accountReportRunning(report)) return false;
          newReport();
          return true;
        }
        if (account) {
          setAccount(null);
          requestKey.current = null;
          return true;
        }
        return false;
      },
    }),
    [busy, picker, report, account, mode],
  );
  function switchMode(next: AccountMode) {
    setMode(next);
    setError("");
    requestKey.current = null;
    scroll.current?.scrollTo({ y: 0, animated: false });
  }
  useEffect(() => {
    setBalancePage(0);
  }, [balanceQuery, report?.id]);
  function generate() {
    const end = mode === "ledger" ? through : asOf;
    const message = accountDateError(mode, from, end, options);
    if (message) {
      setError(message);
      return;
    }
    const name = mode === "ledger" ? account?.name : group?.name;
    if (!name) {
      setError(
        mode === "ledger" ? "Choose an account." : "Choose an account group.",
      );
      return;
    }
    void run(async () => {
      requestKey.current ??= `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      const body = mode === "ledger"
        ? { account_id: account!.id, start_date: from, end_date: through, request_key: requestKey.current }
        : { group_id: group!.id, as_of: asOf, request_key: requestKey.current };
      const row = await api<AccountReport>(
        `/account-reports/${mode === "ledger" ? "ledger" : "group-balances"}`, body,
      );
      remember(row);
      requestKey.current = null;
    });
  }
  async function copyBalanceAccount(name: string) {
    await run(async () => {
      const matches = await api<LedgerAccount[]>(
        `/accounts?q=${encodeURIComponent(name)}`,
      );
      const found = matches.find(
        (row) => row.name.trim().toLowerCase() === name.trim().toLowerCase(),
      );
      if (!found)
        throw Error(
          "This account is missing from the saved list. Ask the office to import its latest account list.",
        );
      setAccount(found);
      setSelectedGroups((old) => ({
        ...old,
        ledger: groups.find((item) => item.id === found.group_id) ?? null,
      }));
      setFrom(options.start_date);
      setThrough(report?.as_of ?? options.as_of);
      datesChanged.current.ledger = true;
      setReports((old) => {
        const next = { ...old };
        delete next.ledger;
        return next;
      });
      switchMode("ledger");
    });
  }
  const shownBalances =
    balances?.accounts.filter((row) =>
      row.name.toLowerCase().includes(balanceQuery.trim().toLowerCase()),
    ) ?? [];
  const maxDate = new Date(options.as_of + "T23:59:00");
  return (
    <>
      <ScrollView
        ref={scroll}
        contentContainerStyle={styles.content}
        keyboardShouldPersistTaps="handled"
      >
        <Heading
          eyebrow="ACCOUNTS"
          title={mode === "ledger" ? "Copy account" : "Group closing balances"}
          subtitle={
            mode === "ledger"
              ? "A party’s ledger for the dates you choose."
              : "Each account’s closing balance, in one report."
          }
        />
        <View style={styles.yearList}>
          {(
            [
              ["ledger", "Copy account"],
              ["group_balances", "Group balances"],
            ] as const
          ).map(([key, label]) => (
            <Pressable
              key={key}
              accessibilityRole="tab"
              accessibilityState={{ selected: mode === key }}
              disabled={busy}
              onPress={() => switchMode(key)}
              style={[styles.year, mode === key && styles.yearActive]}
            >
              <Text
                style={[styles.yearText, mode === key && styles.yearTextActive]}
              >
                {label}
              </Text>
            </Pressable>
          ))}
        </View>
        {!!error && (
          <View
            accessibilityRole="alert"
            style={[styles.notice, { marginHorizontal: 0 }]}
          >
            <Text style={[styles.error, styles.grow]}>{error}</Text>
          </View>
        )}
        {busy && <YarnProgress color={palette.blue} />}
        {report ? (
          <>
            <View style={styles.card}>
              <View style={styles.sectionHead}>
                <Text style={[styles.cardTitle, styles.grow]}>
                  {report.party_name}
                </Text>
                <Icon
                  name={report.status === "ready" ? "check" : "history"}
                  color={
                    report.status === "ready" ? palette.teal : palette.blue
                  }
                />
              </View>
              <Text style={styles.muted}>
                {report.report_kind === "ledger"
                  ? `${displayDate(report.parameters.start_date!)} – ${displayDate(report.as_of)}`
                  : `As of ${displayDate(report.as_of)}`}
              </Text>
              <Text
                style={
                  report.status === "failed" ? styles.error : styles.status
                }
              >
                {statusLabel[report.status] ?? report.status}
              </Text>
              {running && <YarnProgress label={statusLabel[report.status]} />}
              {!!report.error && (
                <Text style={styles.error}>{report.error}</Text>
              )}
              {report.status === "ready" &&
                pdfActions(report.id, accountReportLabel(report))}
              {report.status === "ready" &&
                mode === "group_balances" &&
                !balances &&
                !busy && (
                  <Button
                    title="Load balances"
                    secondary
                    onPress={() =>
                      void run(async () =>
                        setBalances(
                          await api<BalanceView>(
                            `/reports/${report.id}/balances`,
                          ),
                        ),
                      )
                    }
                  />
                )}
              {running && (
                <Button
                  title="Refresh progress"
                  secondary
                  disabled={busy}
                  onPress={() =>
                    void run(async () =>
                      remember(
                        await api<AccountReport>(`/reports/${report.id}`),
                      ),
                    )
                  }
                />
              )}
              <Button
                title={
                  report.status === "ready"
                    ? "Choose another report"
                    : "Back to report options"
                }
                secondary
                onPress={newReport}
                disabled={busy || running}
              />
            </View>
            {balances && (
              <>
                <View style={styles.card}>
                  <Text style={styles.sectionTitle}>
                    {balances.account_count} accounts
                  </Text>
                  <View style={styles.row}>
                    <View style={styles.grow}>
                      <Text style={styles.label}>Debit total</Text>
                      <Text style={styles.sectionTitle}>
                        {amounts(balances.debit_total)}
                      </Text>
                    </View>
                    <View style={styles.grow}>
                      <Text style={styles.label}>Credit total</Text>
                      <Text style={styles.sectionTitle}>
                        {amounts(balances.credit_total)}
                      </Text>
                    </View>
                  </View>
                </View>
                <View style={styles.searchBox}>
                  <Icon name="search" />
                  <TextInput
                    style={styles.searchInput}
                    value={balanceQuery}
                    onChangeText={setBalanceQuery}
                    placeholder="Search account in report"
                    accessibilityLabel="Search closing balances"
                  />
                </View>
                {shownBalances
                  .slice(balancePage * 50, (balancePage + 1) * 50)
                  .map((row) => (
                    <Pressable
                      key={row.name}
                      accessibilityRole="button"
                      accessibilityLabel={`${row.name}, ${amounts(row.balance)} ${row.side}. Open copy account.`}
                      disabled={busy}
                      onPress={() => void copyBalanceAccount(row.name)}
                      style={styles.party}
                    >
                      <View style={styles.grow}>
                        <Text style={styles.historyTitle}>{row.name}</Text>
                        <Text style={styles.historyMeta}>
                          Tap for copy account
                        </Text>
                      </View>
                      <Text
                        style={[
                          styles.status,
                          {
                            maxWidth: "50%",
                            flexShrink: 1,
                            textAlign: "right",
                          },
                        ]}
                      >
                        {amounts(row.balance)} {row.side}
                      </Text>
                    </Pressable>
                  ))}
                {shownBalances.length > 50 && (
                  <View style={styles.row}>
                    <View style={styles.grow}>
                      <Button
                        title="Previous"
                        secondary
                        disabled={balancePage === 0}
                        onPress={() => setBalancePage((page) => page - 1)}
                      />
                    </View>
                    <Text style={styles.noteText}>
                      {balancePage + 1} / {Math.ceil(shownBalances.length / 50)}
                    </Text>
                    <View style={styles.grow}>
                      <Button
                        title="Next"
                        secondary
                        disabled={
                          (balancePage + 1) * 50 >= shownBalances.length
                        }
                        onPress={() => setBalancePage((page) => page + 1)}
                      />
                    </View>
                  </View>
                )}
                {!shownBalances.length && (
                  <Text style={styles.muted}>
                    {balances.account_count
                      ? "No matching accounts."
                      : "No non-zero closing balances for this group."}
                  </Text>
                )}
              </>
            )}
          </>
        ) : (
          <>
            <View style={styles.card}>
              <Text style={styles.label}>
                {mode === "ledger" ? "Filter by group" : "Account group"}
              </Text>
              <Button
                title={
                  group?.name ??
                  (mode === "ledger" ? "All account groups" : "Choose a group")
                }
                secondary
                icon="chevron"
                disabled={busy}
                onPress={() => {
                  setGroupQuery("");
                  setPicker(true);
                }}
              />
              {mode === "ledger" && account ? (
                <View style={{ gap: 10 }}>
                  <Text style={styles.cardTitle}>{account.name}</Text>
                  <Text style={styles.noteText}>
                    {account.group_name ?? "Saved account"}
                  </Text>
                  <Button
                    title="Change account"
                    secondary
                    disabled={busy}
                    onPress={() => setAccount(null)}
                  />
                </View>
              ) : mode === "ledger" ? (
                <>
                  <View style={styles.searchBox}>
                    <Icon name="search" />
                    <TextInput
                      style={styles.searchInput}
                      value={query}
                      onChangeText={setQuery}
                      placeholder="Search party or account"
                      accessibilityLabel="Search ledger accounts"
                      autoCorrect={false}
                      editable={!busy}
                    />
                  </View>
                  {searching && <YarnProgress color={palette.blue} />}
                  {accounts.slice(0, query.trim() ? 100 : 20).map((row) => (
                    <Pressable
                      key={row.id}
                      accessibilityRole="button"
                      disabled={busy}
                      onPress={() => {
                        setAccount(row);
                        requestKey.current = null;
                        scroll.current?.scrollTo({ y: 0, animated: true });
                      }}
                      style={[styles.party, { marginBottom: 0 }]}
                    >
                      <View style={styles.grow}>
                        <Text style={styles.historyTitle}>{row.name}</Text>
                        <Text style={styles.historyMeta}>
                          {row.group_name ?? "Saved account"}
                        </Text>
                      </View>
                      <Icon name="chevron" size={17} />
                    </Pressable>
                  ))}
                  {!query.trim() && accounts.length > 20 && (
                    <Text style={styles.noteText}>
                      Search by name to find any account in the list.
                    </Text>
                  )}
                  {!searching && !accounts.length && (
                    <Text style={styles.muted}>No matching accounts.</Text>
                  )}
                </>
              ) : null}
              {(mode === "group_balances" || account) && (
                <>
                  <View style={styles.sectionHead}>
                    <Text style={styles.sectionTitle}>Report dates</Text>
                    <Pressable
                      accessibilityRole="button"
                      style={styles.textButton}
                      disabled={busy}
                      onPress={() => {
                        if (mode === "ledger") {
                          setFrom(options.start_date);
                          setThrough(options.as_of);
                        } else setAsOf(options.as_of);
                        datesChanged.current[mode] = false;
                      }}
                    >
                      <Text style={styles.link}>
                        Current FY {options.financial_year}
                      </Text>
                    </Pressable>
                  </View>
                  {mode === "ledger" ? (
                    <View style={styles.row}>
                      <DateField
                        label="From"
                        disabled={busy}
                        value={from}
                        onChange={(v) => {
                          setFrom(v);
                          datesChanged.current.ledger = true;
                        }}
                        maximumDate={maxDate}
                      />
                      <DateField
                        label="Through"
                        disabled={busy}
                        value={through}
                        onChange={(v) => {
                          setThrough(v);
                          datesChanged.current.ledger = true;
                        }}
                        maximumDate={maxDate}
                      />
                    </View>
                  ) : (
                    <DateField
                      label="Closing balances as of"
                      disabled={busy}
                      value={asOf}
                      onChange={(v) => {
                        setAsOf(v);
                        datesChanged.current.group_balances = true;
                      }}
                      minimumDate={new Date(options.start_date + "T00:00:00")}
                      maximumDate={maxDate}
                    />
                  )}
                  <Button
                    title={
                      mode === "ledger"
                        ? "Create copy account"
                        : "Get closing balances"
                    }
                    icon="file"
                    disabled={busy || (mode === "group_balances" && !group)}
                    onPress={generate}
                  />
                </>
              )}
            </View>
            {history.length > 0 && (
              <>
                <Text style={styles.sectionTitle}>
                  Recent {mode === "ledger" ? "copies" : "group reports"}
                </Text>
                {history.slice(0, 5).map((row) => (
                  <Pressable
                    key={row.id}
                    accessibilityRole="button"
                    disabled={busy}
                    onPress={() => remember(row)}
                    style={styles.historyItem}
                  >
                    <Icon name="file" />
                    <View style={styles.grow}>
                      <Text style={styles.historyTitle}>{row.party_name}</Text>
                      <Text style={styles.historyMeta}>
                        {displayDate(row.as_of)} ·{" "}
                        {statusLabel[row.status] ?? row.status}
                      </Text>
                    </View>
                    <Icon name="chevron" size={17} />
                  </Pressable>
                ))}
              </>
            )}
            <Note details>
              Fresh reports use BUSY on the office computer. The office gets
              five seconds to pause if someone is working. PDFs stay available
              for 48 hours.
            </Note>
          </>
        )}
      </ScrollView>
      <Modal
        visible={picker}
        animationType="slide"
        onRequestClose={() => setPicker(false)}
      >
        <SafeAreaView style={styles.root}>
          <View style={styles.header}>
            <Text style={[styles.cardTitle, styles.grow]}>
              Choose account group
            </Text>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Close groups"
              onPress={() => setPicker(false)}
              style={styles.menuButton}
            >
              <Icon name="close" />
            </Pressable>
          </View>
          <FlatList
            contentContainerStyle={styles.content}
            keyboardShouldPersistTaps="handled"
            ListHeaderComponent={
              <View style={{ gap: 14 }}>
                <View style={styles.searchBox}>
                  <Icon name="search" />
                  <TextInput
                    style={styles.searchInput}
                    value={groupQuery}
                    onChangeText={setGroupQuery}
                    placeholder="Search groups"
                    accessibilityLabel="Search account groups"
                    autoCorrect={false}
                  />
                </View>
                {mode === "ledger" && (
                  <Button
                    title="All account groups"
                    secondary
                    onPress={() => {
                      setGroup(null);
                      setAccount(null);
                      setPicker(false);
                    }}
                  />
                )}
              </View>
            }
            data={groups.filter((row) =>
              row.name.toLowerCase().includes(groupQuery.toLowerCase()),
            )}
            keyExtractor={(row) => row.id}
            renderItem={({ item }) => (
              <Pressable
                accessibilityRole="button"
                onPress={() => {
                  setGroup(item);
                  if (mode === "ledger") setAccount(null);
                  requestKey.current = null;
                  setPicker(false);
                }}
                style={styles.party}
              >
                <View style={styles.grow}>
                  <Text style={styles.historyTitle}>{item.name}</Text>
                  <Text style={styles.historyMeta}>
                    {item.account_count} accounts in saved list
                  </Text>
                </View>
                <Icon
                  name={group?.id === item.id ? "check" : "chevron"}
                  size={18}
                />
              </Pressable>
            )}
          />
        </SafeAreaView>
      </Modal>
    </>
  );
});
