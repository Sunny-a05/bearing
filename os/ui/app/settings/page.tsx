"use client";
// Connections — the browser face of the connections layer (map ticket 05).
//
// os/agents.d/<seat>.json says HOW to reach a seat (hand-authored, rare edits).
// os/settings.json says WHETHER it is on (machine-written, constant). This page
// reads the resolved join through settings.py and mutates it only through
// `agentos.py tools`, so a toggle here and a toggle in a terminal are the same
// act — same store, same `settings` record on os/runs.jsonl.
//
// Switching a connection off is not cosmetic: routing drops every roster seat
// behind it, records a `skip` per stepped-over rung, and a chain with nothing
// live left raises rather than falling back to sonnet (ticket 03). The two
// things this page does that a terminal table doesn't are showing which roster
// seats a connection owns, and naming the task classes a switch-off would
// darken — before the click, not after.
import { useCallback, useEffect, useState } from "react";
import { Badge, Empty, PageHeader } from "@/components/ui";
import { useCli } from "@/components/useCli";

type Row = {
  name: string; kind: string; enabled: boolean; auth: string;
  last_probe: string; probe: string; api_key_env: string; note: string;
};
type TrailRec = Record<string, any>;
type View = {
  rows: Row[];
  covers: Record<string, string[]>;
  dark: string[];
  would_dark: Record<string, string[]>;
  trail: TrailRec[];
  error?: string;
};

const BAD = new Set(["needs-auth", "missing-binary", "missing-key"]);

export default function ConnectionsPage() {
  const [view, setView] = useState<View | null>(null);
  const [note, setNote] = useState("");

  const refresh = useCallback(() => {
    fetch("/api/connections").then((r) => r.json()).then(setView);
  }, []);
  const cli = useCli(refresh);
  useEffect(refresh, [refresh]);

  const toggle = (r: Row) => {
    const willDark = view?.would_dark?.[r.name] || [];
    if (r.enabled && willDark.length &&
        !confirm(`Switching off '${r.name}' leaves no live seat for: ${willDark.join(", ")}.\n\n` +
                 `Routing will raise rather than fall back to a more expensive seat. Continue?`)) return;
    const args = ["tools", r.enabled ? "disable" : "enable", r.name];
    if (note.trim()) args.push("--note", note.trim());
    cli.run("toggle", args, 60_000);
    setNote("");
  };

  const rows = view?.rows || [];
  const off = rows.filter((r) => !r.enabled);
  const bad = rows.filter((r) => r.enabled && BAD.has(r.auth));

  return (
    <div className="fade-up mx-auto max-w-5xl px-6 py-6">
      <PageHeader
        title="Connections — which seats are ON"
        sub="os/agents.d/ says how to reach a seat; os/settings.json says whether it's switched on. Off means off: routing skips it, and explicit drive / council refuse it too."
      />

      {view === null && <Empty text="reading the connections layer…" />}
      {view?.error && (
        <div className="card mb-4 border-err/40 px-4 py-3 text-sm text-err">
          settings.py could not be read — the table below is empty, but the OS is unaffected
          (it fails open).
          <pre className="console mt-2 text-[11px]">{view.error}</pre>
        </div>
      )}

      {view && !!view.dark.length && (
        <div className="card mb-4 border-err/40 bg-err/5 px-4 py-3 text-sm">
          <span className="text-err">⚠ No live seat</span> for{" "}
          <span className="font-mono text-ink">{view.dark.join(", ")}</span> — every rung of
          those chains is switched off, so a call raises{" "}
          <code className="text-warn">NoEnabledSeat</code> (exit 3) instead of silently
          rerouting. Re-enable a connection below, or fix the policy table in{" "}
          <code className="text-muted">os/orchestration.md</code>.
        </div>
      )}

      {view && rows.length > 0 && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <button className="btn" onClick={refresh}>↻ Refresh</button>
            <button
              className="btn"
              disabled={cli.busy}
              onClick={() => cli.run("probe", ["tools", "probe"], 120_000)}
            >
              {cli.busy && cli.label === "probe" ? "probing…" : "⌁ Probe all"}
            </button>
            <input
              className="input ml-auto w-72 text-xs"
              placeholder="note for the next toggle — lands on the run trail"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
          </div>

          <div className="card mb-5 overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-faint">
                  <th className="px-4 py-2.5 font-medium">connection</th>
                  <th className="px-2 py-2.5 font-medium">kind</th>
                  <th className="px-2 py-2.5 font-medium">auth</th>
                  <th className="px-2 py-2.5 font-medium">roster seats it owns</th>
                  <th className="px-2 py-2.5 font-medium">last probe</th>
                  <th className="px-4 py-2.5 text-right font-medium">on?</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const covers = view.covers[r.name] || [];
                  const willDark = view.would_dark[r.name] || [];
                  const detail = r.probe || r.note || "";
                  return (
                    <tr key={r.name} className={`border-b border-line last:border-0 hover:bg-elev/40 ${r.enabled ? "" : "opacity-60"}`}>
                      <td className="px-4 py-2.5 align-top">
                        <div className="font-mono text-ink">{r.name}</div>
                        {r.api_key_env && (
                          <div className="mt-0.5 font-mono text-[11px] text-faint">${r.api_key_env}</div>
                        )}
                        {detail && (
                          <div className="mt-0.5 max-w-[300px] text-[11px] leading-snug text-faint">{detail}</div>
                        )}
                        {r.enabled && !!willDark.length && (
                          <div className="mt-1 max-w-[300px] text-[11px] leading-snug text-warn">
                            switching off darkens: {willDark.join(", ")}
                          </div>
                        )}
                      </td>
                      <td className="px-2 py-2.5 align-top text-xs text-muted">{r.kind}</td>
                      <td className="px-2 py-2.5 align-top"><Badge v={r.auth} /></td>
                      <td className="max-w-[200px] px-2 py-2.5 align-top text-xs text-muted">
                        {covers.length ? covers.join(", ") : <span className="text-faint">routed by its own name</span>}
                      </td>
                      <td className="px-2 py-2.5 align-top text-[11px] text-faint">
                        <div>{r.last_probe ? r.last_probe.slice(0, 16).replace("T", " ") : "never"}</div>
                        <button
                          className="btn mt-1 px-2 py-0.5 text-[11px]"
                          disabled={cli.busy}
                          onClick={() => cli.run("probe", ["tools", "probe", r.name], 60_000)}
                        >
                          probe
                        </button>
                      </td>
                      <td className="px-4 py-2.5 text-right align-top">
                        <button
                          className={`btn text-xs ${r.enabled ? "" : "btn-accent"}`}
                          disabled={cli.busy}
                          onClick={() => toggle(r)}
                          title={r.enabled ? `agentos.py tools disable ${r.name}` : `agentos.py tools enable ${r.name}`}
                        >
                          {r.enabled ? "on — switch off" : "OFF — switch on"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="mb-6 text-xs leading-relaxed text-faint">
            {off.length > 0 && (
              <div>
                <span className="text-muted">OFF:</span> {off.map((r) => r.name).join(", ")} — routing
                skips these and records a <code className="text-muted">skip</code> per stepped-over rung.
              </div>
            )}
            {bad.length > 0 && (
              <div className="mt-0.5">
                <span className="text-warn">!</span> {bad.map((r) => r.name).join(", ")} — switched on but
                not usable yet. A probe records what it found; it never flips the switch.
              </div>
            )}
            {!off.length && !bad.length && <div>Every known connection is on and authenticated.</div>}
            <div className="mt-1.5">
              One binary can serve several roster seats — disabling{" "}
              <code className="text-muted">claude</code> drops haiku, sonnet and opus/fable together,
              because that is the truth about what is switchable.
            </div>
          </div>
        </>
      )}

      {cli.output && (
        <div className="mb-6">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs font-semibold text-muted">CLI output</span>
            <button className="btn px-2 py-0.5 text-xs" onClick={cli.clear}>clear</button>
          </div>
          <pre className="console max-h-72 overflow-y-auto">{cli.output}{cli.busy ? "\n…" : ""}</pre>
        </div>
      )}

      {view && !!view.trail?.length && (
        <div>
          <h2 className="mb-1 text-sm font-semibold">Change trail</h2>
          <p className="mb-2.5 text-xs text-faint">
            Config changes and their consequences, straight from os/runs.jsonl — the reason
            &ldquo;why did this stop routing to gemini&rdquo; is answerable without reading settings.json.
          </p>
          <div className="card divide-y divide-line">
            {view.trail.map((t, i) => (
              <div key={i} className="flex flex-wrap items-baseline gap-2 px-4 py-2 text-xs">
                <span className="font-mono text-[11px] text-faint">{(t.ts || "").slice(0, 16).replace("T", " ")}</span>
                {t.kind === "settings" ? (
                  <>
                    <span className="chip bg-accent-soft text-accent">{t.event}</span>
                    <span className="font-mono text-ink">{t.seat}</span>
                    <span className="text-muted">
                      {t.field}: {String(t.was)} → {String(t.now)}
                    </span>
                  </>
                ) : (
                  <>
                    <Badge v="skipped" />
                    <span className="font-mono text-ink">{t.model}</span>
                    <span className="text-muted">
                      skipped on <span className="font-mono">{t.task}</span> — connection{" "}
                      <span className="font-mono">{t.seat}</span> off ({t.via})
                    </span>
                  </>
                )}
                {t.note && t.kind === "settings" && <span className="text-faint">— {t.note}</span>}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
