import { Image, Pressable, StyleSheet, Text, View } from "react-native";

export const palette = {
  navy: "#102f50",
  blue: "#2a6996",
  ink: "#172f45",
  muted: "#687b8a",
  background: "#f5f7f8",
  border: "#e3e9ec",
  teal: "#147b69",
  light: "#eaf3f8",
};
const sources = {
  home: require("../assets/home.png"),
  statement: require("../assets/statement.png"),
  search: require("../assets/search.png"),
  history: require("../assets/history.png"),
  arrow: require("../assets/arrow.png"),
  chevron: require("../assets/chevron.png"),
  back: require("../assets/back.png"),
  download: require("../assets/download.png"),
  share: require("../assets/share.png"),
  whatsapp: require("../assets/whatsapp.png"),
  file: require("../assets/file.png"),
  check: require("../assets/check.png"),
  shield: require("../assets/shield.png"),
  settings: require("../assets/settings.png"),
  calendar: require("../assets/calendar.png"),
  close: require("../assets/close.png"),
  info: require("../assets/info.png"),
};
export type IconName = keyof typeof sources;
export function Icon({
  name,
  color = palette.navy,
  size = 22,
}: {
  name: IconName;
  color?: string;
  size?: number;
}) {
  return (
    <Image
      source={sources[name]}
      style={{ width: size, height: size, tintColor: color }}
      accessibilityIgnoresInvertColors
    />
  );
}
export function Logo({ large = false }: { large?: boolean }) {
  return (
    <Image
      source={require("../assets/logo.png")}
      resizeMode="contain"
      accessibilityLabel="H.S. Traders logo"
      style={large ? styles.welcomeLogo : styles.logo}
    />
  );
}
export function Button({
  title,
  onPress,
  disabled = false,
  secondary = false,
  icon,
  green = false,
}: {
  title: string;
  onPress: () => void;
  disabled?: boolean;
  secondary?: boolean;
  icon?: IconName;
  green?: boolean;
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
        green && styles.greenButton,
        disabled && styles.disabled,
        pressed && styles.pressed,
      ]}
    >
      {icon && (
        <Icon
          name={icon}
          color={secondary ? palette.navy : "white"}
          size={20}
        />
      )}
      <Text style={[styles.buttonText, secondary && styles.secondaryText]}>
        {title}
      </Text>
    </Pressable>
  );
}
export function Heading({
  eyebrow,
  title,
  subtitle,
}: {
  eyebrow: string;
  title: string;
  subtitle?: string;
}) {
  return (
    <View style={styles.heading}>
      <Text style={styles.eyebrow}>{eyebrow}</Text>
      <Text accessibilityRole="header" style={styles.title}>
        {title}
      </Text>
      {subtitle && <Text style={styles.muted}>{subtitle}</Text>}
    </View>
  );
}
export function Note({
  children,
  icon = "shield",
}: {
  children: React.ReactNode;
  icon?: IconName;
}) {
  return (
    <View style={styles.note}>
      <Icon name={icon} color={palette.muted} size={18} />
      <Text style={styles.noteText}>{children}</Text>
    </View>
  );
}
export function TaskTile({
  title,
  subtitle,
  icon,
  onPress,
  disabled = false,
}: {
  title: string;
  subtitle: string;
  icon: IconName;
  onPress: () => void;
  disabled?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.billTile,
        disabled && styles.disabled,
        pressed && styles.pressed,
      ]}
    >
      <View style={styles.tileIcon}>
        <Icon name={icon} size={23} />
      </View>
      <View style={styles.grow}>
        <Text style={styles.tileTitle}>{title}</Text>
        <Text style={styles.tileCopy}>{subtitle}</Text>
      </View>
      <Icon name="chevron" size={17} color={palette.muted} />
    </Pressable>
  );
}
export function Steps({
  labels,
  current,
}: {
  labels: readonly string[];
  current: number;
}) {
  return (
    <View
      style={styles.steps}
      accessibilityLabel={`Step ${current + 1} of ${labels.length}: ${labels[current]}`}
    >
      {labels.map((label, index) => (
        <View key={label} style={styles.step}>
          <View
            style={[
              styles.stepCircle,
              index <= current && styles.stepCircleActive,
            ]}
          >
            {index < current ? (
              <Icon name="check" size={15} color="white" />
            ) : (
              <Text
                style={[
                  styles.stepNumber,
                  index === current && styles.stepNumberActive,
                ]}
              >
                {index + 1}
              </Text>
            )}
          </View>
          <Text
            style={[
              styles.stepLabel,
              index === current && styles.navLabelActive,
            ]}
          >
            {label}
          </Text>
        </View>
      ))}
    </View>
  );
}
export function displayDate(value: string): string {
  const parsed = new Date(value + "T00:00:00Z");
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleDateString("en-IN", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "UTC",
      });
}
export function initials(value: string): string {
  return value
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((word) => word[0])
    .join("")
    .toUpperCase();
}
export const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: palette.background },
  screen: { flex: 1 },
  loading: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 24,
    backgroundColor: palette.background,
  },
  header: {
    paddingHorizontal: 22,
    paddingVertical: 12,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    backgroundColor: "white",
    borderBottomWidth: 1,
    borderBottomColor: palette.border,
  },
  logo: { width: 38, height: 48 },
  welcomeLogo: { width: 88, height: 124 },
  brand: {
    fontWeight: "800",
    fontSize: 17,
    letterSpacing: 1.2,
    color: palette.navy,
  },
  brandSub: { fontSize: 12, color: palette.muted, marginTop: 3 },
  headerText: { flex: 1 },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: palette.light,
    alignItems: "center",
    justifyContent: "center",
  },
  avatarText: { fontSize: 15, fontWeight: "700", color: palette.navy },
  content: { padding: 22, gap: 20, paddingBottom: 32, flexGrow: 1 },
  heading: { gap: 8, marginTop: 4, marginBottom: 2 },
  eyebrow: {
    fontSize: 11,
    fontWeight: "800",
    letterSpacing: 2,
    color: palette.blue,
  },
  title: {
    fontSize: 28,
    lineHeight: 35,
    letterSpacing: -0.9,
    fontWeight: "800",
    color: palette.ink,
  },
  muted: { fontSize: 14, lineHeight: 22, color: palette.muted },
  label: {
    fontSize: 13,
    fontWeight: "700",
    color: palette.ink,
    marginBottom: 9,
  },
  input: {
    backgroundColor: "white",
    borderColor: "#ccd8df",
    borderWidth: 1,
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingVertical: 15,
    fontSize: 16,
    minHeight: 54,
    color: palette.ink,
  },
  searchBox: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "white",
    borderColor: "#ccd8df",
    borderWidth: 1,
    borderRadius: 14,
    paddingLeft: 16,
    gap: 10,
  },
  searchInput: {
    flex: 1,
    paddingVertical: 16,
    paddingRight: 14,
    fontSize: 16,
    color: palette.ink,
    minHeight: 54,
  },
  field: { gap: 0 },
  card: {
    padding: 21,
    backgroundColor: "white",
    borderRadius: 20,
    borderColor: palette.border,
    borderWidth: 1,
    gap: 18,
  },
  cardTitle: {
    fontSize: 20,
    lineHeight: 27,
    fontWeight: "700",
    color: palette.ink,
  },
  button: {
    backgroundColor: palette.navy,
    minHeight: 54,
    borderRadius: 13,
    paddingHorizontal: 18,
    paddingVertical: 15,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 10,
  },
  buttonText: {
    color: "white",
    fontSize: 15,
    fontWeight: "700",
    flexShrink: 1,
    textAlign: "center",
  },
  secondary: {
    backgroundColor: palette.light,
    borderColor: "#dce8ef",
    borderWidth: 1,
  },
  secondaryText: { color: palette.navy },
  greenButton: { backgroundColor: palette.teal },
  disabled: { opacity: 0.4 },
  pressed: { opacity: 0.7 },
  error: { fontSize: 14, color: "#a23932", lineHeight: 21 },
  notice: {
    marginHorizontal: 18,
    marginTop: 12,
    borderRadius: 14,
    padding: 16,
    backgroundColor: "#fff0ec",
    flexDirection: "row",
    gap: 12,
    alignItems: "flex-start",
  },
  dismiss: {
    minHeight: 44,
    minWidth: 44,
    alignItems: "center",
    justifyContent: "center",
    margin: -10,
  },
  link: { color: palette.blue, fontWeight: "700", fontSize: 14 },
  textButton: {
    minHeight: 44,
    justifyContent: "center",
    alignSelf: "flex-start",
  },
  nav: {
    flexDirection: "row",
    backgroundColor: "white",
    paddingHorizontal: 12,
    paddingTop: 8,
    paddingBottom: 6,
    borderTopColor: palette.border,
    borderTopWidth: 1,
  },
  navItem: {
    flex: 1,
    alignItems: "center",
    paddingVertical: 7,
    gap: 5,
    minHeight: 58,
  },
  navIcon: {
    width: 50,
    height: 29,
    borderRadius: 15,
    overflow: "hidden",
    alignItems: "center",
    justifyContent: "center",
  },
  navActive: { backgroundColor: palette.light },
  navLabel: { fontSize: 11, fontWeight: "600", color: palette.muted },
  navLabelActive: { color: palette.navy, fontWeight: "800" },
  hero: {
    borderRadius: 22,
    backgroundColor: palette.navy,
    padding: 24,
    gap: 15,
    overflow: "hidden",
  },
  heroTop: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
  },
  heroIcon: {
    width: 44,
    height: 44,
    borderRadius: 22,
    overflow: "hidden",
    backgroundColor: "#264766",
    alignItems: "center",
    justifyContent: "center",
  },
  heroTag: {
    fontSize: 10,
    color: "#b9d7e8",
    fontWeight: "800",
    letterSpacing: 1.5,
  },
  heroTitle: {
    fontSize: 27,
    fontWeight: "700",
    letterSpacing: -0.5,
    color: "white",
    lineHeight: 34,
  },
  heroCopy: { color: "#c0d2df", fontSize: 14, lineHeight: 22, maxWidth: 270 },
  heroButton: {
    backgroundColor: "white",
    borderRadius: 12,
    minHeight: 50,
    paddingHorizontal: 17,
    paddingVertical: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    marginTop: 5,
  },
  heroButtonText: { color: palette.navy, fontSize: 15, fontWeight: "800" },
  billTile: {
    flexDirection: "row",
    gap: 16,
    alignItems: "center",
    backgroundColor: "white",
    padding: 20,
    borderRadius: 19,
    borderWidth: 1,
    borderColor: palette.border,
    minHeight: 92,
  },
  tileIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    overflow: "hidden",
    backgroundColor: palette.light,
    alignItems: "center",
    justifyContent: "center",
  },
  tileTitle: {
    fontSize: 18,
    fontWeight: "700",
    color: palette.ink,
    marginBottom: 5,
  },
  tileCopy: { fontSize: 13, lineHeight: 20, color: palette.muted },
  row: { flexDirection: "row", gap: 12, alignItems: "center" },
  grow: { flex: 1 },
  sectionHead: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 10,
  },
  sectionTitle: { fontSize: 16, fontWeight: "700", color: palette.ink },
  note: {
    flexDirection: "row",
    gap: 10,
    alignItems: "flex-start",
    paddingHorizontal: 3,
  },
  noteText: { flex: 1, color: palette.muted, fontSize: 12, lineHeight: 19 },
  welcome: { alignItems: "center", paddingVertical: 13, gap: 16 },
  welcomeTitle: {
    color: palette.navy,
    fontSize: 30,
    lineHeight: 37,
    fontWeight: "800",
    letterSpacing: -0.7,
    textAlign: "center",
  },
  welcomeCopy: {
    color: palette.muted,
    fontSize: 14,
    textAlign: "center",
    lineHeight: 22,
    maxWidth: 290,
  },
  pill: {
    backgroundColor: palette.light,
    borderRadius: 20,
    paddingVertical: 7,
    paddingHorizontal: 12,
    flexDirection: "row",
    gap: 6,
    alignItems: "center",
    alignSelf: "flex-start",
  },
  pillText: { fontSize: 11, color: palette.blue, fontWeight: "700" },
  party: {
    flexDirection: "row",
    alignItems: "center",
    gap: 13,
    backgroundColor: "white",
    padding: 16,
    marginBottom: 9,
    borderRadius: 15,
    borderWidth: 1,
    borderColor: palette.border,
    minHeight: 76,
  },
  partyMark: {
    width: 42,
    height: 42,
    borderRadius: 21,
    overflow: "hidden",
    backgroundColor: palette.light,
    alignItems: "center",
    justifyContent: "center",
  },
  partyInitials: { fontSize: 13, fontWeight: "800", color: palette.blue },
  partyName: {
    fontSize: 14,
    lineHeight: 21,
    color: palette.ink,
    fontWeight: "700",
    flex: 1,
  },
  listHeader: { gap: 20, paddingBottom: 20 },
  yearList: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  year: {
    paddingHorizontal: 18,
    paddingVertical: 13,
    borderWidth: 1,
    borderColor: palette.border,
    borderRadius: 24,
    backgroundColor: "white",
    minHeight: 48,
  },
  yearActive: { borderColor: palette.navy, backgroundColor: palette.navy },
  yearText: { color: palette.muted, fontWeight: "600", fontSize: 14 },
  yearTextActive: { color: "white" },
  actions: { gap: 10 },
  smallActions: { flexDirection: "row", gap: 10 },
  smallAction: {
    flex: 1,
    minHeight: 48,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: palette.border,
    alignItems: "center",
    justifyContent: "center",
    flexDirection: "row",
    gap: 7,
  },
  smallActionText: { color: palette.navy, fontSize: 13, fontWeight: "700" },
  amount: {
    fontSize: 33,
    letterSpacing: -0.8,
    fontWeight: "800",
    color: palette.navy,
  },
  amountLabel: {
    fontSize: 11,
    fontWeight: "700",
    color: palette.muted,
    letterSpacing: 1.1,
    marginBottom: 7,
  },
  amountBox: { backgroundColor: "#f1f6f8", borderRadius: 15, padding: 19 },
  status: { fontWeight: "700", fontSize: 14, color: palette.blue },
  success: { color: palette.teal },
  statusBadge: {
    backgroundColor: "#e9f5ef",
    borderRadius: 16,
    paddingVertical: 5,
    paddingHorizontal: 10,
    alignSelf: "flex-start",
    flexDirection: "row",
    gap: 5,
    alignItems: "center",
  },
  successText: { fontSize: 11, fontWeight: "700", color: palette.teal },
  progress: { paddingVertical: 26, alignItems: "center", gap: 15 },
  divider: { height: 1, backgroundColor: palette.border },
  historyItem: {
    backgroundColor: "white",
    padding: 17,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: palette.border,
    flexDirection: "row",
    gap: 13,
    alignItems: "center",
  },
  historyTitle: {
    fontSize: 14,
    fontWeight: "700",
    color: palette.ink,
    lineHeight: 21,
  },
  historyMeta: { fontSize: 12, color: palette.muted, marginTop: 5 },
  empty: {
    alignItems: "center",
    paddingHorizontal: 24,
    paddingVertical: 35,
    gap: 12,
  },
  emptyTitle: { color: palette.ink, fontSize: 17, fontWeight: "700" },
  emptyCopy: {
    textAlign: "center",
    fontSize: 13,
    color: palette.muted,
    lineHeight: 21,
  },
  accountRow: {
    flexDirection: "row",
    gap: 12,
    alignItems: "center",
    minHeight: 50,
  },
  dangerText: { color: "#ad4941", fontSize: 14, fontWeight: "700" },
  backRow: {
    paddingHorizontal: 18,
    paddingTop: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  backButton: {
    minHeight: 44,
    minWidth: 44,
    borderRadius: 22,
    overflow: "hidden",
    backgroundColor: "white",
    flexDirection: "row",
    gap: 6,
    paddingHorizontal: 12,
    alignItems: "center",
  },
  backLabel: { fontSize: 13, color: palette.navy, fontWeight: "700" },
  steps: { flexDirection: "row", gap: 8, paddingVertical: 4 },
  step: { flex: 1, alignItems: "center", gap: 7 },
  stepCircle: {
    width: 30,
    height: 30,
    borderRadius: 15,
    overflow: "hidden",
    backgroundColor: palette.border,
    alignItems: "center",
    justifyContent: "center",
  },
  stepCircleActive: { backgroundColor: palette.navy },
  stepNumber: { color: palette.muted, fontWeight: "700", fontSize: 12 },
  stepNumberActive: { color: "white" },
  stepLabel: {
    color: palette.muted,
    fontSize: 12,
    fontWeight: "600",
    textAlign: "center",
  },
});
