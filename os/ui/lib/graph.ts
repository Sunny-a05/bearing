// lib/graph.ts — builds the Obsidian-style knowledge graph from the wiki.
// Nodes are markdown pages (+ library items); edges are [[wikilinks]].
import fs from "node:fs";
import path from "node:path";
import { frontmatter, osRoot } from "./os";

export type GraphNode = {
  id: string;       // repo-relative path (unique)
  label: string;    // stem
  type: string;     // frontmatter type | registry | library | note
  deg: number;
  status?: string;
};
export type GraphLink = { source: string; target: string };
export type Graph = { nodes: GraphNode[]; links: GraphLink[]; builtAt: string };

const WIKILINK = /\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]/g;
// Root/meta files whose links would turn the graph into one giant hub.
const SKIP_STEMS = new Set(["index", "log", "state", "claude", "agents", "readme", "_template", "untitled"]);

function* walk(dir: string): Generator<string> {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === "node_modules" || e.name.startsWith(".")) continue;
      yield* walk(p);
    } else if (e.name.endsWith(".md")) {
      yield p;
    }
  }
}

export function buildGraph(): Graph {
  const root = osRoot();
  const files: string[] = [];
  for (const sub of ["wiki", "os", "library"]) {
    const dir = path.join(root, sub);
    if (fs.existsSync(dir)) files.push(...walk(dir));
  }

  type Page = { id: string; stem: string; type: string; text: string; status?: string };
  const pages: Page[] = [];
  for (const abs of files) {
    const rel = path.relative(root, abs).replace(/\\/g, "/");
    if (rel.startsWith("os/ui/") || rel.startsWith("os/dock/inbox/") || rel.startsWith("os/sessions/")) continue;
    const stem = path.basename(rel, ".md").toLowerCase();
    if (SKIP_STEMS.has(stem)) continue;
    const text = fs.readFileSync(abs, "utf-8");
    const fm = frontmatter(text);
    let type = fm["type"] || "note";
    if (rel.startsWith("os/registry/")) type = "registry";
    else if (rel.startsWith("library/")) type = "library";
    else if (rel.startsWith("os/")) type = fm["type"] || "context";
    pages.push({ id: rel, stem, type, text, status: fm["status"] });
  }

  // stem -> candidate ids; wiki pages win link resolution over registry cards
  const byStem = new Map<string, string[]>();
  for (const p of pages) {
    const arr = byStem.get(p.stem) || [];
    arr.push(p.id);
    byStem.set(p.stem, arr);
  }
  const resolve = (target: string): string | null => {
    const parts = target.trim().toLowerCase().split("/").filter(Boolean);
    const stem = parts.pop()!;
    const hint = parts.pop(); // explicit folder, e.g. "registry" in [[registry/sls-estimator]]
    const c = byStem.get(stem);
    if (!c) return null;
    // An explicit path prefix is a disambiguation instruction and must beat the
    // wiki-wins default below. Without this, every [[registry/x]] link resolved
    // to wiki/entities/x — the opposite of what it asked for, and the opposite
    // of OS hard rule 3 (cards own status, entity pages own knowledge).
    if (hint) {
      const hinted = c.find((id) => id.toLowerCase().split("/").includes(hint));
      if (hinted) return hinted;
    }
    return c.find((id) => id.startsWith("wiki/")) || c.find((id) => !id.startsWith("os/registry/")) || c[0];
  };

  const deg = new Map<string, number>();
  const links: GraphLink[] = [];
  const seen = new Set<string>();
  for (const p of pages) {
    // strip code fences so snippets don't create phantom links
    const body = p.text.replace(/```[\s\S]*?```/g, "");
    let m: RegExpExecArray | null;
    WIKILINK.lastIndex = 0;
    while ((m = WIKILINK.exec(body))) {
      const target = resolve(m[1]);
      if (!target || target === p.id) continue;
      const key = p.id + "→" + target;
      if (seen.has(key)) continue;
      seen.add(key);
      links.push({ source: p.id, target });
      deg.set(p.id, (deg.get(p.id) || 0) + 1);
      deg.set(target, (deg.get(target) || 0) + 1);
    }
  }

  return {
    nodes: pages.map((p) => ({
      id: p.id,
      label: path.basename(p.id, ".md"),
      type: p.type,
      deg: deg.get(p.id) || 0,
      status: p.status,
    })),
    links,
    builtAt: new Date().toISOString(),
  };
}
