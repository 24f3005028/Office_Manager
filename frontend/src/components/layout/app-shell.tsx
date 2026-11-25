"use client";

import type { ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "./icons";
import { GoogleAccountButton, useGoogleSession } from "./google-gate";

const navigation: { href: string; title: string; icon: IconName }[] = [
  { href: "/", title: "Overview", icon: "home" },
  { href: "/whatsapp-bill-sender", title: "Send bills", icon: "send" },
  { href: "/pouncha-sync", title: "Pouncha sheet", icon: "sheet" },
  { href: "/settings", title: "Settings", icon: "settings" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { owner } = useGoogleSession();
  const items = owner
    ? [...navigation, { href: "/mobile-access", title: "Google access", icon: "phone" as const }]
    : navigation;
  const activePath = pathname === "/setup" ? "/settings" : pathname;
  const title = pathname === "/setup" ? "Setup" : items.find((item) => item.href === pathname)?.title ?? "Google access";

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to page content</a>
    <aside className="workspace-sidebar">
      <Link href="/" className="brand-lockup" aria-label="Office dashboard home">
        <Image className="workspace-logo" src="/auth/hs-traders.png" width={40} height={40} alt="" priority />
        <span><strong>H.S. Traders</strong><small>Office dashboard</small></span>
      </Link>
      <nav className="app-nav" aria-label="Main navigation">
        {items.map((item) => (
          <Link key={item.href} href={item.href} className={activePath === item.href ? "active" : undefined} aria-current={pathname === item.href ? "page" : undefined}>
            <Icon name={item.icon} width="19" height="19" /><span>{item.title}</span>
          </Link>
        ))}
      </nav>
    </aside>
    <header className="workspace-topbar">
      <div className="workspace-location"><span>Workspace</span><span aria-hidden="true">/</span><strong>{title}</strong></div>
      <GoogleAccountButton />
    </header>
    <main className="page-container" id="main-content">{children}</main>
  </div>;
}
