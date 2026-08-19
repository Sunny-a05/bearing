---
name: grilling
type: skill
description: Grill the user relentlessly about a plan or design. Use when the user wants to stress-test a plan before building, or uses any 'grill' trigger phrases.
origin: https://github.com/mattpocock/skills — skills/productivity/grilling
upstream_license: MIT (Copyright (c) 2026 Matt Pocock) — see /NOTICE
forked: 2026-08-19
status: active
---

> **Forked skill.** Origin `mattpocock/skills`, path `skills/productivity/grilling`,
> taken at the version installed 2026-07-10. Upstream is MIT; the notice travels in
> [/NOTICE](../../NOTICE). This fork is authoritative and is not synced upstream.

Interview me relentlessly about every aspect of this plan until we reach a shared understanding. Walk down each branch of the design tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing. Asking multiple questions at once is bewildering.

If a *fact* can be found by exploring the codebase or the wiki, look it up rather than asking me. The *decisions*, though, are mine — put each one to me and wait for my answer.

Do not enact the plan until I confirm we have reached a shared understanding.

## Bearing addendum — this skill is HITL by contract

An agent that answers its own grilling questions has broken the skill. There is no
unattended mode: if there is no human on the other end, stop and say so rather than
simulating one. Everything downstream in Bearing — the map, the research, the plan —
inherits its authority from the fact that a human actually answered these questions.
