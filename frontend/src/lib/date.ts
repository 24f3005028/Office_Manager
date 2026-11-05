export type DatePreset = "today" | "yesterday" | "custom";

export function displayDate(value: string): string {
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("en-IN", {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  }).format(date);
}

export interface DateRange {
  startDate: string;
  endDate: string;
}

export function toDateInput(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function dateRangeFor(preset: Exclude<DatePreset, "custom">): DateRange {
  const date = new Date();
  if (preset === "yesterday") date.setDate(date.getDate() - 1);
  const value = toDateInput(date);
  return { startDate: value, endDate: value };
}

export function isValidDateRange(range: DateRange): boolean {
  return Boolean(range.startDate && range.endDate && range.startDate <= range.endDate);
}
