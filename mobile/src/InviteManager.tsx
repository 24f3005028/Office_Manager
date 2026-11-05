import { useState } from "react";
import { Pressable, Text, TextInput, View } from "react-native";
import * as Clipboard from "expo-clipboard";
import { Button, Note, styles } from "./ui";

type Invite = { invite_code: string; expires_at: string };
type Api = <T>(path: string, body?: unknown) => Promise<T>;

export default function InviteManager({ api }: { api: Api }) {
  const [name, setName] = useState("");
  const [country, setCountry] = useState("91"),
    [phone, setPhone] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [invite, setInvite] = useState<Invite | null>(null),
    [copied, setCopied] = useState(false);
  const [recipient, setRecipient] = useState("");

  async function createInvite() {
    setError("");
    if (
      !name.trim() ||
      !/^[1-9][0-9]{0,3}$/.test(country) ||
      !/^[0-9]{6,14}$/.test(phone) ||
      country.length + phone.length > 15 ||
      (country === "91" && !/^[6-9][0-9]{9}$/.test(phone))
    ) {
      setError(
        "Enter a name, country code and mobile number. For India, use +91 and the 10-digit number without a leading 0.",
      );
      return;
    }
    setBusy(true);
    try {
      const result = await api<Invite>("/invites", {
        name: name.trim(),
        phone: country + phone,
      });
      setInvite(result);
      setCopied(false);
      setRecipient(`${name.trim()} · +${country} ${phone}`);
      setName("");
      setPhone("");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The invite could not be created.",
      );
    } finally {
      setBusy(false);
    }
  }
  async function copyCode() {
    if (!invite) return;
    try {
      await Clipboard.setStringAsync(invite.invite_code);
      setCopied(true);
    } catch {
      setError(
        "Copy was unavailable. Press and hold the code to copy it manually.",
      );
    }
  }
  return (
    <View style={styles.card}>
      <Text style={styles.eyebrow}>INVITE MANAGER</Text>
      <Text style={styles.cardTitle}>Invite a new user</Text>
      <Text style={styles.muted}>
        Create a private, one-time code for their phone. Approved users can view
        parties, update Pouncha and send bills.
      </Text>
      {error && (
        <Text accessibilityRole="alert" style={styles.error}>
          {error}
        </Text>
      )}
      <View>
        <Text style={styles.label}>Person’s name</Text>
        <TextInput
          style={styles.input}
          value={name}
          onChangeText={setName}
          maxLength={100}
          editable={!busy}
          placeholder="Enter their name"
          accessibilityLabel="New user's name"
        />
      </View>
      <View style={styles.row}>
        <View style={{ width: 105 }}>
          <Text style={styles.label}>Country code</Text>
          <View style={[styles.searchBox, { paddingLeft: 12, gap: 2 }]}>
            <Text style={styles.muted}>+</Text>
            <TextInput
              value={country}
              onChangeText={(value) =>
                setCountry(value.replace(/\D/g, "").slice(0, 4))
              }
              style={styles.searchInput}
              keyboardType="phone-pad"
              editable={!busy}
              maxLength={4}
              accessibilityLabel="New user's country code"
            />
          </View>
        </View>
        <View style={styles.grow}>
          <Text style={styles.label}>Mobile number</Text>
          <TextInput
            style={styles.input}
            value={phone}
            onChangeText={(value) =>
              setPhone(value.replace(/\D/g, "").slice(0, 14))
            }
            keyboardType="phone-pad"
            editable={!busy}
            maxLength={14}
            placeholder="9876543210"
            accessibilityLabel="New user's mobile number"
          />
        </View>
      </View>
      <Button
        title={busy ? "Creating invite…" : "Create one-time invite"}
        disabled={busy || !name.trim() || !country || !phone}
        onPress={() => void createInvite()}
      />
      {invite && (
        <View style={{ gap: 14 }}>
          <View style={styles.divider} />
          <Text style={styles.sectionTitle}>Invite ready</Text>
          <Text style={styles.muted}>{recipient}</Text>
          <Text
            selectable
            style={[styles.input, { fontFamily: "monospace", fontSize: 14 }]}
            accessibilityLabel="New user's invite code"
          >
            {invite.invite_code}
          </Text>
          <Button
            title={copied ? "Copied!" : "Copy code"}
            secondary
            onPress={() => void copyCode()}
          />
          <Text style={styles.noteText}>
            Expires at{" "}
            {new Date(invite.expires_at).toLocaleTimeString("en-IN", {
              hour: "2-digit",
              minute: "2-digit",
            })}
            . Works once. Share it only with this person.
          </Text>
          <Pressable
            accessibilityRole="button"
            style={styles.textButton}
            onPress={() => {
              setInvite(null);
              setCopied(false);
            }}
          >
            <Text style={styles.link}>Hide code</Text>
          </Pressable>
        </View>
      )}
      <Note>
        The new phone also needs Tailscale access and your office HTTPS address.
        This invite grants app access; it does not add a phone to Tailscale.
      </Note>
    </View>
  );
}
