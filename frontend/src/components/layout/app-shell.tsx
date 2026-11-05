"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "./icons";

const navigation: { href: string; title: string; icon: IconName }[] = [
  { href: "/", title: "Home", icon: "home" },
  { href: "/whatsapp-bill-sender", title: "Send bills", icon: "send" },
  { href: "/pouncha-sync", title: "Update Pouncha", icon: "sync" },
  { href: "/settings", title: "Settings", icon: "settings" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to page content</a>
    <header className="app-header"><div className="header-inner">
      <Link href="/" className="brand-lockup" aria-label="Office dashboard home">
        <span className="brand-mark"><Icon name="home" /></span>
        <span><strong>Office dashboard</strong><small>H.S. TRADERS</small></span>
      </Link>
      <nav className="app-nav" aria-label="Main navigation">
        {navigation.map((item) => <Link key={item.href} href={item.href} className={pathname === item.href ? "active" : ""} aria-current={pathname === item.href ? "page" : undefined}><Icon name={item.icon} /><span>{item.title}</span></Link>)}
      </nav>
      <span className="header-note">On this computer</span>
    </div></header>
    <main className="page-container" id="main-content">{children}</main>
    <footer className="app-footer"><span>Office document dashboard</span><span>Need to change folders or connect WhatsApp? <Link href="/settings">Open settings</Link></span></footer>
  </div>;
}
