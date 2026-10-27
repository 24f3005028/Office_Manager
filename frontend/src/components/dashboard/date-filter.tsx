import type { DatePreset, DateRange } from "@/lib/date";

interface DateFilterProps {
  preset: DatePreset;
  range: DateRange;
  onPresetChange: (preset: DatePreset) => void;
  onRangeChange: (range: DateRange) => void;
}

export function DateFilter({ preset, range, onPresetChange, onRangeChange }: DateFilterProps) {
  return (
    <fieldset className="filter-group">
      <legend>Date range</legend>
      <div className="segmented-control" role="group" aria-label="Date range presets">
        {(["today", "yesterday", "custom"] as DatePreset[]).map((value) => (
          <button
            className={preset === value ? "segment active" : "segment"}
            key={value}
            type="button"
            onClick={() => onPresetChange(value)}
          >
            {value === "today" ? "Today" : value === "yesterday" ? "Yesterday" : "Custom"}
          </button>
        ))}
      </div>
      {preset === "custom" && (
        <div className="date-inputs">
          <label>
            <span>From</span>
            <input
              type="date"
              value={range.startDate}
              onChange={(event) => onRangeChange({ ...range, startDate: event.target.value })}
            />
          </label>
          <span className="date-arrow" aria-hidden="true">→</span>
          <label>
            <span>To</span>
            <input
              type="date"
              value={range.endDate}
              onChange={(event) => onRangeChange({ ...range, endDate: event.target.value })}
            />
          </label>
        </div>
      )}
    </fieldset>
  );
}
