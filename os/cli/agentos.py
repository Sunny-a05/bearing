#!/usr/bin/env python3
"""agentos — thin CLI for the Bearing OS (stdlib only; pypdf optional for PDFs).

Companion modules in this folder: orchestrator.py (the Orchestration layer —
routing, execution, escalation, run-records; spec: os/orchestration.md),
extract.py (universal text extraction), dockyard.py (dock mechanics —
spec: os/dock/DOCK.md). The OS is file-based; this CLI is convenience, not a
dependency.

Commands:
  status                         registry dashboard + inbox + library
  route "task text"              resolve task -> model chain (os/orchestration.md)
  runs [-n N | --summary]        the run trail — every model call/handoff/review
  log-run <task> --model M ...   agent seats report their work into the trail
  review <run-id> [--note]       mark a local-model output as reviewed (rule 4);
                                 --verdict good|thin|wrong records what the
                                 reviewer CONCLUDED, not just that they looked
  new <slug>                     scaffold a registry card from _template.md

  agents                         every known seat + is its CLI actually installed
                                 (add agents via os/agents.d/*.json — no code)
  tools                          the Connections layer (NESTED family): which
                                 seats are switched ON and what we know about
                                 them — tools | tools enable|disable <seat> |
                                 tools probe [seat] | tools set <seat> k=v.
                                 enable/disable land on the run trail as
                                 `kind: settings`
  drive <seat> "prompt"          run ONE seat now (claude/gemini/ollama/... or
                                 haiku/sonnet/gemini-pro/...); --bg for background;
                                 --expect RE / --min-chars N record `thin` when
                                 the answer comes back but doesn't hold up
  sessions [sid] [--tail|--kill] background runs — registry os/sessions.json
  loop <task> "prompt" --every N recurring runs through the orchestrator;
                                 --times M / --until-ok bound it

  dock                           list inbox + dedup (raw/ AND library/)
  extract <file> [--password]    pull plain text out of any file (pdf/docx/...)
  digest [item] [--model M]      thin digest via local Ollama -> draft
                                 sidecar <item>.digest.yaml next to the inbox file
  file <item> --to library|raw   execute the routing decision (made by you)
  redrop <item>                  handle an exact-duplicate drop (logs reactivation)
  reactivate <slug> --trigger C  log a library reactivation + promotion check
  enrich <slug> <claims.txt>     upgrade a library item to tier: rich (+ --tags)
  promote <slug> [--force]       consolidation mechanics library -> raw/ (+ INGEST to-do)

The DECISION step (DOCK.md step 2) stays with you — `digest` drafts, `file`
executes; nothing in between is automated. Local-model output never decides
(OS hard rule 4).
"""
import argparse
import json
import re
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dockyard as dy                                       # noqa: E402
import drivers as drv                                       # noqa: E402
import orchestrator as orc                                  # noqa: E402
import settings as st                                       # noqa: E402
from extract import extract as extract_file                 # noqa: E402

DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent


# ------------------------------------------------------------------ helpers

def frontmatter(path: Path) -> dict:
    import re
    meta = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return meta
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return meta
    for line in m.group(1).splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta


def _print_digest(d: dict):
    print(f"  gist:     {d.get('gist') or '—'}")
    print(f"  entities: {', '.join(d.get('entities', [])) or '—'}")
    rels = d.get("relationships", [])
    if rels:
        print("  graph:    " + "; ".join(f"({r.get('from')} —{r.get('verb')}→ {r.get('to')})"
                                         for r in rels))
    print(f"  tags:     {', '.join(d.get('tags', [])) or 'none'}")
    print(f"  urgency:  {d.get('urgency') or '—'}    verdict (draft): {d.get('verdict') or '—'}")
    for n in d.get("notes", []) or []:
        print(f"  note:     {n}")


# ----------------------------------------------------------------- commands

def cmd_status(root: Path):
    reg = dy.P(root)["registry"]
    cards = sorted(p for p in reg.glob("*.md") if not p.name.startswith("_")) if reg.exists() else []
    print(f"BEARING — STATUS {date.today().isoformat()}")
    print(f"{'project':<18} {'domain':<9} {'status':<8} {'prio':<7} {'tier':<7} updated")
    print("-" * 66)
    for card in cards:
        fm = frontmatter(card)
        print(f"{fm.get('project', card.stem):<18} {fm.get('domain','?'):<9} "
              f"{fm.get('status','?'):<8} {fm.get('priority','?'):<7} "
              f"{fm.get('default-tier','?'):<7} {fm.get('last_updated','?')}")
    items = dy.inbox_items(root)
    print(f"\nDock inbox: {len(items)} item(s) awaiting triage" + (" — run `dock`" if items else ""))
    lib = dy.P(root)["library"]
    if lib.exists():
        n_src = sum(1 for f in lib.iterdir()
                    if f.is_file() and f.name.lower() not in dy.LIB_EXCLUDE
                    and not f.name.endswith(dy.DIGEST_SUFFIX))
        n_rich = sum(1 for f in lib.glob(f"*{dy.DIGEST_SUFFIX}")
                     if "tier: rich" in f.read_text(encoding="utf-8"))
        print(f"Library: {n_src} archived item(s) ({n_rich} rich)")
    state = root / "STATE.md"
    if state.exists():
        age = (datetime.now() - datetime.fromtimestamp(state.stat().st_mtime)).days
        flag = "  << STALE — update on next session" if age > 7 else ""
        print(f"STATE.md last modified: {age} day(s) ago{flag}")


def cmd_route(root: Path, task: str):
    """Routing is the orchestrator's routing function (os/orchestration.md).
    `root` is what lets it read the connections layer — without it, `route`
    would keep describing seats that are switched off."""
    print(orc.resolve(task, root=root).describe())


def cmd_runs(root: Path, n: int, summary: bool, days: int):
    if summary:
        print(orc.summarize(root, days=days))
        return
    records = list(orc.iter_runs(root))
    if not records:
        print("no run records yet — os/runs.jsonl is written by the orchestrator "
              "on every model call, handoff, log-run, and review.")
        return
    for r in records[-n:]:
        kind = r.get("kind", "?")
        who = r.get("model") or r.get("to") or r.get("of", "?")
        extra = r.get("outcome") or r.get("note", "")
        item = f"  [{r['item']}]" if r.get("item") else ""
        print(f"{r.get('ts','?')}  {r.get('run','?')}  {kind:<10} "
              f"{r.get('task',''):<15} {who:<14} {extra}{item}")


def cmd_log_run(root: Path, task: str, model: str, outcome: str,
                item: str, note: str, reviewed: bool):
    rec = orc.log_agent_run(root, task, model, outcome,
                            item=item, note=note, reviewed=reviewed)
    print(f"logged {rec['run']} — {model} on '{task}' ({outcome}). "
          "The run trail (os/runs.jsonl) now includes this agent-seat work.")


def cmd_review(root: Path, run_id: str, note: str, verdict: str):
    try:
        rec = orc.mark_reviewed(root, run_id, note=note, verdict=verdict)
    except KeyError as e:
        sys.exit(f"error: {e.args[0]}")
    except ValueError as e:
        sys.exit(f"error: {e}")
    print(f"review recorded ({rec['run']}) for {run_id} — "
          "OS hard rule 4 satisfied for that output.")
    if rec.get("verdict"):
        print(f"verdict: {rec['verdict']} — this is the quality signal; "
              "`runs --summary` counts it separately from completion.")
    else:
        print("no verdict given — recorded as 'looked, didn't say'. Pass "
              f"--verdict {'|'.join(orc.REVIEW_VERDICTS)} to say what you concluded.")


def cmd_new(root: Path, slug: str):
    reg = dy.P(root)["registry"]
    dest = reg / f"{slug}.md"
    if dest.exists():
        sys.exit(f"error: {dest} already exists")
    shutil.copy(reg / "_template.md", dest)
    text = dest.read_text(encoding="utf-8")
    text = text.replace("project: <slug — matches wiki entity page if one exists>", f"project: {slug}")
    text = text.replace("last_updated: YYYY-MM-DD", f"last_updated: {date.today().isoformat()}")
    dest.write_text(text, encoding="utf-8")
    print(f"created {dest.relative_to(root)} — fill in domain/status/priority/tier and body.")


def cmd_dock(root: Path):
    items = dy.inbox_items(root)
    if not items:
        print("Dock inbox is empty.")
        return
    print(f"{len(items)} item(s) awaiting triage (pipeline: os/dock/DOCK.md):")
    for p in sorted(items):
        age = (datetime.now() - datetime.fromtimestamp(p.stat().st_mtime)).days
        stale = f"  << STALE (>{dy.STALE_DAYS}d) — surface it" if age > dy.STALE_DAYS else ""
        drafted = "  [digested]" if dy.draft_sidecar_path(p).exists() else ""
        print(f"  - {p.name}  ({p.stat().st_size:,} bytes, {age}d old){stale}{drafted}")
        dd = dy.dedup_check(p, root)
        if dd["exact_raw"]:
            print(f"      DEDUP: exact match -> {dd['exact_raw']} (already ingested)"
                  f" — run `redrop {p.name}`")
        elif dd["exact_library"]:
            print(f"      DEDUP: exact match -> {dd['exact_library']} (archived)"
                  f" — run `redrop {p.name}` to log the reactivation")
        elif dd["fuzzy"]:
            print(f"      DEDUP: {len(dd['fuzzy'])} fuzzy title match(es) — read before filing:")
            for hit in dd["fuzzy"][:3]:
                print(f"        · {hit}")
        else:
            print("      DEDUP: no match — proceed to `digest`")


def cmd_extract(path_str: str, password: str, out: str):
    r = extract_file(path_str, password=password)
    print(r.summary(), file=sys.stderr)
    if out:
        Path(out).write_text(r.text, encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    else:
        print(r.text)
    sys.exit(0 if r.ok else 1)


def cmd_digest(root: Path, item_name: str, model: str):
    items = dy.inbox_items(root)
    if item_name:
        items = [p for p in items if p.name == item_name]
        if not items:
            sys.exit(f"error: {item_name} not found in inbox")
    if not items:
        print("Dock inbox is empty — nothing to digest.")
        return
    print("THIN DIGEST (graphify, local tier) — DRAFT ONLY per DOCK.md rule 5: "
          "a Sonnet+ agent or you still makes the call.\n")
    for p in items:
        dd = dy.dedup_check(p, root)
        if dd["exact_raw"] or dd["exact_library"]:
            where = dd["exact_raw"] or dd["exact_library"]
            print(f"=== {p.name} ===\n  SKIPPED — exact duplicate of {where}. "
                  f"Run `redrop {p.name}`.\n")
            continue
        print(f"=== {p.name} ===")
        d = dy.thin_digest(p, root, model=model)
        ex = d.pop("extraction", None)
        if ex is not None:
            print(f"  extract:  {ex.method}, {len(ex.text):,} chars"
                  + (" — NEEDS OCR" if ex.needs_ocr else ""))
            for w in ex.warnings:
                print(f"  warning:  {w}")
        _print_digest(d)
        if d.get("entities") or d.get("gist") or d.get("notes"):
            sc = dy.save_draft(p, d)
            print(f"  draft sidecar -> {sc.relative_to(root)}")
        print()
    print("Next: a Sonnet+ agent reads the drafts + index.md + tagged registry "
          "cards, then runs `file <item> --to library|raw` (DOCK.md step 2).")


def cmd_file(root: Path, item_name: str, to: str):
    inbox = dy.P(root)["inbox"]
    item = inbox / item_name
    if not item.is_file():
        sys.exit(f"error: {item_name} not found in inbox")
    dd = dy.dedup_check(item, root)
    if dd["exact_raw"] or dd["exact_library"]:
        where = dd["exact_raw"] or dd["exact_library"]
        sys.exit(f"refusing: exact duplicate of {where} — run `redrop {item_name}` instead")
    if to == "library":
        res = dy.file_to_library(item, root)
        print(f"archived: library/{res['dest'].name}")
        print(f"sidecar:  library/{res['sidecar'].name}  (slug: {res['slug']})")
        print(f"catalog + log.md updated; dock history: {', '.join(res['cards']) or 'no cards tagged'}")
        print("Item is immutable from here; it comes back via reactivation (DOCK.md).")
    else:  # raw
        res = dy.file_to_raw(item, root)
        print(f"moved to raw/{res['dest'].name} — INGEST workflow now pending (agent work):")
        print("  1. wiki/sources/<slug>.md (this becomes the rich digest)")
        print("  2. update touched pages + frontmatter sources:")
        print("  3. create missing entity/concept pages")
        print("  4. update index.md; append log.md `ingest` entry")
        if res["digest"]:
            print("\nDraft digest to seed the source page:")
            _print_digest(res["digest"])


def cmd_redrop(root: Path, item_name: str):
    inbox = dy.P(root)["inbox"]
    item = inbox / item_name
    if not item.is_file():
        sys.exit(f"error: {item_name} not found in inbox")
    dd = dy.dedup_check(item, root)
    if dd["exact_library"]:
        sc, d = dy.sidecar_for_file(dd["exact_library"].name, root)
        if sc is None:
            sys.exit(f"error: {dd['exact_library'].name} has no sidecar — fix the library catalog first")
        slug = sc.name[:-len(dy.DIGEST_SUFFIX)]
        d, (ok, reason) = dy.reactivate(slug, "re-drop", f"re-dropped as {item_name}", root)
        dy._try_unlink(item)
        draft = dy.draft_sidecar_path(item)
        if draft.exists():
            dy._try_unlink(draft)
        print(f"reactivation logged on library/{sc.name} (re-drop); inbox copy discarded "
              "(the one allowed delete — content already archived).")
        print(f"promotion check: {'PROMOTE — ' + reason if ok else reason}")
        if ok:
            print(f"run: agentos.py promote {slug}")
    elif dd["exact_raw"]:
        dy.append_log(root, "reactivation", item_name,
                      [f"re-drop of already-ingested `{dd['exact_raw'].relative_to(root)}` — "
                       "inbox copy discarded"])
        dy._try_unlink(item)
        print(f"already fully ingested at {dd['exact_raw'].relative_to(root)} — "
              "drop logged, inbox copy discarded.")
    else:
        sys.exit("not an exact duplicate — use `digest` + `file` instead")


def cmd_reactivate(root: Path, slug: str, trigger: str, note: str):
    d, (ok, reason) = dy.reactivate(slug, trigger, note, root)
    print(f"reactivation logged ({len(d['reactivations'])} total) on library/{slug}{dy.DIGEST_SUFFIX}")
    if d.get("tier") == "thin":
        print("tier is still THIN — compute the rich digest now (agent work, scoped to the "
              "actual need; escalate more readily than for thin work, per os/orchestration.md), "
              f"then: agentos.py enrich {slug} <claims.txt>")
    else:
        print("tier is RICH — claims already cached, no re-work needed.")
    print(f"promotion check: {'PROMOTE — ' + reason if ok else reason}")
    if ok:
        print(f"run: agentos.py promote {slug}")


def cmd_enrich(root: Path, slug: str, claims_file: str, tags: str):
    claims = [l.strip() for l in Path(claims_file).read_text(encoding="utf-8").splitlines()
              if l.strip() and not l.strip().startswith("#")]
    if not claims:
        sys.exit(f"error: no claims found in {claims_file}")
    add_tags = [t for t in (tags or "").split(",") if t.strip()]
    d, (ok, reason) = dy.enrich(slug, claims, add_tags, root)
    print(f"enriched -> tier: rich ({len(d['claims'])} claims cached, "
          f"tags: {', '.join(d['tags']) or 'none'})")
    print(f"promotion check: {'PROMOTE — ' + reason if ok else reason}")
    if ok:
        print(f"run: agentos.py promote {slug}")


def cmd_promote(root: Path, slug: str, force: bool):
    res, reason = dy.promote(slug, root, force=force)
    if res is None:
        sys.exit(f"not promoting: {reason}\n(use --force to override — but the bar exists "
                 "to keep the wiki lean)")
    print(f"promoted: -> raw/{res['dest'].name}  ({res['reason']})")
    print("sidecar retired, catalog line removed, log.md updated.")
    print("\nINGEST workflow now pending (agent work) — the cached digest to build from:")
    _print_digest(res["digest"])
    for c in res["digest"].get("claims", []):
        print(f"  claim:    {c}")


def cmd_agents(root: Path):
    print("KNOWN SEATS (built-ins + os/agents.d/*.json — add agents there, not in code)")
    print(f"{'seat':<9} {'binary':<9} {'installed':<10} {'tier':<8} models / notes")
    print("-" * 78)
    for row in drv.probe(root):
        avail = "YES" if row["available"] else "no"
        models = ", ".join(f"{k}={v}" for k, v in row["models"].items()
                           if v and not k.startswith("_"))
        print(f"{row['name']:<9} {row['binary']:<9} {avail:<10} {row['tier']:<8} "
              f"{models or '-'}")
        if row["notes"]:
            print(f"{'':<9} {'':<9} {'':<10} {'':<8} ^ {row['notes']}")
    print("\nRoster seats reachable through drivers: "
          + ", ".join(f"{s} -> {a}" for s, (a, _) in orc.SEAT_DRIVERS.items()))
    print("Frontier guard: " + ", ".join(orc.FRONTIER_SEATS)
          + " is never auto-driven — name it explicitly.")


# -------------------------------------------------------------------- tools
# The Connections layer's command surface (map ticket 02). `agents` answers
# "is the binary there"; `tools` answers "is it switched ON, and what do we
# know about it" — spec vs state, the split settings.py exists to keep.

_AUTH_BAD = ("needs-auth", "missing-binary", "missing-key")


def _tools_table(rows: list):
    """One line per connection. The leading marker column is the point: a
    disabled or unauthenticated seat has to be findable by eye in a plain
    terminal, without colour, which is all you read before asking 'why
    didn't that route'."""
    if not rows:
        print("no connections known — add a seat spec in os/agents.d/ "
              "(settings.json is written mechanically, never by hand)")
        return
    w = max([9] + [len(r["name"]) for r in rows])
    print(f"CONNECTIONS — os/settings.json (state) x os/agents.d/ (how to reach)")
    print(f"  {'seat':<{w}} {'kind':<11} {'on?':<4} {'auth':<14} "
          f"{'last probe':<17} detail")
    print("-" * (w + 62))
    for r in rows:
        mark = "x" if not r["enabled"] else ("!" if r["auth"] in _AUTH_BAD else " ")
        detail = r.get("probe") or r.get("note") or ""
        if r.get("api_key_env"):
            detail = f"${r['api_key_env']}  {detail}"
        print(f"{mark} {r['name']:<{w}} {r['kind']:<11} "
              f"{('on' if r['enabled'] else 'OFF'):<4} {r['auth']:<14} "
              f"{r.get('last_probe', '')[:16]:<17} {detail[:44]}")
    off = [r["name"] for r in rows if not r["enabled"]]
    bad = [r["name"] for r in rows if r["enabled"] and r["auth"] in _AUTH_BAD]
    print()
    print(f"  x = disabled (routing skips it)   ! = enabled but not usable yet")
    if off:
        print(f"  OFF: {', '.join(off)} — re-enable with `tools enable <seat>`")
    if bad:
        print(f"  !!   {', '.join(bad)} — enabled but auth is not ok; "
              "`tools probe <seat>` re-checks")
    if not off and not bad:
        print("  every known connection is on and authenticated.")


def cmd_tools(root: Path):
    _tools_table(st.status_rows(root))


def cmd_tools_toggle(root: Path, seat: str, enabled: bool, note: str):
    known = st.connections(root)
    if seat not in known:
        print(f"note: '{seat}' has no spec in os/agents.d/ and no stored entry — "
              "creating one. Check the spelling if that wasn't intended.",
              file=sys.stderr)
    entry = st.set_enabled(seat, enabled, root=root, note=note)
    word = "enabled" if enabled else "disabled"
    if not entry.get("changed"):
        print(f"{seat} was already {word} — no change, nothing recorded "
              "(the trail holds changes, not restatements).")
        return
    print(f"{seat} -> {word}   (run {entry.get('run', '?')} on os/runs.jsonl)")
    if not enabled:
        print("routing now skips this seat and records the skip; `drive`, "
              "`drive --bg` refuses it too. `agents` still shows "
              "the spec — the seat exists, it is switched off.")


def cmd_tools_probe(root: Path, seat: str):
    if seat and seat not in st.connections(root):
        sys.exit(f"error: no connection named '{seat}' — run `tools` for the list")
    results = [st.probe(seat, root)] if seat else st.probe_all(root)
    for r in results:
        flag = "!" if r["auth"] in _AUTH_BAD else " "
        print(f"{flag} {r['name']:<12} {r['auth']:<14} {r['probe']}")
    print("\nA probe records what it found; it never flips `enabled`. "
          "You turn seats off; discovery does not.")


def cmd_tools_set(root: Path, seat: str, assignment: str):
    if "=" not in assignment:
        sys.exit("error: expected key=value, e.g. "
                 "`tools set openrouter api_key_env=OPENROUTER_API_KEY`")
    key, _, raw = assignment.partition("=")
    key, raw = key.strip(), raw.strip()
    low = raw.lower()
    value = True if low == "true" else False if low == "false" else raw
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value):
        value = int(value)
    try:
        entry = st.set_field(seat, key, value, root=root)
    except ValueError as e:
        sys.exit(f"refused: {e}")
    if not entry.get("changed"):
        print(f"{seat}.{key} was already {value!r} — no change, nothing recorded.")
        return
    print(f"{seat}.{key} = {value!r}   (run {entry.get('run', '?')})")

def _output_validator(expect: str, min_chars: int):
    """Build the validator orc.drive_seat() takes, out of the two checks a CLI
    can honestly express. Returns None when neither flag was given — no
    validator means the recorded outcome stays liveness-only ("the process
    exited with output"), which is the pre-ticket-17 behavior and still the
    default. You only get a quality signal by asking for one."""
    if not expect and not min_chars:
        return None
    rx = None
    if expect:
        try:
            rx = re.compile(expect, re.I | re.S)
        except re.error as e:
            sys.exit(f"error: --expect is not a valid regex: {e}")

    def validate(out):
        text = (out or "").strip()
        if min_chars and len(text) < min_chars:
            return False, text, f"{len(text)} chars, --min-chars {min_chars}"
        if rx and not rx.search(text):
            return False, text, f"no match for --expect {expect!r}"
        return True, text, ""

    return validate


def cmd_drive(root: Path, seat: str, prompt: str, model: str, task: str,
              item: str, timeout: int, bg: bool, expect: str = "",
              min_chars: int = 0):
    if bg:
        if expect or min_chars:
            sys.exit("error: --expect/--min-chars need the output in hand, and "
                     "--bg returns before there is any. Drive it in the "
                     "foreground, or review the session afterwards with "
                     "`review <run-id> --verdict`.")
        agent = seat
        if seat in orc.SEAT_DRIVERS and seat not in drv.load_agents(root):
            agent, alias = orc.SEAT_DRIVERS[seat]
            model = model or alias
        # --bg spawns straight through drivers.py, so it never passes the guard
        # inside drive_seat(). Backgrounding a call is not a way around a switch.
        orc.require_enabled(root, agent, task=task or "drive", item=item,
                            how="`agentos.py drive --bg`")
        try:
            row = drv.spawn(agent, prompt, model=model, root=root,
                            task=task or "drive", item=item)
        except (ValueError, FileNotFoundError) as e:
            sys.exit(f"error: {e}")
        orc._emit(root, {"kind": "session", "task": task or "drive",
                         "item": item, "model": agent, "tier": agent,
                         "outcome": "started", "sid": row["sid"],
                         "pid": row["pid"]})
        print(f"spawned {row['sid']} (pid {row['pid']}) — {agent}"
              f"{' ' + str(row['model']) if row['model'] else ''}")
        print(f"log: {row['log']}   check: agentos.py sessions {row['sid']} --tail")
        return
    r = orc.drive_seat(root, seat, prompt, model=model,
                       task=task or "drive", item=item, timeout=timeout,
                       validate=_output_validator(expect, min_chars))
    print(f"[{r['seat']} -> {r['agent']}"
          f"{' ' + str(r.get('model')) if r.get('model') else ''}] "
          f"{r['outcome']} in {r.get('latency_s', '?')}s  (run {r['run']})")
    if r.get("output"):
        print("\n" + r["output"])
    elif r.get("error"):
        print(f"error: {r['error']}", file=sys.stderr)
    if r["outcome"] == "thin":
        # The seat answered; the answer didn't hold up. Printed apart from the
        # driver's own failures because it is a different kind of bad.
        print(f"\nthin: {r.get('reason', 'failed validation')} — recorded as "
              f"`thin` on run {r['run']}, not `ok`.", file=sys.stderr)
    if r["outcome"] != "ok":
        sys.exit(1)


def cmd_sessions(root: Path, sid: str, tail: bool, kill: bool, n: int):
    if sid and kill:
        try:
            s = drv.session_kill(sid, root)
        except KeyError as e:
            sys.exit(f"error: {e.args[0]}")
        orc._emit(root, {"kind": "session", "task": s.get("task", ""),
                         "model": s.get("agent"), "tier": s.get("agent"),
                         "outcome": "killed", "sid": sid})
        print(f"killed {sid} (pid {s.get('pid')})")
        return
    if sid and tail:
        try:
            print(drv.session_tail(sid, root, n=n))
        except KeyError as e:
            sys.exit(f"error: {e.args[0]}")
        return
    rows = drv.sessions_list(root)
    if not rows:
        print("no background sessions yet — spawn one with `drive <seat> \"...\" --bg`")
        return
    print(f"{'sid':<11} {'agent':<8} {'status':<8} {'started':<20} task / prompt")
    print("-" * 78)
    for s in rows[-20:]:
        print(f"{s['sid']:<11} {s['agent']:<8} {s['status']:<8} {s['started']:<20} "
              f"{s.get('task', '')}: {s.get('prompt_head', '')[:40]}")


def cmd_loop(root: Path, task: str, prompt: str, every: int, times: int,
             until_ok: bool, model: str, drive_s: str):
    drive = None
    if drive_s:
        drive = True if drive_s == "true" else [s.strip() for s in drive_s.split(",")]
    print(f"LOOP — task '{task}' every {every}s, "
          + (f"{times}x" if times else "unbounded (Ctrl+C stops)")
          + (", until first ok" if until_ok else "") + "\n")
    i = 0
    try:
        while True:
            i += 1
            r = orc.run(task, prompt, root=root, item=f"loop#{i}",
                        model=model, drive=drive)
            head = (r.output or "").splitlines()[0][:80] if r.output else ""
            print(f"[{i}] {r.status}" + (f" via {r.model}" if r.model else "")
                  + (f" — {head}" if head else "")
                  + (f" — next: {r.next_model}" if r.next_model else ""))
            if until_ok and r.ok:
                print("\nfirst ok — loop done.")
                return
            if times and i >= times:
                print("\niteration bound reached.")
                return
            time.sleep(every)
    except KeyboardInterrupt:
        print(f"\nstopped by hand after {i} iteration(s).")


# --------------------------------------------------------------------- main

def main():
    # Windows consoles default to cp1252 — the 2026-07-10 shakedown mojibake.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None, help="repo root override (testing)")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("status")
    p = sub.add_parser("route"); p.add_argument("task", nargs="+")
    p = sub.add_parser("runs")
    p.add_argument("-n", type=int, default=20)
    p.add_argument("--summary", action="store_true")
    p.add_argument("--days", type=int, default=7)
    p = sub.add_parser("log-run")
    p.add_argument("task"); p.add_argument("--model", required=True)
    p.add_argument("--outcome", default="ok")
    p.add_argument("--item", default=""); p.add_argument("--note", default="")
    p.add_argument("--reviewed", action="store_true")
    p = sub.add_parser("review")
    p.add_argument("run_id"); p.add_argument("--note", default="")
    p.add_argument("--verdict", choices=list(orc.REVIEW_VERDICTS), default=None,
                   help="what you concluded (omit for 'looked, didn't say')")
    p = sub.add_parser("new"); p.add_argument("slug")
    sub.add_parser("dock")
    p = sub.add_parser("extract")
    p.add_argument("file"); p.add_argument("--password", default=""); p.add_argument("--out")
    p = sub.add_parser("digest")
    p.add_argument("item", nargs="?"); p.add_argument("--model")
    p = sub.add_parser("file")
    p.add_argument("item"); p.add_argument("--to", required=True, choices=["library", "raw"])
    p = sub.add_parser("redrop"); p.add_argument("item")
    p = sub.add_parser("reactivate")
    p.add_argument("slug"); p.add_argument("--trigger", required=True)
    p.add_argument("--note", default="")
    p = sub.add_parser("enrich")
    p.add_argument("slug"); p.add_argument("claims_file"); p.add_argument("--tags", default="")
    p = sub.add_parser("promote")
    p.add_argument("slug"); p.add_argument("--force", action="store_true")
    p = sub.add_parser("triage")   # deprecated v2 alias
    p.add_argument("item", nargs="?")

    sub.add_parser("agents")

    # tools — the Connections layer. A NESTED family: bare `tools`
    # lists, the verbs are sub-subcommands.
    ptool = sub.add_parser("tools", help="connections: on/off, auth, probes")
    stool = ptool.add_subparsers(dest="tools_cmd")
    q = stool.add_parser("enable"); q.add_argument("seat")
    q.add_argument("--note", default="")
    q = stool.add_parser("disable"); q.add_argument("seat")
    q.add_argument("--note", default="", help="why — it lands on the trail")
    q = stool.add_parser("probe"); q.add_argument("seat", nargs="?")
    q = stool.add_parser("set")
    q.add_argument("seat"); q.add_argument("assignment", metavar="key=value")

    p = sub.add_parser("drive")
    p.add_argument("seat"); p.add_argument("prompt", nargs="+")
    p.add_argument("--model"); p.add_argument("--task", default="")
    p.add_argument("--item", default=""); p.add_argument("--timeout", type=int)
    p.add_argument("--bg", action="store_true")
    p.add_argument("--expect", default="",
                   help="regex the output must match, else the run records `thin`")
    p.add_argument("--min-chars", type=int, default=0, dest="min_chars",
                   help="shorter output records `thin` rather than `ok`")
    p = sub.add_parser("sessions")
    p.add_argument("sid", nargs="?")
    p.add_argument("--tail", action="store_true"); p.add_argument("--kill", action="store_true")
    p.add_argument("-n", type=int, default=40)
    p = sub.add_parser("loop")
    p.add_argument("task"); p.add_argument("prompt", nargs="+")
    p.add_argument("--every", type=int, default=300)
    p.add_argument("--times", type=int, default=0)
    p.add_argument("--until-ok", action="store_true")
    p.add_argument("--model")
    p.add_argument("--drive", default="",
                   help="'true' for non-frontier drivable seats, or a comma list")
    args = ap.parse_args()
    root = Path(args.root).resolve() if args.root else DEFAULT_ROOT
    if not args.cmd:
        print(__doc__)
        return
    if args.cmd == "status":
        cmd_status(root)
    elif args.cmd == "route":
        cmd_route(root, " ".join(args.task))
    elif args.cmd == "runs":
        cmd_runs(root, args.n, args.summary, args.days)
    elif args.cmd == "log-run":
        cmd_log_run(root, args.task, args.model, args.outcome,
                    args.item, args.note, args.reviewed)
    elif args.cmd == "review":
        cmd_review(root, args.run_id, args.note, args.verdict)
    elif args.cmd == "new":
        cmd_new(root, args.slug)
    elif args.cmd == "dock":
        cmd_dock(root)
    elif args.cmd == "extract":
        cmd_extract(args.file, args.password, args.out)
    elif args.cmd == "digest":
        cmd_digest(root, args.item, args.model)
    elif args.cmd == "triage":
        print("`triage` is the old v2 name — running `digest` (v3).\n")
        cmd_digest(root, args.item, None)
    elif args.cmd == "file":
        cmd_file(root, args.item, args.to)
    elif args.cmd == "redrop":
        cmd_redrop(root, args.item)
    elif args.cmd == "reactivate":
        cmd_reactivate(root, args.slug, args.trigger, args.note)
    elif args.cmd == "enrich":
        cmd_enrich(root, args.slug, args.claims_file, args.tags)
    elif args.cmd == "promote":
        cmd_promote(root, args.slug, args.force)
    elif args.cmd == "agents":
        cmd_agents(root)
    elif args.cmd == "tools":
        tc = getattr(args, "tools_cmd", None)
        if tc in ("enable", "disable"):
            cmd_tools_toggle(root, args.seat, tc == "enable", args.note)
        elif tc == "probe":
            cmd_tools_probe(root, args.seat)
        elif tc == "set":
            cmd_tools_set(root, args.seat, args.assignment)
        else:
            cmd_tools(root)
    elif args.cmd == "drive":
        cmd_drive(root, args.seat, " ".join(args.prompt), args.model,
                  args.task, args.item, args.timeout, args.bg,
                  args.expect, args.min_chars)
    elif args.cmd == "sessions":
        cmd_sessions(root, args.sid, args.tail, args.kill, args.n)
    elif args.cmd == "loop":
        cmd_loop(root, args.task, " ".join(args.prompt), args.every,
                 args.times, args.until_ok, args.model, args.drive)


if __name__ == "__main__":
    try:
        main()
    except orc.PolicyRefusal as e:
        # The routing policy blocked this call (os/orchestration.md `never`).
        # It's a refusal, not a crash — print it as one. Exit 2 so a caller
        # can tell "policy said no" apart from "the seat failed" (exit 1).
        print(f"\n{e}\n", file=sys.stderr)
        sys.exit(2)
    except orc.NoEnabledSeat as e:
        # Every seat this task class could use is switched off (ticket 03).
        # Exit 3, distinct from 2, because the FIX is different: a refusal
        # means edit the policy in os/orchestration.md, this means run
        # `agentos.py tools enable <seat>`. Same reason 2 was split from 1.
        print(f"\n{e}\n", file=sys.stderr)
        sys.exit(3)
