"use client";
import { useCallback, useState } from "react";

export type CliState = { busy: boolean; label: string; output: string };

/** Run an allowlisted agentos.py subcommand via /api/exec and keep a console log. */
export function useCli(onDone?: () => void) {
  const [state, setState] = useState<CliState>({ busy: false, label: "", output: "" });

  const run = useCallback(
    async (label: string, args: string[], timeoutMs?: number) => {
      setState({ busy: true, label, output: `$ agentos.py ${args.join(" ")}\n` });
      try {
        const r = await fetch("/api/exec", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ args, timeoutMs }),
        });
        const d = await r.json();
        const out = [d.stdout, d.stderr && `\n[stderr]\n${d.stderr}`, !d.ok && `\n(exit ${d.code})`]
          .filter(Boolean)
          .join("");
        setState((s) => ({ busy: false, label: "", output: s.output + out }));
      } catch (e: any) {
        setState((s) => ({ busy: false, label: "", output: s.output + `\nUI error: ${e.message}` }));
      }
      onDone?.();
    },
    [onDone]
  );

  const clear = useCallback(() => setState({ busy: false, label: "", output: "" }), []);
  return { ...state, run, clear };
}
