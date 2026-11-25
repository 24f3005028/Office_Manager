import type { ReactNode, SVGProps } from "react";

export type IconName = "home" | "send" | "sync" | "settings" | "arrow" | "folder" | "check" | "help" | "sheet" | "chat" | "phone" | "calendar" | "file";
const paths: Record<IconName, ReactNode> = {
  home: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
  send: <><path d="m21 3-7 18-4-7-7-4Z" /><path d="m10 14 6-6" /></>,
  sync: <path d="M20 7h-6m6 0V1m0 6a9 9 0 0 0-15-2M4 17h6m-6 0v6m0-6a9 9 0 0 0 15 2" />,
  settings: <><path d="M4 7h16M4 17h16" /><circle cx="9" cy="7" r="3" fill="currentColor" stroke="none" /><circle cx="16" cy="17" r="3" fill="currentColor" stroke="none" /></>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6" />,
  folder: <path d="M3 7V5a2 2 0 0 1 2-2h5l3 3h6a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />,
  check: <path d="m5 12 4 4L19 6" />,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9.5 9a2.5 2.5 0 0 1 5 .5c0 2-2.5 2-2.5 4M12 17h.01" /></>,
  sheet: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M4 9h16M4 15h16m-8-6v12" /></>,
  chat: <path d="M20 11.5a8 8 0 0 1-11.4 7.2L4 20l1.3-4.6A8 8 0 1 1 20 11.5Z" />,
  phone: <><rect x="7" y="2.5" width="10" height="19" rx="2.2" /><path d="M11 18.5h2" /></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M7 3v4m10-4v4M3 10h18" /></>,
  file: <><path d="M13 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V10Zm0 0v7h7M8 14h8m-8 3h5" /></>,
};
export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>;
}
