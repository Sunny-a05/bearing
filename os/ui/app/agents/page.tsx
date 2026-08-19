"use client";
// Agents — the roster made tangible: which seats exist, which CLIs are
// actually installed, plus a drive playground and a council launcher.
// New agents appear here automatically when a JSON lands in os/agents.d/.
import { useCallback, useEffect, useState } from "react";
import { Badge, Empty, PageHeader } from "@/components/ui";
import { useCli } from "@/components/useCli";

type Agent = { name: string; binary: string; available: boolean; tier: string; models: Record<string, string | null>; notes: string };

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[] | null>(null);
  const [seat, setSeat] = useState("ollama");
  const [model, setModel] = useState("");
  const [prompt, setPrompt] = useState("");
  const [bg, setBg] = useState(false);
  const [members, setMembers] = useState("ollama=qwen3.5:0.8b,claude=haiku");
  const [judge, setJudge] = useState("");
  const [cPrompt, setCPrompt] = useState("");
  const [dock, setDock] = useState(false);

  const refresh = useCallback(() => {
    fetch("/api/agents").then((r) => r.json()).then((d) => setAgents(d.agents));
  }, []);
  const cli = useCli();
  useEffect(refresh, [refresh]);

  const drive = () => {
    const args = ["drive", seat, prompt];
    if (model) args.push("--model", model);
    if (bg) args.push("--bg");
    cli.run("drive", args, 600_000);
  };
  const council = () => {
    const args = ["council", cPrompt, "--members", members];
    if (judge) args.push("--judge", judge);
    if (dock) args.push("--dock");
    cli.run("council", args, 600_000);
  };

  return (
    <div className="fade-up mx-auto max-w-5xl px-6 py-6">
      <PageHeader
        title="Agents — the roster"
        sub="Seats and how to reach them. A new agent (Hermes, OpenClaw, Odysseus…) is a JSON drop-in at os/agents.d/ — no code."
      />

      {agents === null && <Empty text="probing seats…" />}
      {agents && (
        <div className="card mb-6 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-faint">
                <th className="px-4 py-2.5 font-medium">seat</th>
                <th className="px-2 py-2.5 font-medium">binary</th>
                <th className="px-2 py-2.5 font-medium">installed</th>
                <th className="px-2 py-2.5 font-medium">models</th>
                <th className="px-4 py-2.5 font-medium">notes</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((a) => (
                <tr key={a.name} className="border-b border-line last:border-0 hover:bg-elev/40">
                  <td className="px-4 py-2.5 font-mono text-ink">{a.name}</td>
                  <td className="px-2 py-2.5 font-mono text-xs text-muted">{a.binary}</td>
                  <td className="px-2 py-2.5">{a.available ? <Badge v="ok" /> : <Badge v="unavailable" />}</td>
                  <td className="max-w-[220px] px-2 py-2.5 text-xs text-muted">
                    {Object.entries(a.models).filter(([k, v]) => v && !k.startsWith("_")).map(([k, v]) => `${k}→${v}`).join(", ") || "—"}
                  </td>
                  <td className="max-w-[260px] px-4 py-2.5 text-xs text-faint">{a.notes}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        <div className="card px-4 py-4">
          <h2 className="mb-1 text-sm font-semibold">Drive one seat</h2>
          <p className="mb-3 text-xs text-faint">Explicit call = consent. Frontier (opus) still requires naming it here — never auto-driven.</p>
          <div className="mb-2 flex gap-2">
            <select className="input" value={seat} onChange={(e) => setSeat(e.target.value)}>
              {(agents || []).map((a) => <option key={a.name} value={a.name}>{a.name}</option>)}
              <option value="haiku">haiku (roster)</option>
              <option value="sonnet">sonnet (roster)</option>
              <option value="gemini-flash">gemini-flash (roster)</option>
            </select>
            <input className="input flex-1" placeholder="model (optional, e.g. haiku / qwen3.5:0.8b)" value={model} onChange={(e) => setModel(e.target.value)} />
          </div>
          <textarea className="input mb-2 h-24 w-full resize-none" placeholder="prompt…" value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          <div className="flex items-center gap-3">
            <button className="btn btn-accent" disabled={cli.busy || !prompt} onClick={drive}>
              {cli.busy && cli.label === "drive" ? "running…" : "▶ Drive"}
            </button>
            <label className="flex items-center gap-1.5 text-xs text-muted">
              <input type="checkbox" checked={bg} onChange={(e) => setBg(e.target.checked)} /> background session
            </label>
          </div>
        </div>

        <div className="card px-4 py-4">
          <h2 className="mb-1 text-sm font-semibold">Convene a council</h2>
          <p className="mb-3 text-xs text-faint">Same prompt → N seats in parallel; optional judge synthesizes. Every call lands on the trail.</p>
          <input className="input mb-2 w-full font-mono text-xs" placeholder="members: seat=model,seat=model" value={members} onChange={(e) => setMembers(e.target.value)} />
          <input className="input mb-2 w-full font-mono text-xs" placeholder="judge (optional): claude=sonnet" value={judge} onChange={(e) => setJudge(e.target.value)} />
          <textarea className="input mb-2 h-16 w-full resize-none" placeholder="council prompt…" value={cPrompt} onChange={(e) => setCPrompt(e.target.value)} />
          <div className="flex items-center gap-3">
            <button className="btn btn-accent" disabled={cli.busy || !cPrompt} onClick={council}>
              {cli.busy && cli.label === "council" ? "deliberating…" : "◈ Convene"}
            </button>
            <label className="flex items-center gap-1.5 text-xs text-muted">
              <input type="checkbox" checked={dock} onChange={(e) => setDock(e.target.checked)} /> dock the transcript
            </label>
          </div>
        </div>
      </div>

      {cli.output && (
        <div className="mt-5">
          <div className="mb-1 flex items-center justify-between">
            <span className="text-xs font-semibold text-muted">output</span>
            <button className="btn px-2 py-0.5 text-xs" onClick={cli.clear}>clear</button>
          </div>
          <pre className="console max-h-[420px] overflow-y-auto">{cli.output}{cli.busy ? "\n…" : ""}</pre>
        </div>
      )}
    </div>
  );
}
