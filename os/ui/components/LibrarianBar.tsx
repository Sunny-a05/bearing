"use client";
// Librarian agent bar for the graph detail panel. Ask questions about the
// selected wiki page (or the whole wiki). Routes through the OS driver layer
// (`/api/exec` → `agentos.py drive`), NOT a provider API — so every question
// lands on os/runs.jsonl for free, and the UI reimplements no OS behavior.
// Blocking call (drive isn't a streaming CLI): "thinking…" spinner + final
// answer in a chat thread. Design: wayfinder ticket 04-librarian-agent-design.
import { useCallback, useEffect, useRef, useState } from "react";

type Agent = { name: string; available: boolean };
type Msg = { role: "user" | "assistant"; content: string };

const CONTEXT_CAP = 6000; // chars of page markdown prepended to the prompt

// drivers.py prefixes drive stdout with a status banner, e.g.
// "[ollama -> ollama qwen3.5:0.8b] ok in 68.6s  (run r-fa743d5e)". Strip it so
// the chat bubble shows only the librarian's answer. No-op if absent.
function stripDriveBanner(s: string): string {
  return s.replace(/^\[[^\]]+\][^\n]*\(run r-[0-9a-f]+\)[^\n]*\r?\n\r?\n?/, "").trimStart();
}

function buildPrompt(
  pageLabel: string | null,
  pageContent: string | null,
  history: Msg[],
  question: string
): string {
  const persona = pageContent
    ? "You are the wiki librarian for this Bearing wiki. Answer ONLY from the wiki page provided below. Cite pages by their name. If the answer isn't in the page, say so plainly rather than guessing."
    : "You are the wiki librarian for this Bearing wiki. Answer from your general knowledge of the wiki; say when you're unsure.";
  const ctx = pageContent
    ? `\n\n--- WIKI PAGE: ${pageLabel} ---\n${pageContent.slice(0, CONTEXT_CAP)}\n--- END PAGE ---`
    : "";
  const priors = history.map((m) => `${m.role === "user" ? "Q" : "A"}: ${m.content}`).join("\n");
  return `${persona}${ctx}\n\n${priors ? priors + "\n" : ""}Q: ${question}\nA:`;
}

export default function LibrarianBar({
  pageId,
  pageLabel,
  pageContent,
}: {
  pageId: string | null;
  pageLabel: string | null;
  pageContent: string | null;
}) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [seat, setSeat] = useState("ollama");
  const [model, setModel] = useState("");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch("/api/agents")
      .then((r) => r.json())
      .then((d) => setAgents(d.agents || []))
      .catch(() => {});
  }, []);

  // fresh thread whenever the selected page changes
  useEffect(() => {
    setMessages([]);
    setInput("");
  }, [pageId]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, loading]);

  const submit = useCallback(
    async (e?: React.FormEvent) => {
      e?.preventDefault();
      const text = input.trim();
      if (!text || loading) return;
      const history = messages;
      setMessages((m) => [...m, { role: "user", content: text }]);
      setInput("");
      setLoading(true);
      const prompt = buildPrompt(pageLabel, pageContent, history, text);
      const args = ["drive", seat, prompt];
      if (model.trim()) args.push("--model", model.trim());
      try {
        const r = await fetch("/api/exec", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ args, timeoutMs: 600_000 }),
        });
        const d = await r.json();
        const answer = d.ok
          ? stripDriveBanner((d.stdout || "").trim()) || "(empty response)"
          : `Error: ${(d.stderr || "").trim() || `exit ${d.code}`}`;
        setMessages((m) => [...m, { role: "assistant", content: answer }]);
      } catch (err: any) {
        setMessages((m) => [...m, { role: "assistant", content: `Error: ${err.message}` }]);
      } finally {
        setLoading(false);
      }
    },
    [input, loading, messages, pageLabel, pageContent, seat, model]
  );

  const seatNames = agents.length ? agents.map((a) => a.name) : ["ollama", "claude", "gemini"];

  return (
    <div className="flex flex-col gap-2">
      {/* context line + seat picker */}
      <div className="flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[11px] text-faint">
          {pageLabel ? (
            <>
              Context: <span className="text-muted">{pageLabel}</span>
            </>
          ) : (
            "Full wiki context active"
          )}
        </span>
        {messages.length > 0 && !loading && (
          <button
            onClick={() => setMessages([])}
            className="shrink-0 text-[10px] text-faint transition hover:text-muted"
          >
            clear
          </button>
        )}
      </div>

      <div className="flex gap-2">
        <select
          className="input py-1 text-xs"
          value={seat}
          onChange={(e) => setSeat(e.target.value)}
          title="Which seat answers. Defaults to the local (free) tier."
        >
          {seatNames.map((n) => (
            <option key={n} value={n}>
              {n}
              {agents.find((a) => a.name === n && !a.available) ? " (not installed)" : ""}
            </option>
          ))}
        </select>
        <input
          className="input flex-1 py-1 text-xs"
          placeholder="model (optional)"
          value={model}
          onChange={(e) => setModel(e.target.value)}
        />
      </div>

      {/* thread */}
      {(messages.length > 0 || loading) && (
        <div
          ref={scrollRef}
          className="max-h-56 space-y-0 overflow-y-auto rounded-md border border-line bg-deep"
        >
          {messages.map((m, i) => (
            <div
              key={i}
              className={`border-b border-line/50 px-3 py-2 last:border-0 ${m.role === "user" ? "bg-panel/40" : ""}`}
            >
              <div className="mb-1 text-[10px] font-medium uppercase tracking-wider text-faint">
                {m.role === "user" ? "You" : "Librarian"}
              </div>
              <p className="whitespace-pre-wrap text-xs leading-relaxed text-ink">{m.content}</p>
            </div>
          ))}
          {loading && (
            <div className="px-3 py-2 text-xs text-faint">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent align-middle" />{" "}
              thinking…
            </div>
          )}
        </div>
      )}

      {/* input */}
      <form onSubmit={submit} className="flex items-end gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          rows={1}
          placeholder={pageLabel ? `Ask about ${pageLabel}…` : "Ask about your wiki…"}
          className="input flex-1 resize-none py-1.5 text-sm"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="btn btn-accent shrink-0 px-3 py-1.5 text-sm disabled:opacity-40"
          aria-label="Send"
        >
          {loading ? "…" : "↑"}
        </button>
      </form>
    </div>
  );
}
