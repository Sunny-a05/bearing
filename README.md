# Bearing

**Every other AI writes your plan in an hour. Bearing makes sure it's the right plan.**

Bearing is a planner-researcher that runs inside the AI agent you already use. You
bring a loose idea. It **grills** you until the idea is sharp, **charts** it as a map
with an explicit frontier, then **researches** the market into that map until the plan
is worth acting on.

Everything is markdown on your own disk. **No server, no account, no API key.**

Bearing is **not** a plan generator. It is **not** autonomous. It is **not** a
co-founder. It asks; you decide.

---

## What actually happens

**Session one — you get grilled, and you leave with a map.**
One question at a time, each with a recommended answer. When the plan converges,
Bearing says so out loud and writes `os/wayfinder/<your-plan>/map.md`: the
destination, every decision you just made, and — the part that matters — the
questions still open, written down as fog rather than papered over.

**Session two — it already knows your plan, and goes to find things out.**
It opens by reading the map, not by re-asking what you already answered. The open
questions become runnable research tickets, and you pick which ones it takes. What it
finds lands in the dock, and at the end of the session it walks you through what to
keep and what to archive. You decide every one of those; nothing files itself.

That is the whole thesis. Other tools remember *who you are*. Bearing remembers **why
you decided what you decided**, because the reasoning is written into the tickets
instead of being compressed out of a chat log.

---

## Install

Requires **Python 3.10+**. Nothing to `pip install` — the whole thing is standard
library. Node 18+ only if you want the optional local UI.

**1. Clone it.**

```bash
git clone https://github.com/Sunny-a05/bearing.git
```

**2. Open it in your agent.**

Whatever you already use — Claude Code, Codex, Cursor, Gemini CLI, or a chat window
you paste into. Bearing is a folder of markdown plus a stdlib CLI; there is no
connector to configure and no server to run.

```bash
cd bearing && claude
```

Your agent reads `CLAUDE.md` (or `AGENTS.md`) on the way in and picks up the loop from
`os/skills/bearing.md`.

**3. Check it can see itself.**

```bash
python os/cli/agentos.py status
```

**4. Describe something you are trying to plan** — a venture, a product, a decision
you are stuck on. Bearing will notice it is plan-shaped and offer to grill you. Say
yes.

### Optional — the local UI

A read-only management surface: dashboard, wiki graph, dock, library, connections.

```bash
cd os/ui && npm install && npm run dev
```

Then open <http://localhost:4123>.

### Optional — a local model

If [Ollama](https://ollama.com) is installed, Bearing uses it for the cheap work
(digesting documents, bulk classification) and keeps that work off your subscription
entirely. Without it, everything falls back to the agent you are already running in.
Nothing breaks either way.

---

## How it is laid out

| Path | What it is |
|---|---|
| `os/skills/bearing.md` | **The loop.** Read this first — it is the product |
| `os/skills/grilling.md` | Stage 1, forked from `mattpocock/skills` |
| `os/skills/wayfinder.md` | Stage 2, forked from `mattpocock/skills` |
| `os/wayfinder/` | Your maps. `README.md` is the tracker spec |
| `os/dock/DOCK.md` | How incoming material becomes knowledge |
| `wiki/` | Your knowledge base. Ships empty — it is yours, not ours |
| `raw/` · `library/` | Ingested sources · the archive that is never deleted |
| `os/cli/agentos.py` | The CLI. Standard library only — `status`, `query`, `dock`, `digest`, `file` |
| `os/cli/librarian.py` | Ranked retrieval over your wiki: `agentos.py query "..."` |
| `CLAUDE.md` / `AGENTS.md` | The schema every agent boots from |

---

## Two rules worth knowing before you start

**Grilling needs you actually there.** The agent is forbidden from answering its own
grilling questions. There is no unattended mode — that is the point, and it is why
the resulting plan is yours rather than the model's.

**Nothing you dock is ever deleted.** Material is either fully ingested into `raw/`
plus a wiki page, or archived into `library/` with a thin digest. Archived items can
be promoted later if they turn out to matter. The filing decision is always yours.

---

## Licence and affiliation

Bearing is released under the **MIT Licence** — see [LICENSE](./LICENSE).

`os/skills/grilling.md` and `os/skills/wayfinder.md` are forks of two MIT-licensed
skills from [mattpocock/skills](https://github.com/mattpocock/skills). The upstream
copyright notice travels with them in [NOTICE](./NOTICE), as that licence requires.
Bearing's copies are edited on purpose and are not synced upstream.

Built by Sun Potirangsee as student work at **Harbour.Space Institute of Technology** and the
**University of the Thai Chamber of Commerce (UTCC)**, under the double-diploma
programme.
