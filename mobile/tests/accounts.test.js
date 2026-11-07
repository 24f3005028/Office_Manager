import { expect, test } from "bun:test";
import {
  accountDateError,
  accountReportLabel,
  currentAccountYear,
  formatAccountMoney,
} from "../src/accountModel";

test("large balances retain their exact digits in Indian notation", () => {
  expect(formatAccountMoney("123456789012345678.90")).toBe(
    "₹1,23,45,67,89,01,23,45,678.90",
  );
  expect(formatAccountMoney("0.00")).toBe("₹0.00");
  expect(formatAccountMoney("invalid")).toBe("Unavailable");
});

test("account dates default to the current April-to-March financial year", () => {
  expect(currentAccountYear("2026-03-31")).toEqual({
    financial_year: "25-26",
    start_date: "2025-04-01",
    as_of: "2026-03-31",
  });
  expect(currentAccountYear("2026-04-01").financial_year).toBe("26-27");
});
test("copy account accepts earlier custom ranges and rejects future or reversed dates", () => {
  const options = currentAccountYear("2026-11-07");
  expect(
    accountDateError("ledger", "2025-01-16", "2026-11-07", options),
  ).toBeNull();
  expect(
    accountDateError("ledger", "2026-11-07", "2026-11-06", options),
  ).toContain("start date");
  expect(
    accountDateError("ledger", "2026-04-01", "2026-11-08", options),
  ).toContain("today");
  expect(
    accountDateError("ledger", "2026-02-30", "2026-11-07", options),
  ).toContain("valid");
});
test("group closing date is limited to the current financial year", () => {
  const options = currentAccountYear("2026-11-07");
  expect(
    accountDateError("group_balances", "", "2026-03-31", options),
  ).toContain("26-27");
  expect(
    accountDateError("group_balances", "", "2026-04-01", options),
  ).toBeNull();
});
test("account report filenames always contain the party or group name", () => {
  expect(
    accountReportLabel({ party_name: "Example party", report_kind: "ledger" }),
  ).toBe("Example party - Copy account");
  expect(
    accountReportLabel({ party_name: "Sale", report_kind: "group_balances" }),
  ).toBe("Sale - Closing balances");
});
