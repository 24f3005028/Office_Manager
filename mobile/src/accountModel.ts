export type AccountMode = "ledger" | "group_balances";
export function formatAccountMoney(value: string): string {
  if (!/^\d+(?:\.\d{1,2})?$/.test(value)) return "Unavailable";
  const [whole, fraction = ""] = value.split(".");
  const integer =
    whole.length > 3
      ? whole.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",") +
        "," +
        whole.slice(-3)
      : whole;
  return `₹${integer}.${fraction.padEnd(2, "0")}`;
}
export type AccountGroup = { id: string; name: string; account_count: number };
export type LedgerAccount = {
  id: string;
  name: string;
  group_id: string | null;
  group_name: string | null;
};
export type AccountReport = {
  id: string;
  party_id: string;
  party_name: string;
  report_kind: AccountMode;
  as_of: string;
  status: string;
  error: string | null;
  finished_at: string | null;
  parameters: { start_date?: string; financial_year?: string };
  details: {
    pages: number;
    debit_total?: string;
    credit_total?: string;
    account_count?: number;
  } | null;
};
export type BalanceRow = {
  name: string;
  debit: string;
  credit: string;
  balance: string;
  side: "Dr" | "Cr";
};
export type BalanceView = {
  group_name: string;
  as_of: string;
  accounts: BalanceRow[];
  debit_total: string;
  credit_total: string;
  account_count: number;
};
export type AccountOptions = {
  financial_year: string;
  start_date: string;
  as_of: string;
};
export const accountReportRunning = (report: AccountReport | null) =>
  !!report && ["queued", "warning", "generating"].includes(report.status);
export function accountReportLabel(report: AccountReport) {
  return (
    report.party_name +
    (report.report_kind === "ledger"
      ? " - Copy account"
      : " - Closing balances")
  );
}
export function currentAccountYear(today: string): AccountOptions {
  const year =
    Number(today.slice(0, 4)) - (Number(today.slice(5, 7)) < 4 ? 1 : 0);
  return {
    financial_year: `${String(year % 100).padStart(2, "0")}-${String((year + 1) % 100).padStart(2, "0")}`,
    start_date: `${year}-04-01`,
    as_of: today,
  };
}
function validDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(value + "T12:00:00Z");
  return (
    Number.isFinite(parsed.getTime()) &&
    parsed.toISOString().slice(0, 10) === value
  );
}
export function accountDateError(
  mode: AccountMode,
  start: string,
  end: string,
  options: AccountOptions,
): string | null {
  if (!validDate(end) || (mode === "ledger" && !validDate(start)))
    return "Choose valid report dates.";
  if (end > options.as_of) return "Choose a date through today.";
  if (mode === "ledger" && start > end)
    return "The start date must be before the end date.";
  if (mode === "group_balances" && end < options.start_date)
    return `Choose a date in financial year ${options.financial_year}.`;
  return null;
}
