# Agentic OS — Management UI

The management surface over the Bearing file-based OS. **The UI is a
read-view plus a remote control — it is not the OS.** If this app is deleted,
the OS loses nothing.

```
npm install        # once
npm run dev        # http://localhost:4123
```

## Durability contract (why this still builds in 2–3 years)

1. **Pinned versions, three runtime deps** (next / react / react-dom) — no UI
   kit, no graph library, no markdown library, no state library. The graph
   view is a hand-rolled canvas force simulation; markdown is an ~100-line
   renderer covering exactly what the wiki uses.
2. **The filesystem is the database.** `lib/os.ts` parses the wiki, registry,
   dock sidecars, `runs.jsonl`, and `sessions.json` directly. No schema
   migrations, no DB, no cache to invalidate.
3. **The Python CLI is the only mutation path.** Every action button POSTs an
   allowlisted argv array to `/api/exec`, which runs
   `python os/cli/agentos.py …`. The UI can never drift from the OS spec
   because it doesn't reimplement any OS behavior.
4. **Local-only.** No external requests, no fonts fetched, no telemetry, no
   auth surface. Do not expose the port beyond localhost — `/api/exec` shells
   the CLI by design.

## Map

| Route | What |
|---|---|
| `/` | Dashboard — registry, model usage, recent log, objective |
| `/graph` | Obsidian-style knowledge graph (canvas, pan/zoom/drag, page preview) |
| `/dock` | Inbox pipeline — digest / file to library / file to raw / redrop |
| `/library` | Archive tier — digests, claims, reactivate / promote |
| `/runs` | The run trail — every model call; rule-4 review buttons |
| `/sessions` | Detached background runs — live tail, kill |
| `/agents` | Seat probe + drive playground + council launcher |
| `/settings` | Connections — which seats are ON, auth, probes, change trail |

`OS_ROOT` env overrides root detection (default: walk up from cwd to the
folder containing `os/OS.md`).
