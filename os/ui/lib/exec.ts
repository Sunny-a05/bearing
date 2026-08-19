// lib/exec.ts — the ONLY mutation path. The UI never writes OS files itself;
// it shells the Python CLI (single source of truth for OS behavior) with an
// allowlisted argv array (no shell string interpolation, no injection surface).
import { execFile } from "node:child_process";
import { osRoot } from "./os";

const ALLOWED = new Set([
  "status", "route", "runs", "log-run", "review",
  "dock", "digest", "file", "redrop", "reactivate", "enrich", "promote",
  "agents", "drive", "council", "sessions", "tools",
]);

export type ExecResult = { ok: boolean; code: number; stdout: string; stderr: string; cmd: string[] };

export function runCli(args: string[], timeoutMs = 600_000): Promise<ExecResult> {
  if (!args.length || !ALLOWED.has(args[0])) {
    return Promise.resolve({ ok: false, code: -1, stdout: "", stderr: `subcommand not allowlisted: ${args[0]}`, cmd: args });
  }
  const root = osRoot();
  const argv = ["-X", "utf8", "os/cli/agentos.py", ...args];
  return new Promise((resolve) => {
    execFile(
      "python",
      argv,
      { cwd: root, timeout: timeoutMs, maxBuffer: 16 * 1024 * 1024, windowsHide: true },
      (err, stdout, stderr) => {
        const code = err ? ((err as any).code ?? 1) : 0;
        resolve({ ok: !err, code: typeof code === "number" ? code : 1, stdout: stdout || "", stderr: stderr || "", cmd: argv });
      }
    );
  });
}

/** Structured probe straight from drivers.py — single source of truth. */
export function probeAgents(): Promise<any[]> {
  const root = osRoot();
  const py = "import json,sys; sys.path.insert(0,'os/cli'); import drivers; print(json.dumps(drivers.probe()))";
  return new Promise((resolve) => {
    execFile("python", ["-X", "utf8", "-c", py], { cwd: root, timeout: 30_000, windowsHide: true }, (err, stdout) => {
      if (err) return resolve([]);
      try {
        resolve(JSON.parse(stdout.trim().split("\n").pop() || "[]"));
      } catch {
        resolve([]);
      }
    });
  });
}

// --------------------------------------------------------------- connections
// The connections table is READ THROUGH PYTHON, not parsed from settings.json
// in TypeScript — deliberately, and against this app's usual filesystem-as-
// database habit. `settings.json` is a sparse overlay: the effective state of
// a seat is stored-entry over fail-open defaults, with `kind` inferred from
// its agents.d spec and both enums coerced (settings.py:connection). Re-deriving
// that here would be a second implementation of the spec, which is the exact
// defect ticket 03 found in lib/os.ts's summarize() twin — three record kinds
// it was never taught. probeAgents() set the precedent; this follows it.
//
// `covers` and `would_dark` come from orchestrator.py's own mapping and policy
// table for the same reason: the UI must never hold its own opinion about which
// roster seats a connection owns.
const CONNECTIONS_PY = `
import json, sys
sys.path.insert(0, 'os/cli')
import settings as st, orchestrator as orc

rows = st.status_rows()
off = {r["name"] for r in rows if not r["enabled"]}

covers = {}
for name in list(orc.MODELS) + list(orc.SEAT_DRIVERS):
    conn = orc.connection_seat(name)
    if not conn:
        continue                       # user: a human is not a connection
    covers.setdefault(conn, [])
    if name not in covers[conn]:
        covers[conn].append(name)

def dark(hidden):
    """Task classes whose whole chain is unreachable with \`hidden\` also off."""
    out = []
    for task, _kw, chain, _never, _why in list(orc.POLICY) + [orc.DEFAULT_ROUTE]:
        conns = [orc.connection_seat(s) for s in chain]
        if conns and all(c is not None and (c in off or c in hidden) for c in conns):
            out.append(task)
    return out

now_dark = dark(set())
would = {r["name"]: [t for t in dark({r["name"]}) if t not in now_dark]
         for r in rows if r["enabled"]}

print(json.dumps({"rows": rows, "covers": covers,
                  "dark": now_dark, "would_dark": would}))
`;

export type ConnectionRow = {
  name: string; kind: string; enabled: boolean; auth: string;
  last_probe: string; probe: string; api_key_env: string; note: string;
};
export type ConnectionsView = {
  rows: ConnectionRow[];
  covers: Record<string, string[]>;
  dark: string[];
  would_dark: Record<string, string[]>;
  error?: string;
};

const EMPTY_VIEW: ConnectionsView = { rows: [], covers: {}, dark: [], would_dark: {} };

export function connectionsView(): Promise<ConnectionsView> {
  const root = osRoot();
  return new Promise((resolve) => {
    execFile(
      "python",
      ["-X", "utf8", "-c", CONNECTIONS_PY],
      { cwd: root, timeout: 30_000, windowsHide: true },
      (err, stdout, stderr) => {
        if (err) return resolve({ ...EMPTY_VIEW, error: (stderr || String(err)).slice(-600) });
        try {
          resolve(JSON.parse(stdout.trim().split("\n").pop() || "{}"));
        } catch {
          resolve({ ...EMPTY_VIEW, error: "unparseable output from settings.py" });
        }
      }
    );
  });
}
