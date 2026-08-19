# Wayfinder — local-markdown tracker

No issue tracker (GitHub/Linear/etc.) is configured for this project, so wayfinder
maps and tickets live here as plain markdown, per the wayfinder skill's fallback
convention. This file documents the convention so any session — human or agent —
can read the tracker back correctly.

## Layout

```
os/wayfinder/
  <map-slug>/
    map.md              — the map issue
    tickets/
      <NN>-<slug>.md     — child issues, numbered for reading order
```

## Map frontmatter

```yaml
---
type: wayfinder-map
label: wayfinder:map
status: open | done
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
---
```

Body follows the wayfinder skill's map template exactly (Destination / Notes /
Decisions so far / Not yet specified / Out of scope).

## Ticket frontmatter

```yaml
---
id: <NN>-<slug>            # matches the filename, used for blocked_by references
map: <map-slug>
type: wayfinder-ticket
label: wayfinder:research | wayfinder:prototype | wayfinder:grilling | wayfinder:task
status: open | closed
assignee: null | <name>    # a ticket is "claimed" the moment this is non-null
blocked_by: [<ticket-id>, ...]
created: YYYY-MM-DD
closed: YYYY-MM-DD          # present only once closed
---

## Question

<the decision or investigation this ticket resolves>

## Resolution

<present only once closed — the answer>
```

## Tracker operations (the "native" features a real tracker provides elsewhere)

- **Claim** a ticket: set `assignee` to a non-null value before starting work.
- **Blocking**: a ticket is **unblocked** when every id in its `blocked_by` list
  points to a ticket whose `status: closed`.
- **Frontier**: the set of tickets where `status: open`, `assignee: null`, and
  every `blocked_by` entry is closed. To compute it: read every `tickets/*.md`
  file in the map's directory, filter on those three conditions.
- **Resolve**: append a `## Resolution` section to the ticket body, set
  `status: closed` and `closed: <date>`, then add one line to the map's
  **Decisions so far** section linking the ticket.
- **Out of scope**: set `status: closed`, do not add a `## Resolution` section
  or a Decisions-so-far line — instead add one line to the map's **Out of
  scope** section.

## Maps

No maps yet. Your first one is charted for you the first time a plan converges —
see `os/skills/wayfinder.md` for the method and `os/skills/bearing.md` for the
loop that drives it.
