# Bearing

This is **Bearing** — a planner-researcher that runs inside the AI agent you already
use. You bring a loose idea; it grills you until the idea is sharp, charts it as a
map, then researches the market into that map until the plan is worth acting on.

**Every other AI writes your plan in an hour. Bearing makes sure it's the right plan.**

Everything is files on your disk. There is no server, no account, no API key, and
nothing to install — the CLI is standard library only.

- **The loop:** `./os/skills/bearing.md` — read this first
- **Knowledge base:** `./wiki/`
- **Raw sources (immutable):** `./raw/`
- **Library (archive — never deleted):** `./library/` — catalog at `./library/index.md`
- **Catalog:** `./index.md` · **Chronological log:** `./log.md`
- **Operational layer:** `./os/OS.md`

---

## Operating instructions

Any AI agent reading this file should follow these rules.

1. **Read the loop first.** `./os/skills/bearing.md` is the product. It composes
   `./os/skills/grilling.md` (stage 1) and `./os/skills/wayfinder.md` (stage 2).
2. **If a map exists, read it before asking anything.** Maps live in
   `./os/wayfinder/<slug>/map.md`. Opening a session with a question the user already
   answered is the one failure that makes this pointless.
3. **Read the index.** `./index.md` is designed to fit in a single read and give you a
   map of what is already known. Load `./wiki/context/` on any non-trivial request —
   it defines who the user is and how they like to work.
4. **Never answer your own grilling question.** Grilling is human-in-the-loop by
   contract. Look *facts* up; put *decisions* to the user and wait.
5. **Flag contradictions.** If a new source contradicts something already in the wiki,
   do not silently overwrite. Show both claims and ask which to keep.
6. **Cite sources.** Every factual claim on a wiki page should trace back to a file in
   `./raw/` via a wiki-link, or be explicitly marked as the user's stated preference.
7. **Prefer reuse over re-derivation.** If a matching page already exists in
   `./wiki/templates/`, `./wiki/prompts/`, `./wiki/stacks/` or `./wiki/patterns/`,
   start from it.
8. **Append to the log.** Every ingest, significant edit or lint pass gets an entry in
   `./log.md` as `## [YYYY-MM-DD] <type> | <title>`.
9. **Route before you spend.** Consult `./os/orchestration.md` before expensive work —
   if a cheaper tier can do the job, say so instead of doing it.
10. **Dock everything incoming.** When material arrives, run `./os/dock/DOCK.md`:
    dedup → digest → **your verdict** → `./raw/` + a wiki page, or `./library/`.
    Nothing dropped into the dock is ever deleted, and the verdict is never automated.

---

## Structure

```
./
├── CLAUDE.md             # This file — the schema / operating manual
├── AGENTS.md             # Same content, aliased for Codex and other agents
├── README.md             # Human-facing quickstart and install path
├── LICENSE               # MIT
├── NOTICE                # Third-party notices (forked skills)
├── index.md              # Catalog of every wiki page
├── log.md                # Chronological log of ingests and edits
│
├── wiki/                 # All AI-maintained knowledge (yours — ships empty)
│   ├── entities/         # Concrete things — projects, people, products
│   ├── concepts/         # Abstract ideas and theories
│   ├── skills/           # Reusable AI capability definitions
│   ├── prompts/          # Prompt templates and patterns
│   ├── templates/        # Project scaffolds with option trees
│   ├── stacks/           # Technology choices
│   ├── patterns/         # UI/UX/architecture patterns
│   ├── context/          # Personal context — about-me, preferences
│   ├── sources/          # One summary page per ingested source
│   └── _templates/       # Blank page templates (copy when creating new pages)
│
├── os/                   # The operational layer (see os/OS.md)
│   ├── OS.md             # Kernel spec — layers, boot protocol, hard rules
│   ├── orchestration.md  # Control plane — roster, routing, escalation, run trail
│   ├── skills/           # The loop: bearing.md + forked grilling.md, wayfinder.md
│   ├── wayfinder/        # Planning layer — one map per effort (README = the spec)
│   ├── dock/             # Incoming-knowledge dock — DOCK.md + inbox/
│   ├── registry/         # One status card per active work item (_template.md)
│   ├── agents.d/         # Drop-in agent definitions (JSON) — new agent, no code
│   ├── cli/              # The CLI (stdlib; pypdf optional): agentos.py (entry)
│   │                     #   + orchestrator.py + drivers.py + settings.py
│   │                     #   + extract.py + dockyard.py + librarian.py
│   └── ui/               # Local management UI (Next.js, localhost:4123)
│
├── raw/                  # Immutable source material, fully ingested
└── library/              # Archive tier — docked but not fully ingested. Never deleted.
    └── index.md
```

> **Structure-tree rule:** a directory that exists on disk but not in this tree is
> invisible to any agent booting from this file alone. When you create a top-level
> directory, add it here in the same session.

---

## Page conventions

### Linking — Obsidian-style wiki links

Use `[[page-name]]` (filename without extension, case-insensitive). For
disambiguation, `[[path/to/page|display text]]`.

Two forms that silently produce no edge — do not use them:

1. **Never put a file extension in a wiki link.** A link with `.md` in it does not
   resolve; the bare stem does.
2. **Never wrap a wiki link in a code span, and never escape the pipe.** Both defeat
   the parser. Use a bare link plus plaintext.

### YAML frontmatter — required on every wiki page

```yaml
---
type: entity | concept | skill | prompt | template | stack | pattern | context | source
tags: [short, lowercase, hyphenated]
status: draft | active | archived | stub
related: [[other-page-1]], [[other-page-2]]
sources: [[source-page]]
last_updated: YYYY-MM-DD
---
```

### Page body

1. **H1 title** matching the entity name.
2. **Summary** — two or three sentences: what this is, why it matters, how it connects.
3. **Body sections** — specific to the page type (see `wiki/_templates/`).
4. **Open questions** — what the wiki does not yet answer. Ingests try to resolve these.
5. **Changelog** — `- YYYY-MM-DD — short description`.

---

## Workflows

### INGEST — a new source arrives

1. Read the source end to end. If it has images, view them.
2. Summarize the key takeaways conversationally. Wait for guidance on what to emphasize.
3. Create `wiki/sources/<slug>.md` from `wiki/_templates/source.md`.
4. Edit the existing pages this source should update; add it to their `sources:` field.
5. Create pages for entities/concepts the source introduces that lack one.
6. Update `index.md`.
7. Append to `log.md`.
8. Report back: what was ingested, what was touched, what contradictions were flagged.

### QUERY — the user asks a question

1. Read `index.md`, identify candidate pages, read them in full.
2. Synthesize the answer and cite pages with wiki links.
3. If the answer is worth keeping, offer to file it back.

### LINT — periodic health check

Check for contradictions, stale claims, orphan pages, missing cross-references, tag
sprawl, and concepts mentioned across pages but lacking one of their own. Fix the
obvious, propose the rest.

---

## Page type catalog

Each type has a template in `wiki/_templates/`. Copy the matching one when creating a
page.

- **entity** — a concrete thing: project, person, product, company. `wiki/entities/`.
- **concept** — an abstract idea, framework or theory. `wiki/concepts/`.
- **skill** — a reusable AI capability. `wiki/skills/`.
- **prompt** — a prompt template or meta-prompt pattern. `wiki/prompts/`.
- **template** — a project scaffold with an option tree. `wiki/templates/`.
- **stack** — a technology option catalog. `wiki/stacks/`.
- **pattern** — a reusable UI, UX or architecture pattern. `wiki/patterns/`.
- **context** — personal context about you or your preferences. `wiki/context/`.
- **source** — a one-page summary of an item in `raw/`. `wiki/sources/`.

---

## Principles

- **The wiki compounds.** Every ingest and every interesting query leaves it richer.
- **AIs are the maintainers, humans are the curators.** You drop sources, ask
  questions and course-correct; the AI reads, files, cross-references and bookkeeps.
- **Nothing gets rediscovered.** A question answered once and filed is never
  re-derived from first principles.
- **A plan honest about its own incompleteness beats a confident wrong one.** Fog is a
  legitimate answer and belongs on the map as fog.
- **When in doubt, ask.** Better to pause than to write a wrong page that becomes
  load-bearing later.
