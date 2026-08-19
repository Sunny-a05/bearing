---
type: spec
status: active
last_updated: 2026-08-19
---

# Orchestration — the control plane

Which model does a piece of work, what it is allowed to touch, and what happened.
Implemented by `os/cli/orchestrator.py`; this file is the policy it mirrors. **Token
economy is a first-class constraint** — a loop that grills and researches on your own
subscription must not be casually expensive.

## The roster

Seats are named capabilities, not products. A seat is reachable only if its
**connection** is switched on (`agentos.py tools`).

| Seat | Tier | Use for |
|---|---|---|
| `qwen3.5:0.8b`, `gemma*` | local (free) | Thin digests, extraction, bulk classification |
| `haiku` | cheap | Short structured transforms |
| `sonnet` | default | Filing, wiki writes, anything that decides |
| `opus`, `fable` | scarce | Architecture, long reasoning — asked for, not fallen into |
| `user` | human | The terminal rung. You. |

**The ladder is derived, not fixed.** `orchestrator.ladder_str()` renders only the
rungs actually reachable on this machine — a seat shows up if its connection is
installed *and* switched on — and it always terminates in `user`. So the ladder reads
differently for different people, truthfully:

| What you have | The ladder you see |
|---|---|
| Ollama + Claude Code | `ollama -> haiku -> sonnet -> opus/fable -> user` |
| Claude Code only | `haiku -> sonnet -> opus/fable -> user` |
| Ollama only | `ollama -> user` |
| Neither — just the agent you are in | `this agent -> user` |

The last row is the common case and it is not a degraded one: escalation still exists,
it just has one rung and then you. **The human rung is never filtered** — a person is
not a connection, and is always the last resort.

Escalation walks up it. It never skips to the top because the bottom was
inconvenient, and it **raises rather than substituting** when every seat in a chain is
switched off — an off switch that silently reroutes is not an off switch.

## Rules

1. **Cheapest seat that can actually do the job.** Digesting a document is not
   architecture work; do not price it like architecture work.
2. **A local draft is a draft.** Anything a local model produces needs review before
   it reaches `wiki/` (OS hard rule 4). `agentos.py review <run-id>` records it, with
   an optional verdict of `good` | `thin` | `wrong`.
3. **Knowledge decisions are not routed.** The orchestrator moves *work* between
   models; it never moves *content* into the wiki. Dock verdicts and wiki writes stay
   with a capable agent or with you.
4. **A probe records; it never decides.** Discovery reports what it found and never
   flips a seat on or off. You turn seats off; a flaky network does not.
5. **Off means off**, explicit calls included. Consent to use a seat is not consent to
   use a seat you had already switched off.

## The run trail

`os/runs.jsonl` — one append-only record per model call, handoff, skip, settings
change or review. It makes spend visible and makes rule 2 auditable instead of
aspirational. Read it with `agentos.py runs` or `runs --summary`.

Exit codes: **2** = policy refused this seat for this task class. **3** = every seat
in the chain is switched off. **1** = the seat ran and failed. Three different fixes,
so three different codes.
