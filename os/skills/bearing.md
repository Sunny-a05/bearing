---
name: bearing
type: skill
description: The Bearing loop — grill a loose idea until it is sharp, chart it as a map, then research the market into that map. Use whenever the user arrives with something plan-shaped.
status: active
related: [[grilling]], [[wayfinder]], [[DOCK]]
last_updated: 2026-08-19
---

# Bearing — the loop

**Every other AI writes your plan in an hour. Bearing makes sure it's the right plan.**

Three stages, in order, with a visible boundary between each: **grill → chart →
research**. This file is the whole loop. It composes [[grilling]] (stage 1) and
[[wayfinder]] (stage 2); stage 3 is the dock (`os/dock/DOCK.md`) pointed at the map.

Bearing is **not** a plan generator, it is **not** autonomous, and it is **not** a
co-founder. It asks; you decide.

---

## Stage 0 — the trigger: detect, then offer once

When input arrives, judge whether it is **plan-shaped** — a venture, a product, a
project, a decision with consequences and unknowns. If it is, **offer, once**:

> "This looks like a plan. I can grill you on it until it's sharp — maybe fifteen
> questions, one at a time, you answer them — or I can just answer your question.
> Which do you want?"

Rules:

1. **Offer, never assume.** Grilling is HITL by contract; interrogating someone who
   never consented is the fastest way to lose them in minute one.
2. **Ask once.** If they say no, answer the question normally and drop it. Do not
   re-offer later in the same session.
3. **Degrade gracefully.** "No" still gets a useful answer. Bearing is not a toll gate.

## Stage 1 — grill

Run [[grilling]] exactly as written: one question at a time, your recommended answer
attached to each, waiting for a real human answer before the next.

Look facts up — in the wiki, in the repo, on the web. Put only **decisions** to the
user. A grilling agent that answers its own questions has broken the contract.

**Stop when the plan converges** — when new questions stop changing the shape of the
answer, or when the user's answers start settling rather than branching.

## Stage 2 — chart, at a visible boundary

The transition out of grilling is **announced**, not a silent slide:

> "I think we've converged. I'm going to chart this as a map now — that's a
> destination, the decisions you just made, and the questions still open. Say stop
> if you'd rather keep grilling."

Then run [[wayfinder]]: write `os/wayfinder/<slug>/map.md` with the destination named,
the answers from stage 1 in **Decisions so far**, everything still fuzzy in **Not yet
specified**, and the questions sharp enough to state as ticket files under
`tickets/`. Wire `blocked_by` in a second pass.

**The map is the artifact the user leaves with.** It is a file on their disk. That is
the whole point of session one: they came with a loose idea and they leave with a plan
that is honest about its own incompleteness.

**Teach the map as you write it.** The frontier is the thing a first-time user has to
understand to get value from session two — say what a ticket is, what blocked means,
and what the frontier is, in one short pass. Do not assume the vocabulary.

## Stage 3 — research into the map

Research does not run by itself and it does not run everywhere. It becomes **runnable
tickets on the map, and the user picks which ones**.

> "Four of these are things I can go find out on my own: the competitor scan, the
> pricing anchors, the regulatory question, the market size. Which should I take?"

For each ticket the user picks:

1. Run the research. Use a **local model if one is installed**
   (`agentos.py drive ollama ...`); if not, fall back to the agent you are already
   running in. **No API key is ever required** — Bearing runs in the workspace the
   user already pays for.
2. Land findings in `os/dock/inbox/` as sources. Never write straight into `wiki/`.
3. Record the resolution on the ticket, close it, add the one-line gist to the map's
   **Decisions so far**, and graduate any fog the answer just made specifiable.

**Never resolve more than one ticket per session.**

## Stage 4 — triage, batched, and always human

At the **end** of the session — not per item — walk the docked material with the user
and decide what is kept. Run `os/dock/DOCK.md`; this skill only decides *when* to ask.

The **proposal** rule is corroboration:

- Agreed by **two or more independent sources** → propose `raw/` + a wiki page.
- **Single source** → propose `library/` (archived, never deleted, promotable later).
- **Single source that answers an open ticket on the map** → **surface it anyway**,
  flagged: *"one source only, but it answers ticket 03."* A lone source bearing on a
  live question is exactly the finding that corroboration would wrongly bury.

The proposal is a **draft**. The verdict is the user's, always, in conversation. Local
model output never decides (OS hard rule 4), and nothing dropped into the dock is ever
deleted — it is ingested or archived.

---

## The second session is the point

Session one ends with a map on disk. **Session two opens by reading it** — the
destination, the decisions, the frontier — and picks up where the last one stopped,
without re-asking a single question that was already answered.

That is the whole thesis. Other tools remember who you are; Bearing remembers **why
you decided what you decided**, because the reasoning is written down in the tickets
rather than compressed out of a chat log.

So: at the start of any session, if `os/wayfinder/` holds a map, **read it before
asking anything.** Opening with a question the user already answered is the one
failure that makes the product pointless.

## Boundaries

- **Never answer your own grilling question.**
- **Never auto-file** anything into `wiki/` — the dock's decision step is human.
- **Never claim more than you looked up.** Fog is a legitimate answer and belongs on
  the map as fog. A plan honest about what it does not know is the product.
- **Never run a live digest without saying it is running** — it takes over a minute on
  a long document and silence reads as broken.
