"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { GearIcon, GearMark } from "./Gear";

const ICONS: Record<string, string> = {
  // minimal inline stroke icons (24x24 path data)
  home: "M3 10.5 12 3l9 7.5M5 9.5V21h5v-6h4v6h5V9.5",
  graph: "M5 6a2 2 0 1 0 0.001 0M19 5a2 2 0 1 0 0.001 0M12 19a2 2 0 1 0 0.001 0M6.5 7.5l4 9M13.5 17l4.5-10M7 6.5l10-1",
  dock: "M3 16l4-11h10l4 11M3 16v4h18v-4M3 16h5a4 4 0 0 0 8 0h5",
  library: "M4 4h4v16H4zM10 4h4v16h-4zM17.2 5l3.6 15-3.9 1-3.6-15z",
  runs: "M4 19V9m5.5 10V5M15 19v-8m5 8V3",
  sessions: "M12 8v4l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0",
  agents: "M9 7a3 3 0 1 0 6 0 3 3 0 0 0-6 0M5 21v-1a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v1",
  // a toggle: the connections layer is a switch, not a settings drawer
  connections: "M8 8h8a4 4 0 0 1 0 8H8a4 4 0 0 1 0-8M8 9.6a2.4 2.4 0 1 0 0 4.8 2.4 2.4 0 0 0 0-4.8",
};

const NAV = [
  { href: "/", label: "Dashboard", icon: "home" },
  { href: "/graph", label: "Graph", icon: "graph" },
  { href: "/dock", label: "Dock", icon: "dock" },
  { href: "/library", label: "Library", icon: "library" },
  { href: "/runs", label: "Runs", icon: "runs" },
  { href: "/sessions", label: "Sessions", icon: "sessions" },
  { href: "/agents", label: "Agents", icon: "agents" },
  { href: "/settings", label: "Connections", icon: "connections" },
];

export default function Sidebar() {
  const path = usePathname();
  return (
    <aside className="flex h-screen w-[212px] shrink-0 flex-col border-r border-line bg-deep">
      <div className="group flex items-center gap-2.5 px-4 pb-3 pt-5">
        <GearMark size={34} />
        <div>
          <div className="text-sm font-semibold leading-tight">Bearing</div>
          <div className="text-[11px] text-faint">grill · chart · research</div>
        </div>
      </div>
      <div className="gear-edge mx-4 mb-4" />
      <nav className="flex flex-col gap-0.5 px-2">
        {NAV.map((n) => {
          const active = path === n.href || (n.href !== "/" && path.startsWith(n.href));
          return (
            <Link
              key={n.href}
              href={n.href}
              className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                active ? "bg-accent-soft text-accent" : "text-muted hover:bg-panel hover:text-ink"
              }`}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <path d={ICONS[n.icon]} />
              </svg>
              {n.label}
              {active && <GearIcon size={11} fast className="ml-auto text-accent" />}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto px-4 pb-4 text-[11px] leading-relaxed text-faint">
        Reads the OS files directly.
        <br />
        Actions run <code className="text-muted">agentos.py</code>.
      </div>
    </aside>
  );
}
