// lib/os.ts — the OS read layer. The filesystem IS the database: this module
// parses the wiki, registry, dock, library, run trail, and sessions directly.
// It never writes — every mutation goes through the Python CLI (lib/exec.ts)
// so the UI can never drift from the OS spec.
import fs from "node:fs";
import path from "node:path";

// ---------------------------------------------------------------- root

export function osRoot(): string {
  if (process.env.OS_ROOT) return process.env.OS_ROOT;
  // ui lives at <root>/os/ui — walk up until we see the OS kernel.
  let dir = process.cwd();
  for (let i = 0; i < 5; i++) {
    if (fs.existsSync(path.join(dir, "os", "OS.md"))) return dir;
    dir = path.dirname(dir);
  }
  throw new Error("OS root not found — set OS_ROOT");
}

/** Resolve a repo-relative path and refuse anything that escapes the root. */
export function safePath(rel: string): string {
  const root = osRoot();
  const abs = path.resolve(root, rel);
  if (!abs.startsWith(path.resolve(root))) throw new Error("path escapes OS root");
  return abs;
}

export function readText(rel: string): string | null {
  try {
    return fs.readFileSync(safePath(rel), "utf-8");
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------- frontmatter

export type Frontmatter = Record<string, string>;

export function frontmatter(text: string): Frontmatter {
  const m = text.match(/^---\s*\n([\s\S]*?)\n---/);
  const out: Frontmatter = {};
  if (!m) return out;
  for (const line of m[1].split("\n")) {
    const i = line.indexOf(":");
    if (i > 0 && !line.trimStart().startsWith("#")) {
      out[line.slice(0, i).trim()] = line.slice(i + 1).trim();
    }
  }
  return out;
}

// ---------------------------------------------------------------- mini-YAML
// Tolerant parser for the dock's sidecar .digest.yaml files (fixed schema,
// emitted by dockyard.py). Never throws — unparseable lines are kept raw.

export type Sidecar = {
  source?: string;
  dropped?: string;
  entities: string[];
  relationships: { from?: string; verb?: string; to?: string }[];
  tags: string[];
  urgency?: string;
  tier?: string;
  claims: string[];
  reactivations: { date?: string; trigger?: string; note?: string }[];
  promoted?: boolean;
  raw: string;
};

function unquote(s: string): string {
  s = s.trim();
  if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'")))
    return s.slice(1, -1);
  return s;
}

function parseInlineList(v: string): string[] {
  const inner = v.trim().replace(/^\[/, "").replace(/\]$/, "").trim();
  if (!inner) return [];
  return inner.split(",").map(unquote).filter(Boolean);
}

function parseInlineMap(v: string): Record<string, string> {
  const out: Record<string, string> = {};
  const inner = v.trim().replace(/^\{/, "").replace(/\}$/, "");
  for (const part of inner.split(",")) {
    const i = part.indexOf(":");
    if (i > 0) out[unquote(part.slice(0, i))] = unquote(part.slice(i + 1));
  }
  return out;
}

export function parseSidecar(text: string): Sidecar {
  const sc: Sidecar = { entities: [], relationships: [], tags: [], claims: [], reactivations: [], raw: text };
  const lines = text.split("\n");
  let key = "";
  for (const line of lines) {
    if (!line.trim() || line.trimStart().startsWith("#")) continue;
    const top = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (top) {
      key = top[1];
      const v = top[2].trim();
      if (!v) continue;
      if (key === "entities" || key === "tags" || key === "claims") {
        (sc as any)[key] = v.startsWith("[") ? parseInlineList(v) : [unquote(v)];
      } else if (key === "relationships" || key === "reactivations") {
        if (v.startsWith("[") && v !== "[]") {
          // inline list of maps — rare; best effort
          (sc as any)[key] = v.slice(1, -1).split("},").map((s) => parseInlineMap(s));
        }
      } else if (key === "promoted") {
        sc.promoted = v === "true";
      } else {
        (sc as any)[key] = unquote(v);
      }
      continue;
    }
    const item = line.match(/^\s+-\s+(.*)$/);
    if (item && key) {
      const v = item[1].trim();
      if (key === "relationships" || key === "reactivations") {
        (sc as any)[key].push(v.startsWith("{") ? parseInlineMap(v) : { note: unquote(v) });
      } else if (key === "entities" || key === "tags" || key === "claims") {
        (sc as any)[key].push(unquote(v));
      }
    }
  }
  return sc;
}

// ---------------------------------------------------------------- registry

export type RegistryCard = {
  slug: string;
  path: string;
  project: string;
  domain: string;
  status: string;
  priority: string;
  tier: string;
  updated: string;
  focus: string[];
  next: string[];
};

export function registryCards(): RegistryCard[] {
  const dir = safePath("os/registry");
  if (!fs.existsSync(dir)) return [];
  const cards: RegistryCard[] = [];
  for (const f of fs.readdirSync(dir).sort()) {
    if (!f.endsWith(".md") || f.startsWith("_")) continue;
    const text = fs.readFileSync(path.join(dir, f), "utf-8");
    const fm = frontmatter(text);
    const section = (name: string) => {
      const m = text.match(new RegExp(`## ${name}\\n([\\s\\S]*?)(\\n## |$)`));
      if (!m) return [];
      return m[1].split("\n").map((l) => l.replace(/^-\s*(\[[ x]\]\s*)?/, "").trim()).filter(Boolean);
    };
    cards.push({
      slug: f.replace(/\.md$/, ""),
      path: `os/registry/${f}`,
      project: fm["project"] || f.replace(/\.md$/, ""),
      domain: fm["domain"] || "?",
      status: fm["status"] || "?",
      priority: fm["priority"] || "?",
      tier: fm["default-tier"] || "?",
      updated: fm["last_updated"] || "?",
      focus: section("Current focus").slice(0, 3),
      next: section("Next actions").slice(0, 5),
    });
  }
  return cards;
}

// ---------------------------------------------------------------- run trail

export type RunRecord = Record<string, any>;

export function runRecords(): RunRecord[] {
  const text = readText("os/runs.jsonl");
  if (!text) return [];
  const out: RunRecord[] = [];
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    try {
      out.push(JSON.parse(t));
    } catch {
      /* skip corrupt line */
    }
  }
  return out;
}

export type RunsSummary = {
  total: number;
  days: number;
  byModel: { model: string; calls: number; ok: number; charsOut: number }[];
  handoffs: { to: string; n: number }[];
  unreviewed: number;
  councils: number;
  sessions: number;
  refusals: number;
  skipped: number;
  config: number;
};

/** Mirrors orchestrator.summarize() — reviewed set + per-model rollup. */
export function runsSummary(days = 7): RunsSummary {
  const all = runRecords();
  const cutoff = new Date(Date.now() - days * 86400_000).toISOString().slice(0, 19);
  const recent = all.filter((r) => (r.ts || "") >= cutoff);
  const reviewed = new Set<string>();
  for (const r of all) {
    if (r.kind === "review" && r.of) reviewed.add(r.of);
    if (r.reviewed === true && r.run) reviewed.add(r.run);
  }
  const byModel = new Map<string, { calls: number; ok: number; charsOut: number }>();
  const handoffs = new Map<string, number>();
  let unreviewed = 0, councils = 0, sessions = 0;
  let refusals = 0, skipped = 0, config = 0;
  for (const r of recent) {
    if (r.kind === "review") continue;
    if (r.kind === "council") { councils++; continue; }
    if (r.kind === "session") { sessions++; continue; }
    if (r.kind === "handoff") {
      handoffs.set(r.to || "?", (handoffs.get(r.to || "?") || 0) + 1);
      continue;
    }
    // Not model calls, and each one would otherwise land in byModel: `refusal`
    // (16) and `skip` (03) as a seat that ran, `settings` (02) as a call by a
    // model named "?". summarize() in orchestrator.py was taught each of these
    // as it was added; this twin was not, so it inherited the same trap three
    // times over. Kept as an explicit skip-list rather than an allow-list of
    // call kinds, to match the Python side line for line.
    if (r.kind === "refusal") { refusals++; continue; }
    if (r.kind === "skip") { skipped++; continue; }
    if (r.kind === "settings") { config++; continue; }
    const m = r.model || "?";
    const d = byModel.get(m) || { calls: 0, ok: 0, charsOut: 0 };
    d.calls++;
    if (r.outcome === "ok") d.ok++;
    d.charsOut += Number(r.chars_out || 0);
    byModel.set(m, d);
    const local = r.tier === "ollama";
    if ((r.kind === "model-call" || r.kind === "agent-run") && local && !reviewed.has(r.run)) unreviewed++;
  }
  return {
    total: recent.length,
    days,
    byModel: [...byModel.entries()].map(([model, d]) => ({ model, ...d })).sort((a, b) => b.calls - a.calls),
    handoffs: [...handoffs.entries()].map(([to, n]) => ({ to, n })),
    unreviewed,
    councils,
    sessions,
    refusals,
    skipped,
    config,
  };
}

// ---------------------------------------------------------------- sessions

export type SessionRow = Record<string, any>;

export function sessionRows(): SessionRow[] {
  const text = readText("os/sessions.json");
  if (!text) return [];
  try {
    return JSON.parse(text);
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------- dock + library

export type DockItem = {
  name: string;
  size: number;
  ageDays: number;
  digested: boolean;
  sidecar: Sidecar | null;
};

const DOCK_EXCLUDE = new Set(["readme.md", "desktop.ini"]);

export function dockItems(): DockItem[] {
  const dir = safePath("os/dock/inbox");
  if (!fs.existsSync(dir)) return [];
  const out: DockItem[] = [];
  for (const f of fs.readdirSync(dir).sort()) {
    const p = path.join(dir, f);
    if (!fs.statSync(p).isFile()) continue;
    if (DOCK_EXCLUDE.has(f.toLowerCase()) || f.endsWith(".digest.yaml")) continue;
    const st = fs.statSync(p);
    const draft = path.join(dir, f + ".digest.yaml");
    const sidecar = fs.existsSync(draft) ? parseSidecar(fs.readFileSync(draft, "utf-8")) : null;
    out.push({
      name: f,
      size: st.size,
      ageDays: Math.floor((Date.now() - st.mtimeMs) / 86400_000),
      digested: sidecar !== null,
      sidecar,
    });
  }
  return out;
}

export type LibraryItem = {
  slug: string;
  file: string;
  hasPage: boolean;
  sidecar: Sidecar | null;
};

const LIB_EXCLUDE = new Set(["readme.md", "index.md", "desktop.ini"]);

export function libraryItems(): LibraryItem[] {
  const dir = safePath("library");
  if (!fs.existsSync(dir)) return [];
  const files = fs.readdirSync(dir);
  const out: LibraryItem[] = [];
  for (const f of files.sort()) {
    if (!fs.statSync(path.join(dir, f)).isFile()) continue;
    if (LIB_EXCLUDE.has(f.toLowerCase()) || f.endsWith(".digest.yaml")) continue;
    const slug = f.replace(/\.[^.]+$/, "");
    const scName = files.find((x) => x === `${slug}.digest.yaml` || x === `${f}.digest.yaml`);
    const sidecar = scName ? parseSidecar(fs.readFileSync(path.join(dir, scName), "utf-8")) : null;
    out.push({ slug, file: `library/${f}`, hasPage: f.endsWith(".md"), sidecar });
  }
  return out;
}

// ---------------------------------------------------------------- log

export type LogEntry = { date: string; type: string; title: string };

export function logEntries(limit = 12): LogEntry[] {
  const text = readText("log.md") || "";
  const out: LogEntry[] = [];
  const re = /^## \[(\d{4}-\d{2}-\d{2})\]\s*([\w-]+)\s*\|\s*(.+)$/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) out.push({ date: m[1], type: m[2], title: m[3].trim() });
  return out.reverse().slice(0, limit);
}
