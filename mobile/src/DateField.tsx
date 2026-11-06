import { useState } from "react";
import { Platform, Pressable, Text, TextInput, View } from "react-native";
import DateTimePicker from "@react-native-community/datetimepicker";
import { displayDate, Icon, styles } from "./ui";

export default function DateField({
  label,
  value,
  onChange,
  disabled = false,
  mode = "date",
  maximumDate,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  mode?: "date" | "time";
  maximumDate?: Date;
}) {
  const [open, setOpen] = useState(false);
  const parsed = new Date(
    mode === "date" ? `${value}T12:00:00` : `2026-01-01T${value}:00`,
  );
  const selected = Number.isNaN(parsed.getTime()) ? new Date() : parsed;
  const pad = (part: number) => String(part).padStart(2, "0");
  return (
    <View style={styles.grow}>
      <Text style={styles.label}>{label}</Text>
      {Platform.OS === "web" ? (
        <TextInput
          style={styles.input}
          value={value}
          onChangeText={onChange}
          accessibilityLabel={label}
          editable={!disabled}
          placeholder={mode === "date" ? "YYYY-MM-DD" : "HH:MM"}
        />
      ) : (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${label}: ${value || "Choose"}`}
          disabled={disabled}
          onPress={() => setOpen(true)}
          style={[styles.input, styles.row, disabled && styles.disabled]}
        >
          <Icon name="calendar" size={18} />
          <Text style={[styles.historyTitle, styles.grow]}>
            {value ? (mode === "date" ? displayDate(value) : value) : "Choose"}
          </Text>
        </Pressable>
      )}
      {open && Platform.OS !== "web" && (
        <DateTimePicker
          value={selected}
          mode={mode}
          is24Hour
          maximumDate={maximumDate}
          onChange={(event, date) => {
            setOpen(false);
            if (event.type !== "set" || !date) return;
            onChange(
              mode === "date"
                ? `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
                : `${pad(date.getHours())}:${pad(date.getMinutes())}`,
            );
          }}
        />
      )}
    </View>
  );
}
