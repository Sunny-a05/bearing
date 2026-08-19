import Link from "next/link";
import { dockItems, libraryItems, logEntries, registryCards, runsSummary, sessionRows, readText } from "@/lib/os";
import { buildGraph } from "@/lib/graph";
import { Badge, PageHeader, Stat } from "@/components/ui";

export const dynamic = "force-dynamic";

export default function Dashboard() {
  const cards = registryCards();
  const dock = dockItems();
  const lib = libraryItems();
  const sum = runsSummary(7);
  const sessions = sessionRows();
  const running = sessions.filter((s) => s.status === "running").length;
  const graph = buildGraph();
  const log = logEntries(8);
  const state = readText("STATE.md") || "";
  const objective = state.match(/## Current Objective\n+([\s\S]*?)\n##/)?.[1]?.trim() || "";

  return (
    <div className="fade-up mx-auto max-w-6xl px-6 py-6">
      <PageHeader title="Dashboard" sub={`One OS over many agents — ${graph.nodes.length} pages, ${graph.links.length} links in the knowledge graph`} />

      {objective && (
        <div className="card mb-5 border-accent/25 bg-accent-soft px-4 py-3 text-sm">
          <span className="mr-2 font-semibold text-accent">Objective</span>
          <span className="text-muted">{objective}</span>
        </div>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
        <Stat label="wiki pages" value={graph.nodes.length} />
        <Stat label="active cards" value={cards.filter((c) => c.status === "active").length} tone="accent" />
        <Stat label="dock inbox" value={dock.length} tone={dock.length ? "warn" : undefined} />
        <Stat label="library" value={lib.length} />
        <Stat label="runs · 7d" value={sum.total} />
        <Stat label="unreviewed" value={sum.unreviewed} tone={sum.unreviewed ? "err" : "ok"} />
        <Stat label="sessions live" value={running} tone={running ? "accent" : undefined} />
      </div>

      <div className="grid gap-5 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <h2 className="mb-2 text-sm font-semibold text-muted">Registry — what you are working on</h2>
          <div className="card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-faint">
                  <th className="px-4 py-2.5 font-medium">project</th>
                  <th className="px-2 py-2.5 font-medium">domain</th>
                  <th className="px-2 py-2.5 font-medium">status</th>
                  <th className="px-2 py-2.5 font-medium">prio</th>
                  <th className="px-2 py-2.5 font-medium">tier</th>
                  <th className="px-4 py-2.5 text-right font-medium">updated</th>
                </tr>
              </thead>
              <tbody>
                {cards.map((c) => (
                  <tr key={c.slug} className="border-b border-line last:border-0 hover:bg-elev/40">
                    <td className="px-4 py-2.5">
                      <div className="font-medium">{c.project}</div>
                      {c.focus[0] && <div className="mt-0.5 max-w-[320px] truncate text-xs text-faint">{c.focus[0]}</div>}
                    </td>
                    <td className="px-2 py-2.5 text-xs text-muted">{c.domain}</td>
                    <td className="px-2 py-2.5"><Badge v={c.status} /></td>
                    <td className="px-2 py-2.5 text-xs text-muted">{c.priority}</td>
                    <td className="px-2 py-2.5 text-xs text-muted">{c.tier}</td>
                    <td className="px-4 py-2.5 text-right text-xs tabular-nums text-faint">{c.updated}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="lg:col-span-2">
          <h2 className="mb-2 text-sm font-semibold text-muted">Model usage — 7 days</h2>
          <div className="card mb-5 px-4 py-3">
            {sum.byModel.length === 0 && <div className="py-3 text-sm text-faint">no runs yet</div>}
            {sum.byModel.map((m) => (
              <div key={m.model} className="flex items-center justify-between border-b border-line py-1.5 text-sm last:border-0">
                <span className="font-mono text-xs text-ink">{m.model}</span>
                <span className="text-xs text-muted">
                  {m.ok}/{m.calls} ok · ~{Math.round(m.charsOut / 4).toLocaleString()} tok
                </span>
              </div>
            ))}
            {sum.handoffs.map((h) => (
              <div key={h.to} className="flex items-center justify-between py-1.5 text-sm">
                <span className="text-xs text-warn">handoff → {h.to}</span>
                <span className="text-xs text-muted">{h.n}</span>
              </div>
            ))}
          </div>

          <h2 className="mb-2 text-sm font-semibold text-muted">Recent log</h2>
          <div className="card px-4 py-2">
            {log.map((e, i) => (
              <div key={i} className="flex items-baseline gap-2 border-b border-line py-2 text-sm last:border-0">
                <span className="shrink-0 font-mono text-[11px] text-faint">{e.date}</span>
                <Badge v={e.type} />
                <span className="truncate text-xs text-muted">{e.title}</span>
              </div>
            ))}
          </div>
          <div className="mt-3 text-right">
            <Link className="text-xs text-accent hover:underline" href="/graph">
              open the knowledge graph →
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
