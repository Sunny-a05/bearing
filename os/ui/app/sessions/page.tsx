"use client";
// Background sessions — detached agent runs (drive --bg). Live tail + kill.
import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Empty, PageHeader } from "@/components/ui";
import { useCli } from "@/components/useCli";

type Row = Record<string, any>;

export default function SessionsPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [tailSid, setTailSid] = useState<string | null>(null);
  const [tail, setTail] = useState("");
  const [follow, setFollow] = useState(true);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(() => {
    fetch("/api/sessions").then((r) => r.json()).then((d) => setRows(d.sessions));
  }, []);
  const cli = useCli(refresh);
  useEffect(refresh, [refresh]);

  const loadTail = useCallback((sid: string) => {
    fetch(`/api/sessions?tail=${sid}`).then((r) => r.json()).then((d) => setTail(d.log || ""));
  }, []);

  useEffect(() => {
    if (timer.current) clearInterval(timer.current);
    if (tailSid && follow) {
      loadTail(tailSid);
      timer.current = setInterval(() => {
        loadTail(tailSid);
        refresh();
      }, 3000);
    } else if (tailSid) {
      loadTail(tailSid);
    }
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [tailSid, follow, loadTail, refresh]);

  return (
    <div className="fade-up mx-auto max-w-5xl px-6 py-6">
      <PageHeader title="Sessions" sub="Detached background runs — os/sessions.json + per-run logs. Spawn from Agents or `drive --bg`." />

      <div className="mb-4"><button className="btn" onClick={refresh}>↻ Refresh</button></div>

      {rows === null && <Empty text="loading…" />}
      {rows !== null && rows.length === 0 && <Empty text="No background sessions yet — try drive <seat> “…” --bg, or the Agents page." />}

      {rows && rows.length > 0 && (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-[11px] uppercase tracking-wide text-faint">
                <th className="px-4 py-2.5 font-medium">sid</th>
                <th className="px-2 py-2.5 font-medium">agent</th>
                <th className="px-2 py-2.5 font-medium">status</th>
                <th className="px-2 py-2.5 font-medium">started</th>
                <th className="px-2 py-2.5 font-medium">task / prompt</th>
                <th className="px-4 py-2.5 text-right font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((s) => (
                <tr key={s.sid} className="border-b border-line last:border-0 hover:bg-elev/40">
                  <td className="px-4 py-2.5 font-mono text-xs text-ink">{s.sid}</td>
                  <td className="px-2 py-2.5 text-xs text-muted">{s.agent}{s.model ? ` · ${s.model}` : ""}</td>
                  <td className="px-2 py-2.5"><Badge v={s.status} /></td>
                  <td className="whitespace-nowrap px-2 py-2.5 font-mono text-xs text-faint">{s.started}</td>
                  <td className="max-w-[280px] truncate px-2 py-2.5 text-xs text-muted">{s.task}: {s.prompt_head}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 text-right">
                    <button className="btn mr-1.5 px-2 py-0.5 text-xs" onClick={() => setTailSid(tailSid === s.sid ? null : s.sid)}>
                      {tailSid === s.sid ? "hide" : "tail"}
                    </button>
                    {s.status === "running" && (
                      <button className="btn px-2 py-0.5 text-xs text-err" disabled={cli.busy}
                        onClick={() => cli.run("kill", ["sessions", s.sid, "--kill"])}>
                        kill
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tailSid && (
        <div className="mt-4">
          <div className="mb-1 flex items-center justify-between">
            <span className="font-mono text-xs text-muted">{tailSid}</span>
            <label className="flex items-center gap-1.5 text-xs text-faint">
              <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> follow (3s)
            </label>
          </div>
          <pre className="console max-h-96 overflow-y-auto">{tail || "(empty)"}</pre>
        </div>
      )}

      {cli.output && <pre className="console mt-4 max-h-60 overflow-y-auto">{cli.output}</pre>}
    </div>
  );
}
