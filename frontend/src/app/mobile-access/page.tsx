"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AppShell } from "@/components/layout/app-shell";
import { API_BASE_URL } from "@/lib/api/client";

interface User {
  id: string;
  name: string;
  phone: string;
  active: number;
}
interface Status {
  users: User[];
  party_count: number;
}
async function call<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(API_BASE_URL + "/api/mobile-admin" + path, {
    method: body === undefined ? "GET" : "POST",
    headers:
      body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...(body === undefined
      ? {}
      : { body: body instanceof FormData ? body : JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string" ? data.detail : "Request failed.",
    );
  return data as T;
}
export default function MobileAccess() {
  const [status, setStatus] = useState<Status | null>(null),
    [name, setName] = useState(""),
    [phone, setPhone] = useState(""),
    [invite, setInvite] = useState<{
      invite_code: string;
      expires_at: string;
    } | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const refresh = async () => setStatus(await call<Status>("/status"));
  useEffect(() => {
    void refresh().catch((reason) => setError(String(reason)));
  }, []);
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await fn();
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <AppShell>
      <div className="setup-header">
        <div>
          <p className="eyebrow">On this computer</p>
          <h2>Mobile access</h2>
          <p className="intro-copy">
            Connect approved phones. Every approved user can view all parties
            and saved bill PDFs.
          </p>
        </div>
        <Link href="/settings" className="button button-secondary">
          Back to settings
        </Link>
      </div>
      {error && (
        <div className="notice notice-error" role="alert">
          {error}
        </div>
      )}
      {message && <div className="notice notice-success">{message}</div>}
      <div className="settings-layout">
        <section className="panel settings-connection-card">
          <h2>Connect a phone</h2>
          <p className="muted-text">
            Use a separate invite for each person. Enter their WhatsApp number
            with country code, without + or spaces. Reports can only be sent to
            this approved number.
          </p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void action(async () => {
                setInvite(await call("/invites", { name: name.trim(), phone }));
                setName("");
                setPhone("");
              });
            }}
            style={{ display: "grid", gap: 14, marginTop: 20 }}
          >
            <label htmlFor="mobile-name">Person&apos;s name</label>
            <input
              id="mobile-name"
              value={name}
              maxLength={100}
              onChange={(event) => setName(event.target.value)}
              required
            />
            <label htmlFor="mobile-phone">WhatsApp number</label>
            <input
              id="mobile-phone"
              value={phone}
              onChange={(event) =>
                setPhone(event.target.value.replace(/[^0-9]/g, ""))
              }
              placeholder="919876543210"
              pattern="[1-9][0-9]{7,14}"
              inputMode="tel"
              required
            />
            <button
              className="button button-primary"
              disabled={busy || !name.trim()}
            >
              Create one-time invite
            </button>
          </form>
          {invite && (
            <div className="notice notice-success" style={{ marginTop: 20 }}>
              <strong>Enter this code on their phone</strong>
              <p
                style={{
                  overflowWrap: "anywhere",
                  fontFamily: "monospace",
                  userSelect: "all",
                }}
              >
                {invite.invite_code}
              </p>
              <p>
                Expires{" "}
                {new Date(invite.expires_at).toLocaleTimeString("en-IN")}. Works
                once. Keep it private.
              </p>
              <button
                className="button button-quiet"
                onClick={() => setInvite(null)}
              >
                Hide code
              </button>
            </div>
          )}
        </section>
        <section className="panel settings-folders-card">
          <h2>Party list</h2>
          <p>
            {status?.party_count.toLocaleString("en-IN") ?? "…"} trade accounts
            saved.
          </p>
          <p className="muted-text">
            Import BUSY&apos;s List of Accounts Excel export. Only debtor and
            creditor names are saved. Addresses, GST numbers and balances are
            excluded.
          </p>
          <label className="button button-secondary" style={{ marginTop: 18 }}>
            Update account list
            <input
              type="file"
              accept=".xlsx"
              disabled={busy}
              style={{ display: "none" }}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file)
                  void action(async () => {
                    const data = new FormData();
                    data.append("file", file);
                    const result = await call<{
                      added: number;
                      trade_accounts: number;
                    }>("/accounts", data);
                    setMessage(
                      `${result.trade_accounts} trade accounts checked; ${result.added} new names added.`,
                    );
                  });
                event.target.value = "";
              }}
            />
          </label>
          <div className="notice" style={{ marginTop: 24 }}>
            <strong>Office connection</strong>
            <p>
              Start Office using the desktop shortcut. The mobile gateway runs
              locally on port 8002.
            </p>
            <p>
              For access away from the office, use the private HTTPS Tailscale
              address prepared by the owner. Never expose ports 8000, 3000 or
              3001.
            </p>
            <p>
              Fresh reports show a five-second warning on this computer. Anyone
              using BUSY can cancel the request.
            </p>
          </div>
        </section>
      </div>
      <section
        className="panel settings-folders-card"
        style={{ marginTop: 24 }}
      >
        <h2>Approved people</h2>
        <p className="muted-text">
          Revoke access to disconnect their sessions and unused invites. Copies
          already downloaded to a phone remain on that phone.
        </p>
        <ul style={{ listStyle: "none", padding: 0 }}>
          {status?.users.map((user) => (
            <li
              key={user.id}
              style={{
                display: "flex",
                gap: 16,
                justifyContent: "space-between",
                alignItems: "center",
                padding: "18px 0",
                borderBottom: "1px solid #e2e7ef",
              }}
            >
              <div>
                <strong>{user.name}</strong>
                <p className="muted-text">
                  +{user.phone} · {user.active ? "Access allowed" : "Revoked"}
                </p>
              </div>
              {Boolean(user.active) && (
                <button
                  className="button button-danger-quiet"
                  disabled={busy}
                  onClick={() => {
                    if (
                      window.confirm(`Revoke mobile access for ${user.name}?`)
                    )
                      void action(async () => {
                        await call(`/users/${user.id}/revoke`, {});
                        setMessage("Access revoked.");
                      });
                  }}
                >
                  Revoke access
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>
    </AppShell>
  );
}
