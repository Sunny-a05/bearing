// Small shared pieces — server-component friendly.

export function PageHeader({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="mb-5">
      <h1 className="text-lg font-semibold">{title}</h1>
      {sub && <p className="mt-0.5 text-sm text-faint">{sub}</p>}
    </div>
  );
}

export function Stat({ label, value, tone }: { label: string; value: string | number; tone?: "accent" | "ok" | "warn" | "err" }) {
  const color =
    tone === "accent" ? "text-accent" : tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : tone === "err" ? "text-err" : "text-ink";
  return (
    <div className="card px-4 py-3">
      <div className={`text-xl font-semibold tabular-nums ${color}`}>{value}</div>
      <div className="mt-0.5 text-[11px] uppercase tracking-wide text-faint">{label}</div>
    </div>
  );
}

const STATUS_TONE: Record<string, string> = {
  active: "bg-ok/15 text-ok",
  paused: "bg-warn/15 text-warn",
  blocked: "bg-err/15 text-err",
  done: "bg-elev text-muted",
  ok: "bg-ok/15 text-ok",
  running: "bg-accent-soft text-accent",
  killed: "bg-err/15 text-err",
  thin: "bg-warn/15 text-warn",
  error: "bg-err/15 text-err",
  timeout: "bg-err/15 text-err",
  unavailable: "bg-elev text-faint",
  empty: "bg-warn/15 text-warn",
  handoff: "bg-warn/15 text-warn",
  started: "bg-accent-soft text-accent",
  // A guard that fired and a rung that was switched off are both "the OS did
  // what it was told", not failures — muted, never error-red.
  refused: "bg-elev text-faint",
  skipped: "bg-elev text-faint",
  // Connections auth states (settings.py AUTH_STATES). The three "not usable
  // yet" states share one tone because the CLI table gives them one marker (!):
  // the distinction that matters at a glance is usable / not / unverified.
  "needs-auth": "bg-warn/15 text-warn",
  "missing-binary": "bg-warn/15 text-warn",
  "missing-key": "bg-warn/15 text-warn",
  unknown: "bg-elev text-faint",
};

export function Badge({ v }: { v: string }) {
  return <span className={`chip ${STATUS_TONE[v] || "bg-elev text-muted"}`}>{v}</span>;
}

export function Empty({ text }: { text: string }) {
  return <div className="card px-5 py-8 text-center text-sm text-faint">{text}</div>;
}
