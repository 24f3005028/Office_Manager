"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { request } from "@/lib/api/client";
import { useGoogleSession } from "./google-gate";

type MobileUser = { id: string; name: string; phone: string; active: number };
type Grant = { email: string; dashboard: number; mobile_user_id: string | null };

export function GoogleAccess({ owner }: { owner: boolean }) {
  const session = useGoogleSession();
  const [users, setUsers] = useState<MobileUser[]>([]);
  const [grants, setGrants] = useState<Grant[]>([]);
  const [email, setEmail] = useState("");
  const [dashboard, setDashboard] = useState(false);
  const [mobile, setMobile] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [accountsFile, setAccountsFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const activeUsers = new Map(users.filter((user) => user.active).map((user) => [user.id, user]));

  async function load() {
    const [status, access] = await Promise.all([
      request<{ users: MobileUser[] }>("/api/mobile-admin/status"),
      request<Grant[]>("/api/auth/grants"),
    ]);
    setUsers(status.users);
    setGrants(access);
    setLoaded(true);
  }

  useEffect(() => {
    if (owner) void load().catch((reason: Error) => setError(reason.message));
  }, [owner]);

  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await work();
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Request failed.");
    } finally {
      setBusy(false);
    }
  }

  function save(event: FormEvent) {
    event.preventDefault();
    void action(async () => {
      await request("/api/auth/grants", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), dashboard, mobile_user_id: mobile || null }),
      });
      setMessage("Google access updated.");
    });
  }

  if (!owner) return <section className="panel settings-connection-card">
    <h1>Google access</h1>
    <p>Only the office Google account can manage access.</p>
    <Link href="/settings" className="google-access-back">Back to settings</Link>
  </section>;
  return (
    <div className="google-access">
      <header className="google-access-header">
        <div><h1>Google access</h1><p className="intro-copy">Manage who can sign in to the dashboard and Android app.</p></div>
        <Link href="/settings" className="button button-secondary">Back to settings</Link>
      </header>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {message && <p className="notice notice-success" role="status">{message}</p>}
      <div className="google-access-grid">
        <section className="panel settings-connection-card">
          <h2>Account permissions</h2>
          <p className="muted-text">Enter a Google email or select an account from the list.</p>
          <form onSubmit={save} className="google-access-form">
            <label htmlFor="google-email">Google email</label>
            <input id="google-email" type="email" value={email} onChange={(event) => {
              const next = event.target.value;
              const grant = grants.find((item) => item.email === next.trim().toLowerCase());
              setEmail(next);
              setDashboard(Boolean(grant?.dashboard));
              if (grant) setMobile(grant.mobile_user_id && activeUsers.has(grant.mobile_user_id) ? grant.mobile_user_id : "");
              else if (grants.some((item) => item.mobile_user_id === mobile)) setMobile("");
            }} required />
            <label className="google-access-choice">
              <input type="checkbox" checked={dashboard || email.trim().toLowerCase() === session.email} disabled={email.trim().toLowerCase() === session.email} onChange={(event) => setDashboard(event.target.checked)} />
              <span>Allow dashboard access</span>
            </label>
            <label htmlFor="google-mobile">Mobile account</label>
            <select id="google-mobile" value={mobile} onChange={(event) => setMobile(event.target.value)}>
              <option value="">No mobile access</option>
              {Array.from(activeUsers.values()).map((user) => (
                <option key={user.id} value={user.id} disabled={grants.some((grant) => grant.mobile_user_id === user.id && grant.email !== email.trim().toLowerCase())}>{user.name} (+{user.phone})</option>
              ))}
            </select>
            <button className="button button-primary" disabled={busy || !loaded}>Save permissions</button>
          </form>
        </section>
        <section className="panel settings-connection-card">
          <h2>Add a mobile account</h2>
          <p className="muted-text">Create a profile for someone who hasn’t used the Android app before.</p>
          <form onSubmit={(event) => {
            event.preventDefault();
            void action(async () => {
              const result = await request<{ id: string }>("/api/mobile-admin/users", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: name.trim(), phone: phone.trim().replace(/^\+/, "").replace(/[\s()-]/g, "") }),
              });
              setMobile(result.id);
              setName("");
              setPhone("");
              setMessage("Mobile account created. Enter a Google email and save its permissions.");
              document.getElementById("google-email")?.focus();
            });
          }} className="google-access-form">
            <label htmlFor="google-mobile-name">Name</label>
            <input id="google-mobile-name" maxLength={100} value={name} onChange={(event) => setName(event.target.value)} required />
            <label htmlFor="google-mobile-phone">WhatsApp number with country code</label>
            <input id="google-mobile-phone" type="tel" placeholder="+91 9876543210" value={phone} onChange={(event) => setPhone(event.target.value)} required />
            <button className="button button-secondary" disabled={busy}>Create mobile account</button>
          </form>
        </section>
      </div>
      <section className="panel settings-connection-card" aria-labelledby="granted-accounts">
        <h2 id="granted-accounts">Granted accounts</h2>
        {!loaded && !error && <p role="status" className="muted-text">Loading accounts…</p>}
        {loaded && !grants.length && <p className="muted-text">No accounts have been added yet.</p>}
        {!!grants.length && <ul className="google-grant-list">{grants.map((grant) => {
          const linked = grant.mobile_user_id ? activeUsers.get(grant.mobile_user_id) : undefined;
          return <li key={grant.email}>
            <div className="google-grant-identity"><strong>{grant.email}</strong>{linked && <small>{linked.name}</small>}</div>
            <div className="google-grant-badges">
              {grant.email === session.email && <span>Owner</span>}
              {!!grant.dashboard && <span>Dashboard</span>}
              {linked && <span>Android</span>}
              {!grant.dashboard && !linked && <span className="google-grant-inactive">No access</span>}
            </div>
            <button className="button button-secondary" type="button" aria-label={`Edit access for ${grant.email}`} disabled={busy} onClick={() => {
              setEmail(grant.email);
              setDashboard(Boolean(grant.dashboard));
              setMobile(linked?.id ?? "");
              document.getElementById("google-email")?.focus();
            }}>Edit</button>
          </li>;
        })}</ul>}
      </section>
      <section className="panel settings-connection-card">
        <h2>Update the mobile party list</h2>
        <form onSubmit={(event) => {
          event.preventDefault();
          if (!accountsFile) return;
          void action(async () => {
            const body = new FormData();
            body.append("file", accountsFile);
            const result = await request<{ added: number }>("/api/mobile-admin/accounts", {
              method: "POST", body,
            });
            setMessage(`Party list updated. ${result.added} new parties added.`);
          });
        }} className="google-access-form">
          <label htmlFor="google-accounts-file">BUSY List of Accounts export</label>
          <input id="google-accounts-file" type="file" accept=".xlsx" onChange={(event) => setAccountsFile(event.target.files?.[0] ?? null)} />
          <button className="button button-secondary" disabled={busy || !accountsFile}>Import accounts</button>
        </form>
      </section>
    </div>
  );
}
