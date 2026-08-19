"use client";
// The Library — the archive tier (hippocampus). Never deleted; items are
// enriched on reactivation and promoted to raw/ + wiki when they earn it
// (breadth 2+ cards or frequency 3+ — checked by the CLI, not the UI).
import { useCallback, useEffect, useState } from "react";
import { Badge, Empty, PageHeader } from "@/components/ui";
import { useCli } from "@/components/useCli";

type Sidecar = {
  dropped?: string; entities: string[]; tags: string[]; claims: string[];
  urgency?: string; tier?: string; promoted?: boolean;
  reactivations: { date?: string; trigger?: string; note?: string }[];
};
type Item = { slug: string; file: string; hasPage: boolean; sidecar: Sidecar | null };

export default function LibraryPage() {
  const [items, setItems] = useState<Item[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [trigger, setTrigger] = useState("");
  const refresh = useCallback(() => {
    fetch("/api/library").then((r) => r.json()).then((d) => setItems(d.items));
  }, []);
  const cli = useCli(refresh);
  useEffect(refresh, [refresh]);

  return (
    <div className="fade-up mx-auto max-w-5xl px-6 py-6">
      <PageHeader
        title="Library — the archive tier"
        sub="Everything docked that isn't (yet) wiki-worthy. Thin-digested, never deleted; reactivation enriches, repeated demand promotes."
      />

      {items === null && <Empty text="loading…" />}
      {items !== null && items.length === 0 && <Empty text="Library is empty — the dock's library outcome files items here." />}

      <div className="space-y-3">
        {items?.map((it) => {
          const sc = it.sidecar;
          const expanded = open === it.slug;
          return (
            <div key={it.slug} className="card px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <button className="text-sm font-medium text-ink hover:text-accent" onClick={() => setOpen(expanded ? null : it.slug)}>
                  {expanded ? "▾" : "▸"} {it.slug}
                </button>
                {sc?.tier && <Badge v={sc.tier === "rich" ? "ok" : "thin"} />}
                {sc?.promoted && <span className="chip bg-accent-soft text-accent">promoted</span>}
                {sc?.reactivations?.length ? (
                  <span className="chip bg-elev text-muted">{sc.reactivations.length} reactivation(s)</span>
                ) : null}
                <span className="ml-auto text-xs text-faint">{sc?.dropped && `dropped ${sc.dropped}`}</span>
              </div>
              {sc && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {sc.tags.map((t) => <span key={t} className="chip bg-elev text-muted">#{t}</span>)}
                </div>
              )}
              {expanded && (
                <div className="mt-3 space-y-3 rounded-lg bg-deep px-3 py-3 text-xs">
                  {sc?.entities.length ? (
                    <div className="text-muted"><span className="text-faint">entities · </span>{sc.entities.join(", ")}</div>
                  ) : null}
                  {sc?.claims.length ? (
                    <div>
                      <div className="mb-1 text-faint">cached claims (rich digest)</div>
                      <ul className="ml-4 list-disc space-y-1 text-muted">
                        {sc.claims.map((c, i) => <li key={i}>{c}</li>)}
                      </ul>
                    </div>
                  ) : (
                    <div className="text-faint">tier: thin — claims are computed on first reactivation, then cached forever.</div>
                  )}
                  <div className="flex flex-wrap items-center gap-2 border-t border-line pt-3">
                    <input
                      className="input w-56 text-xs"
                      placeholder="trigger (registry card slug)"
                      value={trigger}
                      onChange={(e) => setTrigger(e.target.value)}
                    />
                    <button
                      className="btn text-xs"
                      disabled={cli.busy || !trigger}
                      onClick={() => cli.run("reactivate", ["reactivate", it.slug, "--trigger", trigger])}
                    >
                      reactivate
                    </button>
                    <button className="btn text-xs" disabled={cli.busy} onClick={() => cli.run("promote", ["promote", it.slug])}>
                      promote check
                    </button>
                    <span className="text-faint">enrich = agent work (claims file) — see DOCK.md</span>
                  </div>
                </div>
              )}
            </div>
          );
        })}
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
