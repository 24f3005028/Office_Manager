import { Modal, Pressable, ScrollView, Text, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { Icon, Logo, styles } from "./ui";

export type NavigationScreen =
  | "home"
  | "outstanding"
  | "allOutstanding"
  | "accounts"
  | "invoices"
  | "tools"
  | "tasks"
  | "history"
  | "account";
export default function NavigationDrawer({
  visible,
  current,
  name,
  disabled,
  onClose,
  onSelect,
}: {
  visible: boolean;
  current: NavigationScreen;
  name: string;
  disabled: boolean;
  onClose: () => void;
  onSelect: (screen: NavigationScreen) => void;
}) {
  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      onRequestClose={onClose}
    >
      <View style={styles.drawerOverlay}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Close navigation menu"
          style={styles.drawerBackdrop}
          onPress={onClose}
        />
        <SafeAreaView style={styles.drawer}>
          <View style={[styles.row, { padding: 18 }]}>
            <Logo />
            <View style={styles.grow}>
              <Text style={styles.brand}>H.S. TRADERS</Text>
              <Text style={styles.brandSub}>Your workspace</Text>
            </View>
            <Pressable
              style={styles.menuButton}
              accessibilityRole="button"
              accessibilityLabel="Close menu"
              onPress={onClose}
            >
              <Icon name="close" />
            </Pressable>
          </View>
          <ScrollView contentContainerStyle={{ padding: 14, gap: 8 }}>
            {(
              [
                ["home", "home", "Home"],
                ["outstanding", "statement", "Party statement"],
                ["allOutstanding", "statement", "All outstanding"],
                ["accounts", "file", "Copy account & balances"],
                ["invoices", "search", "Find a bill"],
                ["tools", "calendar", "Office tools"],
                ["tasks", "check", "Office tasks"],
                ["history", "history", "Activity"],
                ["account", "settings", "Account & connection"],
              ] as const
            ).map(([key, icon, label], index) => (
              <View key={key}>
                {(index === 1 || index === 5 || index === 8) && (
                  <Text
                    style={[
                      styles.eyebrow,
                      {
                        paddingHorizontal: 12,
                        paddingTop: 18,
                        paddingBottom: 8,
                      },
                    ]}
                  >
                    {index === 1
                      ? "REPORTS"
                      : index === 5
                        ? "TEAM & OFFICE"
                        : "SETTINGS"}
                  </Text>
                )}
                <Pressable
                  key={key}
                  accessibilityRole="button"
                  accessibilityState={{ selected: current === key, disabled }}
                  disabled={disabled}
                  onPress={() => onSelect(key)}
                  style={[
                    styles.drawerItem,
                    current === key && styles.navActive,
                  ]}
                >
                  <View style={styles.partyMark}>
                    <Icon name={icon} size={20} />
                  </View>
                  <Text style={[styles.historyTitle, styles.grow]}>
                    {label}
                  </Text>
                  {current === key && <Icon name="check" size={17} />}
                </Pressable>
              </View>
            ))}
          </ScrollView>
          <Text style={[styles.noteText, { padding: 20 }]}>
            Signed in as {name}
          </Text>
        </SafeAreaView>
      </View>
    </Modal>
  );
}
