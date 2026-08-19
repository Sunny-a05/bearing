"use client";
// The run trail — os/runs.jsonl rendered. Every model call, handoff, session,
// council, and review the OS ever made. Review buttons close the rule-4 loop.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge, Empty, PageHeader, Stat } from "@/components/ui";
import { useCli } from "@/components/useCli";

type Rec = Record<string, any>;
type Summary = {
  total: number; unreviewed: number; councils: number; sessions: number;
  byModel: { model: string; calls: number; ok: number; charsOut: number }[];
  handoffs: { to: string; n: number }[];
};

// Every kind orchestrator.py can emit. A kind missing here is a record the
// trail holds and the UI cannot be filtered to — invisible, not absent.
const KINDS = ["all", "model-call", "handoff", "agent-run", "review", "session",
               "council", "refusal", "skip", "settings"];

export default function RunsPage() {
  const [data, setData] = useState<{ records: Rec[]; summary: Summary } | null>(null);
  const [kind, setKind] = useState("all");
  const refresh = useCallback(() => {
    fetch("/api/runs?n=300").then((r) => r.json()).then(setData);
  }, []);
  const cli = useCli(refresh);
  useEffect(refresh, [refresh]);

  const reviewedIds = useMemo(() => {
    const s = new Set<string>();
    for (const r of data?.records || []) {
      if (r.kind === "review" && r.of) s.add(r.of);
      if (r.reviewed === true && r.run) s.add(r.run);
    }
    return s;
  }, [data]);

  const rows = useMemo(
    () => (data?.records || []).filter((r) => kind === "all" || r.kind === kind),
    [data, kind]
  );

  return (
    <div className="fade-up mx-auto max-w-6xl px-6 py-6">
      <PageHeader title="Run trail" sub="os/runs.jsonl — append-only, emitted by the system itself. The governance seed." />

      {data && (
        <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="records · 7d" value={data.summary.total} />
          <Stat label="unreviewed local" value={data.summary.unreviewed} tone={data.summary.unreviewed ? "err" : "ok"} />
          <Stat label="councils" value={data.summary.councils} />
          <Stat label="session events" value={data.summary.sessions} />
        </div>
      )}

      <div className="mb-3 flex flex-wrap items-center gap-1.5">
        {KINDS.map((k) => (
          <button key={k} onClick={() => setKind(k)} className={`chip border border-line ${kind === k ? "bg-accent-soft text-accent" : "bg-panel text-muted hover:text-ink"}`}>
            {k}
          </button>
        ))}
        <button className="btn ml-auto text-xs" onClick={refresh}>↻ Refresh</button>
      </div>

      {!data && <Empty text="loading…" />}
      {data && rows.length === 0 && <Empty text="No records of this kind yet." />}

      {rows.length > 0 && (
        <div className="card overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-faint">
                <th className="px-3 py-2 font-medium">ts</th>
                <th className="px-2 py-2 font-medium">run</th>
                <th className="px-2 py-2 font-medium">kind</th>
                <th className="px-2 py-2 font-medium">task</th>
                <th className="px-2 py-2 font-medium">model / to</th>
                <th className="px-2 py-2 font-medium">outcome</th>
                <th className="px-2 py-2 text-right font-medium">lat</th>
                <th className="px-2 py-2 text-right font-medium">out</th>
                <th className="px-3 py-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const local = r.tier === "ollama";
                const needsReview = (r.kind === "model-call" || r.kind === "agent-run") && local && !reviewedIds.has(r.run);
                return (
                  <tr key={r.run + i} className="border-b border-line last:border-0 hover:bg-elev/40">
                    <td className="whitespace-nowrap px-3 py-2 font-mono text-faint">{(r.ts || "").replace("T", " ")}</td>
                    <td className="px-2 py-2 font-mono text-faint">{r.run}</td>
                    <td className="px-2 py-2 text-muted">{r.kind}</td>
                    <td className="px-2 py-2 text-muted">{r.task}</td>
                    <td className="max-w-[180px] truncate px-2 py-2 font-mono text-ink">{r.model || r.to || r.of || "—"}</td>
                    <td className="px-2 py-2">{r.outcome ? <Badge v={r.outcome} /> : <span className="text-faint">—</span>}</td>
                    <td className="px-2 py-2 text-right font-mono text-muted">{r.latency_s != null ? `${r.latency_s}s` : ""}</td>
                    <td className="px-2 py-2 text-right font-mono text-muted">{r.chars_out ? `${r.chars_out}` : ""}</td>
                    <td className="px-3 py-2 text-right">
                      {needsReview && (
                        <button
                          className="btn px-2 py-0.5 text-[11px]"
                          disabled={cli.busy}
                          onClick={() => cli.run("review", ["review", r.run, "--note", "reviewed via UI"])}
                        >
                          review
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {cli.output && <pre className="console mt-4 max-h-60 overflow-y-auto">{cli.output}</pre>}
    </div>
  );
}
