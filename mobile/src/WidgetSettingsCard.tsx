import { useEffect, useState } from "react";
import { Alert, Text, View } from "react-native";
import { Party } from "./api";
import { Button, styles } from "./ui";
import { defaultWidgetSettings, WidgetSettings } from "./widgetModel";
import { pinHomeWidget, refreshHomeWidgets, saveWidgetSettings, widgetSettings, widgetsAvailable } from "./homeWidgets";

export default function WidgetSettingsCard({ chooseParty }: { chooseParty: () => void }) {
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
    await saveWidgetSettings({ ...settings, enabled: true });
    const result = await pinHomeWidget(kind);
    setNotice(result === "updated" ? "Your existing widget is updated." : result === "requested" ? "Confirm Add on your phone’s home-screen prompt." : "Long-press an empty area on your phone’s home screen → Widgets → H.S. Traders Office, then drag the widget onto the home screen.");
  }
  return <View style={styles.card}>
    <Text style={styles.sectionTitle}>Home-screen widgets</Text>
    <Text style={styles.muted}>See tasks and one chosen party without opening the app. Rounded widgets can be resized on your home screen. All party widgets on this phone show the chosen party.</Text>
    {!widgetsAvailable ? <Text style={styles.muted}>Install the latest Android APK to use widgets.</Text> : <>
      <Text style={styles.label}>Tasks to show</Text>
      <View style={styles.row}>
        <Button title="My tasks" secondary={settings.scope !== "mine"} disabled={busy} onPress={() => void run(() => saveWidgetSettings({ ...settings, scope: "mine", enabled: true }))} />
        <Button title="All tasks" secondary={settings.scope !== "all"} disabled={busy} onPress={() => void run(() => saveWidgetSettings({ ...settings, scope: "all", enabled: true }))} />
      </View>
      <Button title="Add tasks widget" disabled={busy} onPress={() => void run(() => pin("tasks"))} />
      <Text style={styles.label}>Outstanding party</Text>
      <Text style={styles.muted}>{settings.party?.name ?? "Choose a party first"}</Text>
      <Button title={settings.party ? "Change widget party" : "Choose widget party"} secondary disabled={busy} onPress={chooseParty} />
      <Button title="Add party widget" disabled={busy || !settings.party} onPress={() => void run(() => pin("party"))} />
      {settings.enabled && <>
        <Button title="Refresh saved widget data" secondary disabled={busy} onPress={() => void run(async () => { await refreshHomeWidgets(); setNotice("Saved data refreshed. No new BUSY report was requested."); })} />
        <Button title="Turn widgets off" secondary disabled={busy} onPress={() => Alert.alert("Clear widget data?", "The widgets will show a setup message. You can remove them by long-pressing them on your home screen.", [{ text: "Cancel", style: "cancel" }, { text: "Clear", onPress: () => void run(() => saveWidgetSettings({ ...settings, enabled: false })) }])} />
      </>}
      <Text style={styles.noteText}>Read-only updates may take 15 minutes or longer. Tailscale and the office must be online. Saved balances show the statement date; fresh BUSY reports are created only when you request them in the app. Widget text is visible to anyone looking at your unlocked home screen.</Text>
    </>}
    {!!notice && <Text accessibilityRole="alert" style={styles.muted}>{notice}</Text>}
  </View>;
}

export async function selectWidgetParty(party: Party) {
  await saveWidgetSettings({ ...await widgetSettings(), party, enabled: true });
}
