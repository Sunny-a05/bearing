---
type: skill
tags: [agentic-os, dock, ingest, triage, memory]
status: active
related: [[OS]], [[orchestration]], [[skills/auto-researcher]]
sources: [[llm-wiki-pattern]]
last_updated: 2026-07-15
---

# The Dock — Incoming Knowledge Workflow (v3)

The Dock is where new material (a report, research paper, article, idea note, meeting output) **arrives and gets connected to what we already know** — or, if it isn't ready for that yet, **gets preserved instead of thrown away.** Nothing dropped into the dock is ever deleted. Everything ends up in exactly one of two permanent homes: `raw/` + a wiki page (fully integrated, "known"), or `library/` (archived, thin-indexed, retrievable later).

**Drop zone:** `os/dock/inbox/` — You (or any agent) drop files here. Like `raw/`, inbox files are never modified; they are moved out to `raw/` or `library/`, never edited in place, never deleted.

**Intake sources:** anything you drop, **plus claude-mem episodic observations.** The session-memory plugin is an *upstream intake source*, not a memory tier that bypasses the dock — salient observations are surfaced into `inbox/` and run the same pipeline. claude-mem never writes to `library/` or `wiki/` directly, and on conflict the curated wiki wins (see [[OS]] §Episodic memory).

**Status:** v3 **implemented** (2026-07-03) in `os/cli/` — `agentos.py` (commands: `dock`, `extract`, `digest`, `file`, `redrop`, `reactivate`, `enrich`, `promote`) + `extract.py` (universal text extraction: pdf/docx/pptx/xlsx/html/epub/odt/rtf/ipynb/…, stdlib-first, pypdf auto-used for PDFs incl. decryption; scanned PDFs flagged `needs OCR` → route to Gemini/Claude vision) + `dockyard.py` (sidecar YAML, dedup vs raw/+library/, reactivation, breadth-or-frequency promotion). One implementation note beyond the spec: promotion additionally requires `tier: rich` (the consolidation step runs INGEST against the cached claims, so enrichment is a prerequisite; `--force` overrides). Not yet shaken down against a real drop.

---

## The two-tier memory model

This pipeline is deliberately modeled on how biological memory consolidates, because the shape of the problem is the same: capture everything cheaply and fast, then only spend real effort organizing the things that turn out to matter.

| | **`library/`** | **`raw/` + `wiki/`** |
|---|---|---|
| Biological analog | Hippocampus — fast encoding, flexible, unorganized | Neocortex — slow to write, structured, schema-integrated |
| Write cost | Cheap (thin digest only) | Expensive (full INGEST: cross-linking, contradiction-check, curation) |
| Retrieval | Search required, not instant | Instant — `index.md` + wikilinks, "nothing gets rediscovered" |
| Who's in it | Everything that isn't obviously broadly valuable yet | Curated, cross-referenced, load-bearing knowledge |
| How items move up | **Consolidation** — triggered by reactivation (see below) | — |

**Where the metaphor deliberately breaks:** biological short-term memory decays — untouched memories fade and are gone. Ours doesn't, on purpose. Nothing in `library/` is ever pruned or deleted; it just stays cheap and unorganized until something gives it a reason to be organized. Don't import "and eventually forget it" logic from the analogy — that's the one part we're not copying.

---

## Pipeline

```
inbox/ → 0 DEDUP → 1 DIGEST & TRIAGE (thin, graphify) → 2 DECISION (Sonnet+)
                                                              │
                                                    ┌─────────┴─────────┐
                                                    ▼                   ▼
                                              3a INGEST            3b LIBRARY
                                          (raw/ + wiki page)   (thin digest, archived)
                                                                        │
                                                          (later, on demand) REACTIVATION
                                                          → rich digest (cached, scoped to the need)
                                                          → CONSOLIDATION CHECK
                                                          → promote to raw/+wiki, or stay enriched-in-library
                                                    │                   │
                                                    └─────────┬─────────┘
                                                              ▼
                                                            4 LOG
```

### 0. Dedup — before anything else runs, always

Cheap, deterministic, no model call:

1. **Exact match:** SHA-256 hash the inbox item; compare against every file under `raw/` (recursive, excluding `raw/index.md`, `raw/log.md`, `raw/.claude/`, `raw/desktop.ini`) **and every file under `library/`**. Identical hash against `raw/` → it's already fully ingested; discard the inbox copy (nothing lost, the real copy is already permanent). Identical hash against `library/` → it's a **re-drop of an archived item** — don't file it again, but log it as a **reactivation event** against that item's digest (see step 3b/reactivation below; a re-drop is itself a signal of renewed relevance, same as a project pulling the item into a task).
2. **Fuzzy match:** normalize the filename (lowercase, strip extension, collapse `-`/`_`/spaces) and check for substantial overlap against `index.md` (wiki sources) **and `library/index.md`** (archive catalog). A hit doesn't mean discard — it means "read that existing page/digest first, this might be a newer version rather than a true duplicate." Flag either way in the docking report.

Still deliberately **not** doing semantic/embedding dedup — a hash + filename check catches the real failure mode (re-dropping the same thing) without standing up a vector store. Revisit only if near-duplicate-but-differently-named items become a recurring problem.

### 1. Digest & Triage — cheap tier (Ollama per [[orchestration]]), one pass

This step **replaces both the old "triage note" and the old idea of a separate scoring pass.** It produces one structured artifact per item — the **thin digest**:

- **Entities:** people, projects, concepts, tools mentioned (the "graphify" pass — this is what makes it a digest and not just a summary).
- **Relationships:** short (subject, verb, object) triples between those entities — e.g. `(sls-estimator, uses, zustand)`. This is the graph; it's what lets a later reader see structure without reading prose.
- **Tags:** which registry card(s) (`os/registry/*.md`) this plausibly touches.
- **Urgency:** `routine` (batch it) | `worth-a-look` (mention next session) | `surface-now` (interrupt-worthy).
- **Verdict:** `ingest` | `library` | `ask-user`.

Route: qwen3 (~0.6B) first pass; escalate to gemma (~4B) within the local tier if the output looks thin (can't name entities, verdict is a hedge, fewer than the expected fields). Escalate out of Ollama to Haiku only if both local passes fail. **This is a draft, never a decision** — per [[OS]] hard rule 4, local-model output doesn't move an item anywhere by itself.

As of 2026-07-03, the Dock doesn't run this ladder itself — it hands the prompt to the **orchestrator** (task class `dock.digest`; see [[orchestration]]), which owns execution, escalation, and failure handling, and auto-logs every attempt to `os/runs.jsonl`. The exhausted-local-tier case now produces a recorded *handoff* to Haiku instead of just a note. Reviewing a draft digest and running `agentos.py review <run-id>` closes the rule-4 loop on the trail.

**The thin digest is intentionally shallow.** It's built for routing (where does this go, is it urgent) — not for answering specific questions later. Don't expect it to hold quotable facts; that's what the rich digest (step 3b/reactivation) is for, computed only when something actually needs it.

### 2. Decision — the matching step (Sonnet+)

Reads the thin digest (not the raw file — that's the point of step 1) plus `index.md` and the tagged registry cards:

1. **What does this attach to?** — which entity/concept/stack/pattern pages it would update; which registry card's "current focus" it affects.
2. **What does it conflict with?** — contradiction check (CLAUDE.md rule 5). Conflicts are surfaced to you, never silently resolved.
3. **Route:**
   - **Obviously and immediately valuable** (clear broad relevance, no ambiguity) → **3a INGEST**.
   - **Everything else that isn't junk** → **3b LIBRARY**. This is the default. Most dropped material should land here, not in the wiki — the wiki stays lean and high-signal; the library holds the long tail.
   - **Genuinely ambiguous / needs your judgment** → **ask-user**. Stays in `inbox/` (not moved to `library/`) until you resolve it — the existing 14-day staleness rule surfaces it if it sits too long.

### 3a. Ingest — standard INGEST workflow (unchanged)

Move the file to `raw/`, run the CLAUDE.md INGEST workflow (source page → update touched pages → create new pages → index). The resulting `wiki/sources/<slug>.md` page — summary + key claims — **is** the rich digest for anything that takes this path; no separate digest artifact needed, the wiki page already does the job.

**Citation-grounding check, when the item carries its own inline citations.** Applies to anything an agent *synthesized with external citations* rather than a plain human-dropped file — auto-researcher batches, subagent-drafted pages (e.g. content arriving via `outputs/`). A single raw/ drop has nothing to ground-check (the file itself is the source), so this doesn't apply there. See `[[skills/auto-researcher]]` Phase 5 (VERIFY) for the full spec: inline spot-check for ≤3 sources, a NotebookLM grounding pass for batches/4+ citations — added 2026-07-15 after a real mismatched-citation failure in a subagent draft. This is a manual step (NotebookLM has no consumer API), so it isn't part of the orchestrator's automated chain.

### 3b. Library — archive, not delete

Move the file to `library/` (flat, or by domain if it grows large enough to need it — not yet). Write a sidecar digest file, `library/<slug>.digest.yaml`:

```yaml
source: library/<filename>
dropped: YYYY-MM-DD
entities: [...]
relationships: [{from: ..., verb: ..., to: ...}]
tags: [registry-card-slugs]
urgency: routine | worth-a-look | surface-now
tier: thin              # thin | rich
claims: []              # populated only when upgraded to rich
reactivations: []        # [{date: YYYY-MM-DD, trigger: registry-card-slug | re-drop, note: ...}]
promoted: false
```

Add a one-line entry to `library/index.md` (same convention as the wiki's `index.md` — browsable without opening every digest file).

**Sidecar file, not embedded frontmatter**, because library items aren't always markdown (PDFs, JSON exports, etc.) — a digest that lives next to the source works for any file type; embedding only works for markdown.

### Reactivation & consolidation (on demand, not part of the initial pipeline)

This is what makes the library more than a graveyard. It happens whenever a library item becomes relevant again:

- **Trigger:** a project/task needs this item's content, *or* it gets re-dropped into the inbox (step 0 exact-match case above).
- **Action:** compute a **rich digest** — key claims, specific facts, quotes — scoped to what's actually needed right now (not a blind "extract everything" pass; targeted extraction against a real question produces better claims). Write the claims into the item's `claims:` field, set `tier: rich`. **This is cached** — the same item is never rich-digested twice; the second time anyone needs it, the claims are already there.
- **Log the reactivation:** append `{date, trigger, note}` to `reactivations:`.
- **Consolidation check** — promote the item to `raw/` + a real wiki page if, at this point, **either**:
  1. **Breadth:** the rich digest reveals the item touches 2+ registry cards, or
  2. **Frequency:** the item has now been reactivated 3+ times by the *same* registry card (repeated demand from one project is still evidence of value, even without breadth).
  
  Otherwise: leave it **enriched-but-parked** — `tier: rich`, `promoted: false`. It stays in `library/`, just no longer thin. Next time it's needed, the claims are already there — no re-work, only the consolidation check re-runs.
- **Promotion itself** runs the standard INGEST workflow against the now-rich digest (claims already extracted — INGEST's summarize step is mostly done), removes the sidecar `.digest.yaml`, removes the `library/index.md` line, and logs both the promotion and its trigger.

### 4. Log

- Append `## [YYYY-MM-DD] <ingest|library|promotion> | <title>` to `log.md`.
- Add a line to each touched registry card's **Dock history**.
- Remove the item from `inbox/` (it now lives in exactly one of `raw/` or `library/`).

---

## Rules

1. **Nothing is ever deleted.** Every inbox item ends up in `raw/` or `library/`. The only exception is a byte-identical exact-duplicate drop — its content already exists, so the redundant copy isn't stored, but the drop event itself is still logged as a reactivation, not silently ignored.
2. Inbox items, `raw/` items, and `library/` source files are all immutable once filed — corrections happen via new pages/digests, not edits to the original.
3. No item skips dedup or digest — even "obviously relevant" material gets both, since dedup is free and the digest is what step 2 reads instead of the raw file.
4. Digest & triage is always the cheapest capable tier; never open a frontier model on an unvetted document.
5. Auto-digest (Ollama) drafts; it never decides. Step 2 still requires Sonnet+ reading the thin digest and the flagged registry cards directly.
6. **Library is the default outcome**, not a fallback. Most drops should land here — that's what keeps the wiki lean. Ingest is for material that's clearly and immediately broadly relevant.
7. Rich digestion only happens on demand, and only once per item — cache the result, never redo it.
8. `ask-user` items stay in `inbox/`, not `library/`, until you resolve them.
9. An inbox item older than 14 days (still `ask-user`, undecided) is stale — surface it rather than silently defaulting it into the library.

## Open questions

- ~~CLI implementation~~ **Resolved 2026-07-03:** built in `os/cli/` (agentos.py + extract.py + dockyard.py) — sidecar format, library filing, reactivation, enrichment, promotion all live. ~~Remaining: verifying the Ollama tags against `ollama list`~~ **Resolved 2026-07-10 (agent-unification build):** the old guesses (`qwen3:0.6b`, `gemma3:4b`) didn't exist; verified tags are `qwen3.5:0.8b` / `gemma4:e2b`, pinned in `os/agents.d/ollama.json`. The orchestrator itself has now executed for real (digest-class local calls ok); the *dock-specific* shakedown — a real inbox drop through `digest` + `file` — is still pending.
- Once `library/` has real volume (100+ items), does it need sub-foldering (by date or domain), or does the flat + `index.md` catalog stay sufficient? Not worth deciding now.
- Should the LINT workflow (CLAUDE.md) gain a library-staleness check — "any item reactivated more than once that never hit the promotion bar" — as a periodic nudge? Leaning yes, but it's a lint-time addition, not new standalone automation; revisit when LINT next runs.
- Gemini access path and Claude plan reset cadence — still unresolved from [[orchestration]], unrelated to this design.

## Changelog

- 2026-07-15 — **Citation-grounding check added to the ingest path (3a).** Cross-references the new Phase 5 (VERIFY) in `[[skills/auto-researcher]]` — applies only to agent-synthesized content with its own inline external citations (auto-researcher batches, subagent drafts), not plain raw/ drops. Manual step (NotebookLM, no consumer API); prompted by a real mismatched-citation failure caught the same day in a subagent-drafted page.
- 2026-07-10 — **claude-mem registered as an intake source.** Episodic session memory feeds the dock like any dropped material (dedup → digest → decision); it never writes to `library/` or `wiki/` directly, and the wiki wins on conflict. See [[OS]] §Episodic memory. (session: starred-repos evaluation.)
- 2026-07-03 — **Execution de-orphaned onto the Orchestration layer.** `dockyard.thin_digest` no longer shells to Ollama or owns an escalation ladder — it passes the digest prompt to `orchestrator.run("dock.digest", …)`, which routes, executes, escalates, and auto-logs every attempt + handoff to `os/runs.jsonl`. Dockyard keeps only the prompt, parsing, and thin-output validator. Behavior of `agentos.py digest` is unchanged from the outside. (session: orchestration layer build.)
- 2026-07-02 — v1 created (session: agentic-os scaffold).
- 2026-07-02 — v2: dedup step (hash + fuzzy match), scoring replaced with tag+urgency, Ollama auto-triage design (session: dock deep-design).
- 2026-07-03 — **v3 implemented.** `os/cli/` gains extract.py (universal text extraction — stdlib for docx/pptx/xlsx/html/epub/odt/rtf/ipynb + built-in PDF parser; pypdf auto-used when installed, incl. empty-password decryption; scanned PDFs flagged for Gemini/Claude vision) and dockyard.py (sidecar YAML emit/parse, dedup extended to library/, filing, reactivation, enrich, promotion). agentos.py rewired: `digest` replaces `triage` (kept as alias); new `extract`, `file`, `redrop`, `reactivate`, `enrich`, `promote`. Implementation addition: promotion requires `tier: rich` first (INGEST runs against cached claims; `--force` overrides). Tested end-to-end on a scratch tree (frequency + breadth promotion, re-drop reactivation, hostile-string YAML round-trip). (session: dock v3 build.)
- 2026-07-02 — **v3: full redesign.** Digest & triage merged into one structured pass (entities + relationships = "graphify", replacing the flat triage note). Introduced `library/` as a permanent third outcome — nothing is deleted, low-value/unmatched items are archived with a thin digest instead. Two-layer digest (thin at dock time, rich computed lazily on reactivation, cached once computed). Promotion rule: breadth (2+ registry cards) OR frequency (3+ reactivations by the same card). Explicit two-tier memory framing (hippocampus/neocortex analogy, with the no-decay deviation called out). Re-drops of archived items now count as reactivation events via dedup. (session: dock v3 design — thin-vs-rich tradeoff + memory-brain framing discussion.)
