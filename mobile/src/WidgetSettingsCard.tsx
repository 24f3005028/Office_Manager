import YarnProgress from "./YarnProgress";
import { useEffect, useState } from "react";
import { Text, View } from "react-native";
import { Button, styles } from "./ui";
import { defaultWidgetSettings, WidgetSettings } from "./widgetModel";
import { pinHomeWidget, refreshHomeWidgets, saveWidgetSettings, widgetSettings, widgetsAvailable } from "./homeWidgets";

export default function WidgetSettingsCard() {
  const [settings, setSettings] = useState<WidgetSettings>(defaultWidgetSettings);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  useEffect(() => { void widgetSettings().then(setSettings); }, []);
  async function run(fn: () => Promise<void>) {
    setBusy(true); setNotice("");
    try { await fn(); } catch (error) { setNotice(error instanceof Error ? error.message : "Could not update widgets."); }
    finally { setSettings(await widgetSettings()); setBusy(false); }
  }
  async function pin(kind: "tasks" | "party") {
    const result = await pinHomeWidget(kind);
    setNotice(result === "updated" ? "Your existing widget is updated." : result === "requested" ? "Confirm Add on your phone’s home-screen prompt." : "Long-press an empty area on your phone’s home screen → Widgets → H.S. Traders Office, then drag the widget onto the home screen.");
  }
  return <View style={styles.card}>
    <Text style={styles.sectionTitle}>Home-screen widgets</Text>
    <Text style={styles.muted}>Keep your tasks on the home screen, and use the party search bar to quickly find and share statements.</Text>
    <Text style={styles.muted}>Tasks load automatically from your signed-in office account. No widget setup is required.</Text>
    {!widgetsAvailable ? <Text style={styles.muted}>Install the latest Android APK to use widgets.</Text> : <>
      <Text style={styles.label}>Tasks to show</Text>
      <View style={styles.row}>
        <Button title="My tasks" secondary={settings.scope !== "mine"} disabled={busy} onPress={() => void run(() => saveWidgetSettings({ scope: "mine" }))} />
        <Button title="All tasks" secondary={settings.scope !== "all"} disabled={busy} onPress={() => void run(() => saveWidgetSettings({ scope: "all" }))} />
      </View>
      <Button title="Add tasks widget" disabled={busy} onPress={() => void run(() => pin("tasks"))} />
      <Button title="Add party search widget" disabled={busy} onPress={() => void run(() => pin("party"))} />
      <Button title="Refresh tasks now" secondary disabled={busy} onPress={() => void run(async () => { await refreshHomeWidgets(); setNotice("Task data refreshed. No BUSY report was requested."); })} />
      <Text style={styles.noteText}>Tap the search bar to type a party name in the app and share its saved statement. Fresh BUSY reports still require your request. Task updates may take 15 minutes or longer; task text is visible on your unlocked home screen.</Text>
    </>}
    {busy && <YarnProgress label="Updating widgets…" />}
    {!!notice && <Text accessibilityRole="alert" style={styles.muted}>{notice}</Text>}
  </View>;
}
