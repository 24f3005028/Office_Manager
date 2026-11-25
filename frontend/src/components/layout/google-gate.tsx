"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import Image from "next/image";
import { API_BASE_URL, request } from "@/lib/api/client";
import { Icon } from "./icons";

type Session = { required: boolean; ready: boolean; email: string | null; owner: boolean };
const GoogleSession = createContext<Session>({ required: true, ready: false, email: null, owner: false });
export const useGoogleSession = () => useContext(GoogleSession);
const signInErrors: Record<string, string> = {
  denied: "This Google account hasn’t been given office access.",
  expired: "This sign-in attempt expired. Start again in this browser.",
  cancelled: "Google sign-in was cancelled.",
  failed: "Google couldn’t verify this sign-in. Try again with your approved account.",
};

export function GoogleGate({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState("");
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    if (window.location.hostname === "localhost") {
      const canonical = new URL(window.location.href);
      canonical.hostname = "127.0.0.1";
      window.location.replace(canonical);
      return;
    }
    const result = new URLSearchParams(window.location.search).get("google");
    if (result && Object.hasOwn(signInErrors, result)) setError(signInErrors[result]);
    request<Session>("/api/auth/status").then(setSession).catch(() => {
      setUnavailable(true);
      setError("The office dashboard service could not be reached.");
    });
  }, []);

  if (session && (!session.required || session.email)) {
    return <GoogleSession.Provider value={session}>{children}</GoogleSession.Provider>;
  }

  return (
    <main className="office-signin">
      <section className="office-signin-card" aria-labelledby="office-signin-title">
        <div className="office-signin-brand">
          <div className="signin-lockup"><Image src="/auth/hs-traders.png" width={48} height={48} alt="" priority /><span>H.S. Traders</span></div>
          <p>Office workspace</p>
          <span className="signin-art" aria-hidden="true"><Icon name="file" width="72" height="72" /></span>
        </div>
        <div className="office-signin-content">
          <h1 id="office-signin-title">Sign in to your workspace</h1>
          <p>Use your approved Google account to continue.</p>
          {error && <p className="notice notice-error" role="alert">{error}</p>}
          <div className="office-signin-action">
            {session?.ready ? (
              <a className="google-signin-link" href={API_BASE_URL + "/api/auth/google/start"} aria-label="Sign in with Google">
                <Image src="/auth/google-sign-in.png" width={216} height={48} alt="" priority />
              </a>
            ) : unavailable ? (
              <button type="button" className="button button-secondary" onClick={() => window.location.reload()}>Try again</button>
            ) : session ? (
              <p role="status">Ask the office owner to configure Google sign-in.</p>
            ) : (
              <p role="status"><span className="spinner dark" aria-hidden="true" /> Checking sign-in…</p>
            )}
          </div>
          <p className="office-signin-footer">Need access? Contact the office owner.</p>
        </div>
      </section>
    </main>
  );
}

export function GoogleAccountButton() {
  const { email } = useGoogleSession();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  if (!email) return null;
  return <details className="google-account-menu">
    <summary aria-label="Google account" title={email}>{email.slice(0, 1).toUpperCase()}</summary>
    <div className="google-account-popover">
      <strong>Signed in as</strong>
      <span>{email}</span>
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      <button className="button button-secondary" type="button" disabled={busy} onClick={async () => {
        setBusy(true);
        setError("");
        try {
          await request("/api/auth/logout", { method: "POST" });
          window.location.assign("/");
        } catch {
          setError("Could not sign out. Please try again.");
          setBusy(false);
        }
      }}>{busy ? "Signing out…" : "Sign out"}</button>
    </div>
  </details>;
}
