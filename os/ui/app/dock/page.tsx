"use client";
// The Dock — incoming-knowledge pipeline (spec: os/dock/DOCK.md).
// Drop files into os/dock/inbox/, digest them on the free local tier, then
// decide: library (default) or raw+wiki. The UI shells the CLI for every
// action — DOCK rule 5 (drafts never decide) is enforced by the CLI itself.
import { useCallback, useEffect, useState } from "react";
import { Badge, Empty, PageHeader } from "@/components/ui";
import { useCli } from "@/components/useCli";

type Sidecar = {
  entities: string[]; tags: string[]; claims: string[];
  urgency?: string; tier?: string; verdict?: string;
  relationships: { from?: string; verb?: string; to?: string }[];
};
type Item = { name: string; size: number; ageDays: number; digested: boolean; sidecar: Sidecar | null };

export default function DockPage() {
  const [items, setItems] = useState<Item[] | null>(null);
  const refresh = useCallback(() => {
    fetch("/api/dock").then((r) => r.json()).then((d) => setItems(d.items));
  }, []);
  const cli = useCli(refresh);
  useEffect(refresh, [refresh]);

  return (
    <div className="fade-up mx-auto max-w-5xl px-6 py-6">
      <PageHeader
        title="Dock — incoming knowledge"
        sub="inbox → dedup → digest (local tier, free) → decision → library (default) or raw + wiki. Nothing is ever deleted."
      />

      <div className="mb-4 flex items-center gap-2">
        <button className="btn" onClick={refresh}>↻ Refresh</button>
        <button className="btn" disabled={cli.busy || !items?.length} onClick={() => cli.run("digest", ["digest"], 600_000)}>
          {cli.busy && cli.label === "digest" ? "digesting…" : "⚙ Digest all (local tier)"}
        </button>
        <span className="ml-auto text-xs text-faint">drop files into <code className="text-muted">os/dock/inbox/</code></span>
      </div>

      {items === null && <Empty text="loading…" />}
      {items !== null && items.length === 0 && (
        <Empty text="Inbox is empty. Drop a report, paper, or note into os/dock/inbox/ and it shows up here." />
      )}

      <div className="space-y-3">
        {items?.map((it) => (
          <div key={it.name} className="card px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-sm text-ink">{it.name}</span>
              <span className="text-xs text-faint">{(it.size / 1024).toFixed(1)} KB · {it.ageDays}d old</span>
              {it.ageDays > 14 && <Badge v="blocked" />}
              {it.digested ? <Badge v="ok" /> : <span className="chip bg-elev text-faint">no digest yet</span>}
              <div className="ml-auto flex gap-1.5">
                <button className="btn text-xs" disabled={cli.busy} onClick={() => cli.run("digest", ["digest", it.name], 600_000)}>digest</button>
                <button className="btn text-xs" disabled={cli.busy || !it.digested} onClick={() => cli.run("file", ["file", it.name, "--to", "library"])}>→ library</button>
                <button className="btn text-xs" disabled={cli.busy || !it.digested} onClick={() => cli.run("file", ["file", it.name, "--to", "raw"])}>→ raw + wiki</button>
                <button className="btn text-xs" disabled={cli.busy} onClick={() => cli.run("redrop", ["redrop", it.name])}>redrop</button>
              </div>
            </div>
            {it.sidecar && (
              <div className="mt-2.5 rounded-lg bg-deep px-3 py-2.5 text-xs">
                <div className="mb-1.5 flex flex-wrap gap-1.5">
                  {it.sidecar.urgency && <Badge v={it.sidecar.urgency} />}
                  {it.sidecar.verdict && <span className="chip bg-accent-soft text-accent">draft: {it.sidecar.verdict}</span>}
                  {it.sidecar.tags.map((t) => <span key={t} className="chip bg-elev text-muted">#{t}</span>)}
                </div>
                {it.sidecar.entities.length > 0 && (
                  <div className="text-muted"><span className="text-faint">entities · </span>{it.sidecar.entities.join(", ")}</div>
                )}
                {it.sidecar.relationships.length > 0 && (
                  <div className="mt-1 text-muted">
                    <span className="text-faint">graph · </span>
                    {it.sidecar.relationships.slice(0, 6).map((r, i) => (
                      <span key={i} className="mr-2">({r.from} —{r.verb}→ {r.to})</span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {cli.output && (
        <div className="mt-5">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs font-semibold text-muted">CLI output</span>
            <button className="btn px-2 py-0.5 text-xs" onClick={cli.clear}>clear</button>
          </div>
          <pre className="console max-h-80 overflow-y-auto">{cli.output}{cli.busy ? "\n…" : ""}</pre>
        </div>
      )}
    </div>
  );
}
