# os/mcp — MCP frontend on the Wiki OS

A third **detachable frontend** on the OS core, alongside `os/cli/` (terminal)
and `os/ui/` (browser). It exposes the wiki over the Model Context Protocol so
any MCP client (Claude Code, Cursor, …) reads and queries it as structured
tools/resources instead of scanning files.

## Durability contract (same as os/ui/)

- **It imports the core; the core never imports it.** Delete `os/mcp/` and the
  OS loses nothing — the wiki, CLI, and UI are untouched.
- **The core stays stdlib.** The one dependency (the `mcp` SDK) lives only here,
  in `requirements.txt`. `server.py` reads wiki files directly and shells
  nothing; milestones 2–3 will `import` `os/cli/` modules, never fork them.
- **Read/query only (milestone 1).** No wiki file is written by this server.

## What it exposes (milestone 1 — the wiki layer)

| Kind | Name | Purpose |
|---|---|---|
| resource | `wiki://index` | the catalog (`index.md`) |
| resource | `wiki://state` | cross-session handoff (`STATE.md`) |
| resource | `wiki://page/{slug}` | any wiki page by filename slug |
| tool | `wiki_search` | literal substring / filename lookup |
| tool | `wiki_query` | ranked retrieval — BM25 + tag boost + `[[graph]]` expansion, section-level chunks with `[[wiki-link]]` citations |

`wiki_query` is a **router, not a vector store**: at ~131 pages / ~115k tokens
the whole corpus fits in context, so the job is to surface the right 2–3 pages
cheaply. It leans on the two structures you hand-built — the `index.md` and the
`[[wiki-link]]` graph — which beat embeddings on a curated corpus this size.
(Semantic/local-embedding tier is deferred to a later, optional sidecar aimed at
`library/`, not the wiki. See `wiki/patterns/wiki-retrieval.md` if filed.)

## Run

```bash
pip install -r os/mcp/requirements.txt
python os/mcp/server.py            # stdio; a client launches it — no port
```

Use `py` instead of `python` if that's your Windows launcher (update `.mcp.json`
to match).

## Register with a client

`.mcp.json` at the repo root already registers it for Claude Code / Cursor:

```json
{ "mcpServers": { "bearing": { "command": "python",
  "args": ["os/mcp/server.py"] } } }
```

The path is **relative to the repo root**, so a client launched from inside the
repo needs no editing. Then `/mcp` in an interactive session to confirm `bearing`
connected. Or add it explicitly, with an absolute path to your clone:

```bash
claude mcp add bearing -- python "/absolute/path/to/bearing/os/mcp/server.py"
```

## Smoke test without a client

```bash
pip install "mcp[cli]"
mcp dev os/mcp/server.py           # opens the MCP Inspector to click the tools
```

## Roadmap

- **M1 (done 2026-07-24)** — wiki resources + `wiki_search` + `wiki_query`.
- **M2 (done 2026-07-24)** — `os_status` / `os_route` / `os_runs` / `dock_list`, read-only; lazy-imports `orchestrator` + `dockyard` from `os/cli/`.
- **M3** — `secretary_list` / `approve` / `edit` / `reject` (import `secretary`); sending stays human-gated (propose-first). Mutating dock tools (`dock_digest`/`dock_file`) also deferred behind explicit gating.
