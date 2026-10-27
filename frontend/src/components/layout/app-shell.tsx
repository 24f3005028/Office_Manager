import type { ReactNode } from "react";
import Link from "next/link";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <main className="app-shell">
      <div className="ambient-glow ambient-glow-one" />
      <div className="ambient-glow ambient-glow-two" />
      <div className="page-container">
        <header className="app-header">
          <div className="brand-lockup">
            <div className="brand-mark" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <div>
              <p className="eyebrow">Operations console</p>
              <h1>Office document dashboard</h1>
            </div>
          </div>
          <div className="header-note">
            <span className="header-note-dot" />
            Local workspace
          </div>
        </header>
        <nav className="app-nav" aria-label="Primary navigation">
          <Link href="/">Home</Link>
          <Link href="/whatsapp-bill-sender">WhatsApp sender</Link>
          <Link href="/settings">Settings</Link>
        </nav>
        {children}
        <footer className="app-footer">
          <span>Documents stay on your local workspace.</span>
          <span className="footer-divider" aria-hidden="true" />
          <span>WhatsApp sends run one document at a time.</span>
        </footer>
      </div>
    </main>
  );
}
