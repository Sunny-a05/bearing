---
type: spec
status: active
last_updated: 2026-08-19
---

# The OS — kernel spec

Bearing's operational layer. The knowledge lives in `wiki/`; this directory is the
machinery that fills it and keeps it honest. Everything is **files** — markdown and
JSONL on your disk. The CLI and the UI are conveniences over those files, never the
source of truth, and deleting either loses nothing.

## Layers

| Layer | Lives in | Does |
|---|---|---|
| **Skills** | `os/skills/` | The loop itself — [[bearing]] composing [[grilling]] and [[wayfinder]] |
| **Planning** | `os/wayfinder/` | One map per effort too big for a session: destination, decisions, fog, tickets |
| **Dock** | `os/dock/` | Incoming knowledge: dedup → digest → your verdict → `raw/` or `library/` |
| **Orchestration** | `os/cli/orchestrator.py` | Which model does a piece of work, what it cost, what happened — spec in `os/orchestration.md` |
| **Registry** | `os/registry/` | One status card per active work item |
| **Connections** | `os/cli/settings.py` | Which model seats are switched on, and what we know about them |
| **Frontends** | `os/mcp/`, `os/ui/` | Detachable: an MCP server for your agent, a local web UI for you |

## Boot protocol

At the start of a session, an agent should:

1. Read `CLAUDE.md` (or `AGENTS.md`) — the schema and the operating rules.
2. Read `index.md` — the catalog of what the wiki already knows.
3. **If `os/wayfinder/` holds a map, read it** before asking anything. Re-asking a
   question the user already answered is the one failure that makes this pointless.
4. Consult `os/orchestration.md` before expensive work — if a cheaper tier can do the
   job, say so rather than doing it.

## Hard rules

1. All `CLAUDE.md` rules apply — flag contradictions, cite sources, never overwrite.
2. **Nothing dropped into the dock is ever deleted.** It is ingested or archived.
3. **The dock's decision step is human.** `digest` drafts, `file` executes; nothing
   in between is automated.
4. **Local-model output never lands in `wiki/` without review.** A local draft is a
   draft; `agentos.py review <run-id>` records that someone actually looked.
5. **Sources in `raw/` and `library/` are immutable.** They are moved, never edited.

## Session exit

Update any registry card you touched, append to `log.md`, and leave the map's
frontier accurate. The next session — yours or an agent's — starts from those three.
