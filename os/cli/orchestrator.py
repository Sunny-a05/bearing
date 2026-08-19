#!/usr/bin/env python3
"""orchestrator.py — the Orchestration layer (spec: os/orchestration.md). Stdlib only.

The control plane of the Bearing OS. Every model call in the OS goes through
here. It owns the three things that used to be scattered or missing:

  1. ROUTING (the router, folded in) — the executable mirror of the roster +
     task-class policy in os/orchestration.md. `resolve()` answers "which
     model, in what escalation order, and what never touches this."
  2. EXECUTION — actually running the ladder, via the DRIVER layer
     (drivers.py — seats and how to reach them). The local tier (Ollama) is
     always machine-drivable. Since 2026-07-10, agent seats with an installed
     CLI (claude -p, gemini -p, codex exec) are drivable TOO — but only when
     the caller opts in (`drive=`): auto-escalation never silently spends
     agent-seat budget, and frontier seats (opus/fable) must be named
     explicitly even then (the token-economy guard). Everything else still
     produces a structured HANDOFF. Retries, timeouts, thin-output
     escalation, and failure handling live here — nowhere else.
  3. RUN-RECORDS (the governance seed) — every attempt, handoff, agent run,
     and review is appended as one JSON line to os/runs.jsonl. Logs are
     emitted by the system itself, not written by hand. `log-run` is how
     agent seats report their own work into the same trail.

Hard rule inherited from the OS: local-model output DRAFTS, never DECIDES.
The orchestrator moves work between models; it never moves knowledge into
the wiki — that stays with Sonnet+ agents or you.
"""
import json
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drivers as drv                                        # noqa: E402

try:                                                         # noqa: E402
    import settings as st_conn
except ImportError:      # the Connections layer is optional — fail-open
    st_conn = None

DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent
RUNS_REL = Path("os") / "runs.jsonl"

# --------------------------------------------------------------- the roster
# Executable mirror of the roster table in os/orchestration.md. `executor`
# is the honest split: "ollama" = always machine-drivable; "agent" = a
# session seat — drivable via drivers.py when its CLI is installed AND the
# caller opts in, otherwise reached by handoff; "human" = you.
# Ollama tags live in drivers.py + os/agents.d/ollama.json (verified against
# `ollama list` 2026-07-10) — this module just re-exports them.

_ollama_spec = drv.load_agents(DEFAULT_ROOT)["ollama"]["models"]
OLLAMA_FIRST_PASS = _ollama_spec.get("first_pass", drv.OLLAMA_FIRST_PASS)
OLLAMA_ESCALATION = _ollama_spec.get("escalation", drv.OLLAMA_ESCALATION)
OLLAMA_TIMEOUT = drv.OLLAMA_TIMEOUT

MODELS = {
    OLLAMA_FIRST_PASS: {"tier": "ollama", "executor": "ollama", "cost": 0},
    OLLAMA_ESCALATION: {"tier": "ollama", "executor": "ollama", "cost": 0},
    "haiku":           {"tier": "haiku", "executor": "agent", "cost": 1},
    "sonnet":          {"tier": "sonnet", "executor": "agent", "cost": 2},
    "opus/fable":      {"tier": "opus/fable", "executor": "agent", "cost": 3},
    "gemini-flash":    {"tier": "gemini", "executor": "agent", "cost": 1},
    "gemini-pro":      {"tier": "gemini", "executor": "agent", "cost": 1},
    "codex/chatgpt":   {"tier": "codex", "executor": "agent", "cost": 2},
    "user":            {"tier": "human", "executor": "human", "cost": 9},
}

# The full ladder this roster CAN express. It is NOT what any given user sees:
# most people run one agent, not five, so a hardcoded five-vendor ladder is a lie
# to almost everyone reading it. `ladder_str()` renders only the rungs that are
# actually reachable on this machine, and always terminates in `user`.
FULL_LADDER = ["ollama", "haiku", "sonnet", "opus/fable", "user"]
LADDER = " -> ".join(FULL_LADDER)   # the canonical form, for docs and defaults


def ladder_str(root=None) -> str:
    """The escalation ladder as it actually stands on THIS machine.

    A rung shows only if its connection is installed and switched on. If nothing
    but the host agent is reachable, the honest ladder is `this agent -> user`:
    escalation still exists, it just has one rung and then you. The human rung is
    never filtered — it is not a connection, and it is always the last resort."""
    try:
        import drivers as drv
        import settings as st
        r = Path(root) if root else DEFAULT_ROOT
        available = {row["name"] for row in drv.probe(r) if row.get("available")}
        try:
            off = {row["name"] for row in st.status_rows(r) if not row.get("enabled", True)}
        except Exception:                                    # noqa: BLE001
            off = set()
        rungs = []
        for seat in FULL_LADDER:
            if seat in CONNECTIONLESS_SEATS:
                rungs.append(seat)
                continue
            conn = connection_seat(seat)
            if conn and conn in available and conn not in off:
                rungs.append(seat)
        if len(rungs) == 1:                    # only the human rung survived
            return "this agent -> user"
        return " -> ".join(rungs)
    except Exception:                                        # noqa: BLE001
        return LADDER
LOCAL_LADDER = [OLLAMA_FIRST_PASS, OLLAMA_ESCALATION]

# Which driver reaches which roster seat (drivers.py resolves the alias to
# the CLI's model arg). Frontier seats are never auto-driven — even with
# drive=True they must be named explicitly in the drive list.
SEAT_DRIVERS = {
    "haiku": ("claude", "haiku"),
    "sonnet": ("claude", "sonnet"),
    "opus/fable": ("claude", "opus/fable"),
    "gemini-flash": ("gemini", "gemini-flash"),
    "gemini-pro": ("gemini", "gemini-pro"),
    "codex/chatgpt": ("codex", None),
}
FRONTIER_SEATS = {"opus/fable"}

# ------------------------------------------------- the connections layer link
# Routing names ROSTER SEATS ("sonnet", "gemini-pro", "qwen3.5:0.8b");
# os/settings.json names CONNECTIONS ("claude", "gemini", "ollama") — the thing
# that is actually switched on or off, because one binary reaches several
# roster seats. Disabling `claude` therefore drops haiku, sonnet AND opus/fable
# together, which is the truth: there is one CLI behind all three, and pretending
# they can be toggled apart would be a switch that doesn't control anything.
# (map ticket 03)

CONNECTIONLESS_SEATS = {"user"}      # a human is not a connection


def connection_seat(name: str):
    """Roster seat / model tag -> the connections-layer seat that owns it.
    None means "not a connection" (the human seat), which is never filtered."""
    if name in CONNECTIONLESS_SEATS:
        return None
    if name in SEAT_DRIVERS:
        return SEAT_DRIVERS[name][0]
    if MODELS.get(name, {}).get("executor") == "ollama" or ":" in name:
        return "ollama"
    return name          # a seat named directly (hermes, openrouter, …)


def seat_enabled(name: str, root: Path = None) -> bool:
    """Is the connection behind this seat switched on? FAIL-OPEN, always: a
    missing settings.py, a missing/corrupt settings.json, or any error at all
    reads as enabled. The connections layer may stop a call deliberately; it
    may never stop one by breaking."""
    seat = connection_seat(name)
    if seat is None or st_conn is None:
        return True
    try:
        return st_conn.is_enabled(seat, Path(root) if root else DEFAULT_ROOT)
    except Exception:
        return True


# ------------------------------------------------------- the routing policy
# Executable mirror of the task-class table in os/orchestration.md.
# (task_class, keywords for free-text resolve, chain, never, why)
# First keyword match wins; `chain` is the escalation order for run().

POLICY = [
    ("privacy.local",
     ["private", "sensitive", "personal data", "stays local"],
     LOCAL_LADDER,
     ["haiku", "sonnet", "opus/fable", "gemini-pro", "gemini-flash", "codex/chatgpt"],
     "privacy-sensitive -> stays local; escalate to Claude only if you clear it"),
    ("arch.audit",
     ["architecture", "audit", "refactor", "design decision", "debug",
      "production", "load-bearing"],
     ["opus/fable"],
     [OLLAMA_FIRST_PASS, OLLAMA_ESCALATION],
     "load-bearing work -> frontier tier (Cowork); Codex as optional 2nd opinion"),
    ("wiki.ingest",
     ["ingest", "wiki", "cross-link", "file back"],
     ["sonnet", "opus/fable"],
     [OLLAMA_FIRST_PASS, OLLAMA_ESCALATION],
     "wiki maintenance -> Sonnet; local models never write to wiki/ unattended"),
    ("code.daily",
     ["code", "component", "fix", "test", "implement", "build"],
     ["sonnet", "opus/fable"],
     [],
     "day-to-day coding -> Sonnet (Claude Code)"),
    ("read.long",
     ["pdf", "long document", "whole repo", "100 page", "100+ page"],
     ["gemini-pro", "sonnet"],
     ["haiku"],
     "long-context reading -> Gemini Pro; Claude chunked as fallback"),
    ("multimodal",
     ["video", "image", "multimodal", "scanned", "ocr", "vision"],
     ["gemini-pro", "sonnet"],
     [OLLAMA_FIRST_PASS, OLLAMA_ESCALATION],
     "multimodal -> Gemini; Claude vision as fallback (no local vision model)"),
    ("dock.digest",
     ["triage", "digest", "graphify"],
     LOCAL_LADDER + ["haiku"],
     ["opus/fable"],
     "dock first pass -> local tier (free), Haiku only when both local passes fail"),
    ("bulk.summarize",
     ["summarize", "summary", "tag", "extract", "keywords", "bulk", "draft"],
     LOCAL_LADDER + ["haiku"],
     ["opus/fable"],
     "bulk/low-stakes -> local first (free); escalate to Haiku if quality fails"),
    ("ops.format",
     ["log entry", "formatting", "frontmatter", "rename", "reformat"],
     LOCAL_LADDER + ["haiku", "sonnet"],
     ["opus/fable"],
     "mechanical file hygiene -> cheapest tier that gets it right"),
    ("research.web",
     ["research", "web search", "sweep"],
     ["gemini-flash", "sonnet"],
     [],
     "web research sweeps -> Gemini / Claude research"),
    ("crosscheck",
     ["second opinion", "cross-check", "sanity check"],
     ["codex/chatgpt", "gemini-flash"],
     [],
     "cross-check -> least-used seat, keeps its context disposable"),
    # NOTE: keyword lists avoid substrings already claimed by earlier classes
    # (first keyword match wins) — "triage"/"digest" belong to dock.digest,
    # "draft"/"summarize" to bulk.summarize. The secretary code routes by exact
    # class name, so these free-text keywords are convenience only.
    ("secretary.triage",
     ["classify mail", "classify inbox", "secretary sort"],
     LOCAL_LADDER + ["haiku"],
     ["opus/fable"],
     "recurring inbox triage -> local tier (free); urgency/domain classify never "
     "burns frontier. Frontier only to DRAFT (secretary.draft), never to triage."),
    ("secretary.draft",
     ["compose reply", "compose email", "secretary reply"],
     ["sonnet", "opus/fable"],
     [OLLAMA_FIRST_PASS, OLLAMA_ESCALATION],
     "load-bearing drafting -> Sonnet; the one place the secretary spends frontier. "
     "privacy.local threads never reach here (pre-router keeps them local)."),
    ("secretary.distill",
     ["secretary distill", "preference note", "distill outcomes"],
     ["sonnet", "opus/fable"],
     [OLLAMA_FIRST_PASS, OLLAMA_ESCALATION],
     "periodic learning distillation -> Sonnet+ writes a preference note into the "
     "dock (never straight to wiki/). Batched after N outcomes, so cost is rare."),
]

DEFAULT_ROUTE = ("default", [], ["sonnet", "opus/fable"], [],
                 "no policy match -> Sonnet (default workhorse); check "
                 "os/orchestration.md if this looks wrong")


class PolicyRefusal(Exception):
    """Raised when a call would reach a seat the task class forbids.

    The `never` column in os/orchestration.md was decoration until 2026-07-22
    (map ticket 16): it was parsed, stored, printed by describe(), and read
    nowhere in run(). Worse, `chain = [model] if model else route.chain` let
    an explicit override discard policy wholesale, so a privacy.local task
    could be sent to Sonnet with a --model flag and no complaint. This is the
    enforcement. It raises rather than degrading, for the same reason ticket
    03's degradation rule errors instead of substituting: a blocked call that
    silently falls back is a correct outcome reached by an unauditable path.
    """

    def __init__(self, route, seat, via, run_id=None):
        self.task_class, self.seat, self.via, self.run = \
            route.task_class, seat, via, run_id
        self.never = list(route.never)
        super().__init__(
            f"REFUSED: task class '{route.task_class}' may never run on "
            f"'{seat}' (reached via {via}).\n"
            f"  never:  {', '.join(route.never)}\n"
            f"  why:    {route.why}\n"
            f"  policy: os/orchestration.md — routing policy table"
            + (f"\n  run:    {run_id}" if run_id else ""))


class NoEnabledSeat(Exception):
    """The seat(s) a call needs are switched off in os/settings.json (ticket 03).

    Raised by run() instead of falling through to DEFAULT_ROUTE. The
    degradation rule is the load-bearing decision of the connections layer:
    silent substitution is how a task specced for a cheap tier ends up on an
    expensive one. The default chain is `sonnet -> opus/fable`, so a disabled
    local tier that fell through would quietly promote every dock digest to an
    agent seat, and the first anyone would hear of it is the bill. An off
    switch that reroutes instead of stopping is not an off switch.

    Raised by drive_seat() / council for the plainer reason:
    off means off, including for an explicitly named seat.
    """

    def __init__(self, task_class, chain, why, headline, tail=()):
        self.task_class, self.chain = task_class, list(chain)
        self.seats = [connection_seat(n) for n in self.chain]
        named = sorted({s for s in self.seats if s})
        pairs = ", ".join(f"{n} (connection '{connection_seat(n)}')"
                          for n in self.chain)
        lines = [headline,
                 f"  {'seats' if len(self.chain) > 1 else 'seat'}:  {pairs}",
                 f"  why:    {why}",
                 f"  fix:    `agentos.py tools enable "
                 f"{named[0] if named else '<seat>'}`  (see `agentos.py tools`)"]
        lines.extend(tail)
        super().__init__("\n".join(lines))

    @classmethod
    def from_route(cls, route, chain, overridden=False):
        """run(): a whole chain is dark."""
        via = ("the --model override" if overridden
               else "the task class's own chain")
        return cls(
            route.task_class, chain, route.why,
            f"NO ENABLED SEAT: every seat {via} offers for task class "
            f"'{route.task_class}' is switched off.",
            tail=[f"  note:   refusing rather than falling back to the default "
                  f"chain ({' -> '.join(DEFAULT_ROUTE[2])}) — a disabled seat "
                  f"must not silently become a more expensive one"])

    @classmethod
    def for_seats(cls, seats, task="drive", how="`agentos.py drive`"):
        """drive_seat() / council: named seats, switched off.

        Takes a LIST because a council must name every dark member at once —
        refusing one at a time would spend the live members' budget first and
        then throw the results away, which is the same up-front-check argument
        enforce_never() makes.
        """
        seats = list(seats)
        s = "s" if len(seats) > 1 else ""
        return cls(
            task, seats, f"an explicit {how} naming a seat that is switched off",
            f"NO ENABLED SEAT: {', '.join(repr(x) for x in seats)} "
            f"{'are' if s else 'is'} switched off, so {how} will not run "
            f"{'them' if s else 'it'}.",
            tail=["  note:   the switch governs explicit calls too "
                  "Turn the seat back on, or pick "
                  "another — `agentos.py tools` shows what is live."])


class Route:
    def __init__(self, task_class, chain, never, why, root=None):
        self.task_class, self.never, self.why = task_class, never, why
        self.root = Path(root) if root else DEFAULT_ROOT
        # `full_chain` is the policy as written; `chain` is what is actually
        # reachable right now. run() walks full_chain so a skip can be RECORDED
        # (a skip is an event, not a silence); everything that only wants to
        # know what will happen reads `chain`.
        self.full_chain = list(chain)
        self.chain, self.dropped = [], []
        for name in self.full_chain:
            if seat_enabled(name, self.root):
                self.chain.append(name)
            else:
                self.dropped.append((name, connection_seat(name)))

    def describe(self):
        chain_s = " -> ".join(self.chain) if self.chain else \
            "(none — every seat in this chain is switched off)"
        if self.dropped and self.chain:
            chain_s += f"   [{len(self.chain)} of {len(self.full_chain)} seats live]"
        lines = [f"task class: {self.task_class}",
                 f"chain:      {chain_s}",
                 f"why:        {self.why}"]
        for name, seat in self.dropped:
            lines.append(f"dropped:    {name} — connection '{seat}' is disabled "
                         f"in os/settings.json (`tools enable {seat}`)")
        if self.dropped and not self.chain:
            lines.append("            run() will ERROR here rather than fall "
                         "back to the default chain — see os/orchestration.md "
                         "§Connections layer")
        if self.never:
            lines.append(f"never:      {', '.join(self.never)}  (enforced — "
                         "run() refuses these, including a --model override)")
        lines.append(f"ladder:     {ladder_str()}")
        if not self.chain:
            return "\n".join(lines)
        first = MODELS.get(self.chain[0], {})
        if first.get("executor") != "ollama":
            name = self.chain[0]
            if name in SEAT_DRIVERS:
                agent, _ = SEAT_DRIVERS[name]
                installed = drv.which(drv.load_agents(DEFAULT_ROOT).get(agent, {"name": agent}))
                if installed:
                    guard = (" (frontier — must be named explicitly)"
                             if name in FRONTIER_SEATS else "")
                    lines.append(f"executor:   agent seat — drivable via `{agent}` CLI "
                                 f"with drive opt-in{guard}; otherwise handoff + log-run")
                else:
                    lines.append(f"executor:   agent seat — driver '{agent}' not "
                                 "installed; handoff + `agentos.py log-run`")
            else:
                lines.append("executor:   agent seat — orchestrator records a handoff; "
                             "the agent reports back with `agentos.py log-run`")
        return "\n".join(lines)


def resolve(task, root: Path = None) -> Route:
    """Routing function (the folded-in router). `task` is a task-class name
    or free text; first keyword match wins, mirroring os/orchestration.md.

    `root` locates os/settings.json: the returned Route has already had
    switched-off seats filtered out of `.chain` (with `.dropped` saying which
    and why). Defaulting it keeps every existing caller working — and keeps a
    caller that forgets it reading the REAL settings rather than none.
    """
    t = task.strip().lower()
    for cls, keywords, chain, never, why in POLICY:
        if t == cls:
            return Route(cls, list(chain), list(never), why, root)
    for cls, keywords, chain, never, why in POLICY:
        if any(k in t for k in keywords):
            return Route(cls, list(chain), list(never), why, root)
    cls, _, chain, never, why = DEFAULT_ROUTE
    return Route(cls, list(chain), list(never), why, root)


# ------------------------------------------------------------- run records

# The judgement vocabulary for `review` records. Deliberately three words, not
# a score: `good` = usable as-is, `thin` = came back but under-delivered,
# `wrong` = confidently incorrect. `thin` shares its name with the outcome a
# failing validator writes, because they mean the same thing reached two ways —
# machine-checked vs. reviewer-judged.
REVIEW_VERDICTS = ("good", "thin", "wrong")


def runs_path(root: Path) -> Path:
    return Path(root) / RUNS_REL


_EMIT_LOCK = threading.Lock()   # council runs members in parallel threads


def _emit(root: Path, record: dict) -> dict:
    record.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
    record.setdefault("run", "r-" + uuid.uuid4().hex[:8])
    p = runs_path(root)
    with _EMIT_LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def iter_runs(root: Path):
    p = runs_path(root)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def log_agent_run(root: Path, task: str, model: str, outcome: str,
                  item: str = "", note: str = "", reviewed: bool = False) -> dict:
    """Governance entry point for agent seats: a Sonnet/Opus/Gemini session
    that did work reports it here so the run trail stays complete."""
    return _emit(root, {
        "kind": "agent-run", "task": task, "item": item, "model": model,
        "tier": MODELS.get(model, {}).get("tier", model),
        "outcome": outcome, "reviewed": bool(reviewed), "note": note,
    })


def mark_reviewed(root: Path, run_id: str, note: str = "",
                  verdict: str = None) -> dict:
    """Append-only review marker (event-sourced — earlier lines are immutable).

    `reviewed: true` records only that someone LOOKED. `verdict` — good | thin
    | wrong — records what they CONCLUDED, which is the thing the trail never
    held (map ticket 17). Optional on purpose: absent means "looked, didn't
    say", so every review line written before this existed still parses and
    nothing is rewritten.
    """
    if verdict is not None and verdict not in REVIEW_VERDICTS:
        raise ValueError(
            f"verdict must be one of {' | '.join(REVIEW_VERDICTS)} "
            f"(got '{verdict}') — or omitted for 'looked, didn't say'")
    if not any(r.get("run") == run_id for r in iter_runs(root)):
        raise KeyError(f"no run record with id {run_id}")
    rec = {"kind": "review", "of": run_id, "note": note, "reviewed": True}
    if verdict:
        rec["verdict"] = verdict
    return _emit(root, rec)


def _reviewed_ids(records) -> set:
    return ({r.get("of") for r in records if r.get("kind") == "review"}
            | {r.get("run") for r in records if r.get("reviewed") is True})


def _verdicts_by_run(records) -> dict:
    """run-id -> verdict, for reviews that carry one.

    Later reviews of the same run supersede earlier ones. That is a READ rule,
    not a write one: nothing is rewritten, the newest line simply wins — the
    same event-sourcing the rest of the trail follows.
    """
    out = {}
    for r in records:
        if r.get("kind") == "review" and r.get("of") and r.get("verdict"):
            out[r["of"]] = r["verdict"]
    return out


def summarize(root: Path, days: int = 7) -> str:
    """Report the trail. COMPLETION and JUDGEMENT are printed as separate
    figures, deliberately (map ticket 17): `outcome: ok` originates in
    drv.submit() and means the process exited with non-empty output. Printing
    that as `11/15 ok` read like a quality score for months and was never one.
    Quality is the verdict column, and it is empty until someone judges."""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    all_records = list(iter_runs(root))
    records = [r for r in all_records if r.get("ts", "") >= cutoff]
    if not records:
        return f"no run records in the last {days} day(s) — os/runs.jsonl is the trail"
    reviewed = _reviewed_ids(all_records)
    # Verdicts are read from the WHOLE trail, not the window: a review lands
    # after the call it judges, often days later, and a judgement that falls
    # off the edge of --days would otherwise silently read as unjudged.
    verdicts = _verdicts_by_run(all_records)
    by_model, handoffs, unreviewed = {}, {}, 0
    refusals, config, skips = {}, [], {}
    calls_total = judged_total = 0
    for r in records:
        kind = r.get("kind")
        if kind in ("review", "council", "session"):
            continue
        if kind == "settings":
            # A config change is not a model call and carries no `model`, so
            # leaving it to fall through would open a phantom "?" row in
            # by_model and inflate the call count — the same mistake the
            # refusal branch below exists to avoid.
            config.append(r)
            continue
        if kind == "handoff":
            handoffs[r.get("to", "?")] = handoffs.get(r.get("to", "?"), 0) + 1
            continue
        if kind == "skip":
            # A skipped rung never ran, so it is not a call. Same trap as
            # `settings` and `refusal`: let it fall through and a switched-off
            # seat reads in by_model as a seat that answered 0/N — inventing a
            # failure where the OS in fact did exactly what it was told.
            key = (r.get("task", "?"), r.get("model", "?"), r.get("seat", "?"))
            skips[key] = skips.get(key, 0) + 1
            continue
        if kind == "refusal":
            # A blocked call is a governance event, not a model call — it must
            # never land in by_model, or a guard that fired would read as a
            # seat that ran.
            key = (r.get("task", "?"), r.get("model", "?"))
            refusals[key] = refusals.get(key, 0) + 1
            continue
        m = r.get("model", "?")
        d = by_model.setdefault(m, {"calls": 0, "completed": 0, "thin": 0,
                                    "chars_out": 0,
                                    "good": 0, "judged_thin": 0, "wrong": 0})
        d["calls"] += 1
        calls_total += 1
        outcome = r.get("outcome")
        d["completed"] += 1 if outcome == "ok" else 0
        d["thin"] += 1 if outcome == "thin" else 0
        d["chars_out"] += int(r.get("chars_out", 0) or 0)
        v = verdicts.get(r.get("run"))
        if v:
            d["judged_thin" if v == "thin" else v] += 1
            judged_total += 1
        if kind in ("model-call", "agent-run") and r.get("run") not in reviewed \
                and (MODELS.get(m, {}).get("executor") == "ollama"
                     or r.get("tier") == "ollama"):
            unreviewed += 1
    lines = [f"RUN SUMMARY — last {days} day(s), {len(records)} record(s)",
             "  completed = the call returned output (liveness) · judged = a "
             "reviewer said whether it was any good (quality). Not the same number."]
    # Driver-qualified names ("ollama:qwen3.5:0.8b", "hermes:openai/gpt-oss-20b:free")
    # run well past any fixed width, and a summary whose columns don't line up is
    # a summary nobody reads across.
    w = max([14] + [len(m) for m in by_model])   # list form: by_model may be empty
    for m, d in sorted(by_model.items(), key=lambda kv: -kv[1]["calls"]):
        done = f"{d['completed']}/{d['calls']} completed"
        if d["thin"]:
            done += f", {d['thin']} thin"
        j = d["good"] + d["judged_thin"] + d["wrong"]
        judged = (f"judged {j}: {d['good']} good/{d['judged_thin']} thin/"
                  f"{d['wrong']} wrong" if j else "judged 0 — no verdict")
        toks = f"~{d['chars_out'] // 4:,} tokens out" if d["chars_out"] else "no output logged"
        lines.append(f"  {m:<{w}} {d['calls']:>3} call(s)  {done:<24} "
                     f"{judged:<34} {toks}")
    if calls_total:
        pct = round(100 * judged_total / calls_total)
        lines.append(f"  judgement coverage: {judged_total}/{calls_total} call(s) "
                     f"carry a verdict ({pct}%) — "
                     + ("the rest completed but nobody said whether they were good"
                        if judged_total < calls_total else "fully judged"))
    for to, n in sorted(handoffs.items()):
        lines.append(f"  handoff -> {to:<11} {n:>3} pending/executed by agent seats")
    if refusals:
        total = sum(refusals.values())
        lines.append(f"  guard blocked {total} call(s) — policy `never` "
                     "(os/orchestration.md):")
        for (task_cls, seat), n in sorted(refusals.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {task_cls:<20} -> {seat:<14} {n:>3} refused")
    if skips:
        total = sum(skips.values())
        lines.append(f"  skipped {total} rung(s) — connection switched off "
                     "(os/settings.json):")
        for (task_cls, name, seat), n in sorted(skips.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {task_cls:<20} -> {name:<14} {n:>3} skipped  "
                         f"(`tools enable {seat}`)")
    if config:
        lines.append(f"  config: {len(config)} connection change(s) "
                     "(`tools enable|disable|set`):")
        for r in config[-5:]:
            lines.append(f"    {r.get('ts', '?')[:16]}  {r.get('seat', '?'):<12} "
                         f"{r.get('event', '?'):<8} {r.get('field', '?')}: "
                         f"{r.get('was')!r} -> {r.get('now')!r}"
                         + (f"  ({r['note']})" if r.get("note") else ""))
    if unreviewed:
        lines.append(f"  !! {unreviewed} local-model output(s) not yet reviewed "
                     "(OS hard rule 4 — drafts need Sonnet+/human eyes)")
    return "\n".join(lines)


# --------------------------------------------------------------- execution

def run_ollama(model: str, prompt: str, timeout: int = OLLAMA_TIMEOUT):
    """Local-tier call via the driver layer (backcompat shim — dockyard.py
    and older callers use this signature). UTF-8-safe, noise-stripped."""
    r = drv.submit("ollama", prompt, model=model, timeout=timeout)
    return r.get("output"), r["outcome"], r.get("latency_s", 0.0)


def drive_seat(root: Path, seat: str, prompt: str, model: str = None,
               task: str = "", item: str = "", timeout: int = None,
               validate=None) -> dict:
    """Explicitly drive ONE seat and record the call. `seat` is a driver name
    (claude / gemini / ollama / codex / anything in os/agents.d) or a roster
    seat (haiku / sonnet / opus/fable / gemini-pro / ...). Emits one model-call
    record; returns the driver result + run id.

    Explicit calls are consent as far as SPEND goes — the frontier guard still
    only applies to automatic escalation in run(). They are NOT an exception to
    the connections layer: a switched-off seat refuses here too (
    2026-08-06). Raises NoEnabledSeat before reaching the driver.

    validate(output) -> (ok, payload, reason), mirroring run(). Without it the
    recorded outcome is whatever drv.submit() reported, and `ok` there means
    only "the process exited with non-empty output" — LIVENESS, not quality.
    With it, output that fails the check records `thin` instead. This is what
    lets a quality signal exist outside the dock (map ticket 17): before it,
    dockyard.py was the only caller anywhere that passed a validator, so every
    `drive`, every council member, and every session recorded `ok` regardless
    of what came back.
    """
    root = Path(root) if root else DEFAULT_ROOT
    if seat in SEAT_DRIVERS and seat not in drv.load_agents(root):
        agent, alias = SEAT_DRIVERS[seat]
        model = model or alias
    else:
        agent = seat
    # The driver name is what actually gets reached, so it — not the roster
    # alias the caller typed — is the connection to check.
    require_enabled(root, agent, task=task or "drive", item=item)
    r = drv.submit(agent, prompt, model=model, root=root, timeout=timeout)
    tier = drv.load_agents(root).get(agent, {}).get("tier", agent)
    out, reason = r.get("output"), ""
    if out is not None and validate is not None:
        good, payload, why = validate(out)
        r["payload"] = payload
        if not good:
            reason = why or "failed validation"
            r["outcome"] = "thin"
            r["reason"] = reason
    rec = {
        "kind": "model-call", "task": task or "drive", "item": item,
        "model": f"{agent}:{r.get('model')}" if r.get("model") else agent,
        "tier": tier, "outcome": r["outcome"],
        "latency_s": r.get("latency_s", 0.0), "chars_in": len(prompt),
        "chars_out": len(out or ""), "reviewed": False,
        "driver": agent,
    }
    if reason:
        rec["note"] = reason
    rec = _emit(root, rec)
    r["run"] = rec["run"]
    r["seat"] = seat
    return r


class RunResult:
    """Outcome of orchestrating one task. status: ok | handoff | exhausted."""

    def __init__(self, status, model=None, output=None, payload=None,
                 next_model=None, attempts=None, notes=None):
        self.status, self.model, self.output, self.payload = status, model, output, payload
        self.next_model = next_model
        self.attempts = attempts or []   # [{model, outcome, latency_s, payload}]
        self.notes = notes or []

    @property
    def ok(self):
        return self.status == "ok"


def enforce_never(root: Path, route: Route, chain, item: str = "",
                  overridden: bool = False):
    """Refuse, before executing anything, if the chain reaches a forbidden seat.

    Checked UP FRONT rather than per-rung: doing half a chain and then
    refusing spends real tokens on a call the policy already forbade, and
    leaves a partial result nobody should use.

    Two distinct failures, deliberately worded differently:
      - via `--model`  -> the caller tried to route around the policy.
      - via the chain  -> the POLICY ROW CONTRADICTS ITSELF. That's a config
        bug in orchestration.md, and it should be loud rather than quietly
        tolerated the way it has been until now.
    """
    for name in chain:
        if name in route.never:
            via = "--model override" if overridden else "the task class's own chain"
            rec = _emit(root, {
                "kind": "refusal", "task": route.task_class, "item": item,
                "model": name, "tier": MODELS.get(name, {}).get("tier", name),
                "outcome": "refused", "rule": "never",
                "via": "model-override" if overridden else "policy-chain",
                "never": list(route.never),
                "note": f"policy forbids {name} for {route.task_class}",
            })
            if not overridden:
                raise PolicyRefusal(
                    route, name, "the task class's own chain — THIS IS A POLICY "
                    "BUG: the row lists a seat in both its chain and its never "
                    "list. Fix os/orchestration.md and orchestrator.POLICY",
                    rec["run"])
            raise PolicyRefusal(route, name, via, rec["run"])


def _emit_skip(root: Path, task_class: str, name: str, item: str = "",
               via: str = "policy-chain") -> dict:
    """Record that a call was skipped because its connection is off.

    A skip is an EVENT, not a silence (ticket 03). Without this record, "why
    did the digest go straight to haiku" is answerable only by reading
    settings.json and inferring — and the OS's characteristic failure is
    exactly that kind of quiet. `via` says how the seat was reached, so a
    blocked explicit drive reads differently from a stepped-over chain rung.
    """
    seat = connection_seat(name)
    return _emit(root, {
        "kind": "skip", "task": task_class, "item": item,
        "model": name, "tier": MODELS.get(name, {}).get("tier", name),
        "outcome": "skipped", "reason": "disabled", "seat": seat, "via": via,
        "note": f"connection '{seat}' is switched off in os/settings.json "
                f"(`agentos.py tools enable {seat}`)",
    })


def require_enabled(root: Path, seats, task: str = "drive", item: str = "",
                    how: str = "`agentos.py drive`"):
    """Refuse an EXPLICIT call to switched-off seat(s). One guard, three call
    sites: drive_seat(), `drive --bg`, and council.convene().

    Ticket 03 originally exempted explicit invocation on ticket 16's
    consent argument — an `agentos.py drive <seat>` is a deliberate, named act,
    so the switch was scoped to automatic routing. **That was overruled on
    2026-08-06: off means off.** The consent argument was answering the wrong
    question — consent to *use a seat* is not consent to *use a seat you had
    already turned off*, and a switch with an exception nobody can see is the
    decoration this map exists to remove.

    Checked for ALL named seats before any of them runs, so a council with one
    dark member fails before spending the live ones' budget rather than after.
    """
    seats = [seats] if isinstance(seats, str) else list(seats)
    dark = [s for s in seats if not seat_enabled(s, root)]
    if not dark:
        return
    for s in dark:
        _emit_skip(root, task, s, item, via="explicit")
    raise NoEnabledSeat.for_seats(dark, task=task, how=how)


def audit_policy():
    """Self-check: no POLICY row may list a seat in both chain and never.

    Enforcement turns a latent contradiction into a hard failure at call
    time, so it's worth being able to find one without waiting to be bitten.
    Returns a list of (task_class, seat) conflicts — empty means clean.
    """
    return [(cls, name) for cls, _, chain, never, _ in POLICY
            for name in chain if name in never]


def _drive_allowance(drive) -> set:
    """Normalize the drive opt-in. False/None -> nothing auto-driven (every
    agent seat is a handoff, the pre-2026-07-10 behavior). True -> drivable
    non-frontier seats. A list -> exactly those seats; naming a frontier seat
    (opus/fable) explicitly is the ONLY way it gets auto-driven — that's the
    token-economy guard."""
    if not drive:
        return set()
    if drive is True:
        return set(SEAT_DRIVERS) - FRONTIER_SEATS
    return set(drive)


def run(task, prompt, root: Path = None, item: str = "", validate=None,
        model: str = None, timeout: int = OLLAMA_TIMEOUT, drive=None) -> RunResult:
    """Orchestrate one task: resolve the route, walk the chain, execute every
    seat it can (local tier always; agent seats only within the `drive`
    opt-in), validate, escalate on thin/failed output, record every attempt,
    and hand off cleanly at the first seat it may not (or cannot) drive.

    validate(output) -> (ok, payload, reason). payload is kept per attempt so
    the caller can use the best partial even when everything came back thin.
    drive: None/False (default) | True (non-frontier drivable seats) | list
    of seat names (explicitly naming "opus/fable" is the only way frontier
    gets auto-driven).

    Raises PolicyRefusal if the resolved chain — or a `model=` override —
    reaches a seat the task class forbids (os/orchestration.md `never`).
    Raises NoEnabledSeat if every seat it could use is switched off.
    """
    root = Path(root) if root else DEFAULT_ROOT
    route = resolve(task, root=root)
    overridden = bool(model)
    # full_chain, not chain: run() walks the policy AS WRITTEN so that skipping
    # a disabled rung leaves a record. Filtering here instead would make the
    # skip invisible, which is the failure this ticket exists to prevent.
    chain = [model] if overridden else route.full_chain
    # The never list is policy, and an override is a shortcut around the
    # chain — never around the policy. Checked before a single token is spent.
    enforce_never(root, route, chain, item=item, overridden=overridden)
    live = {name for name in chain if seat_enabled(name, root)}
    if chain and not live:
        # THE DEGRADATION RULE. Record every skip, then stop. Do not fall
        # through to DEFAULT_ROUTE — see NoEnabledSeat.
        for name in chain:
            _emit_skip(root, route.task_class, name, item,
                       via="model-override" if overridden else "policy-chain")
        raise NoEnabledSeat.from_route(route, chain, overridden)
    allowance = _drive_allowance(drive)
    result = RunResult("exhausted", attempts=[])
    for name in chain:
        if name not in live:
            rec = _emit_skip(root, route.task_class, name, item)
            result.notes.append(
                f"{name}: skipped — connection "
                f"'{connection_seat(name)}' is switched off ({rec['run']})")
            continue
        # unknown names with a ":" are Ollama tags (e.g. a --model override)
        info = MODELS.get(name) or {"executor": "ollama" if ":" in name else "agent",
                                    "tier": name}
        if info["executor"] == "ollama":
            out, outcome, lat = run_ollama(name, prompt, timeout=timeout)
            rec = {"kind": "model-call", "task": route.task_class, "item": item,
                   "model": name, "tier": "ollama", "outcome": outcome,
                   "latency_s": round(lat, 1), "chars_in": len(prompt),
                   "chars_out": len(out) if out else 0, "reviewed": False}
        elif name in allowance and name in SEAT_DRIVERS:
            agent, alias = SEAT_DRIVERS[name]
            r = drv.submit(agent, prompt, model=alias, root=root,
                           timeout=timeout if timeout != OLLAMA_TIMEOUT else None)
            out, outcome, lat = r.get("output"), r["outcome"], r.get("latency_s", 0.0)
            rec = {"kind": "model-call", "task": route.task_class, "item": item,
                   "model": name, "tier": info.get("tier", name),
                   "outcome": outcome, "latency_s": round(lat, 1),
                   "chars_in": len(prompt), "chars_out": len(out) if out else 0,
                   "reviewed": False, "driver": agent}
            if outcome == "unavailable":
                result.notes.append(f"{name}: driver '{agent}' not installed")
        else:
            _emit(root, {"kind": "handoff", "task": route.task_class, "item": item,
                         "to": name, "tier": info.get("tier", name),
                         "note": "; ".join(result.notes[-2:]) or "routed per policy"})
            result.status, result.next_model = "handoff", name
            why = ("frontier seat — name it in `drive` explicitly to auto-run"
                   if name in FRONTIER_SEATS and drive else
                   "agent seat outside the drive opt-in")
            result.notes.append(
                f"handoff -> {name} ({why}): run it in-session, then report "
                f"with `agentos.py log-run \"{route.task_class}\" --model {name} "
                f"--outcome ok`")
            return result
        attempt = {"model": name, "outcome": outcome, "latency_s": round(lat, 1),
                   "payload": None}
        if out is not None and validate is not None:
            ok, payload, reason = validate(out)
            attempt["payload"] = payload
            if not ok:
                outcome = rec["outcome"] = attempt["outcome"] = "thin"
                rec["note"] = reason
                result.notes.append(f"{name}: {reason}, escalating")
        elif out is None:
            result.notes.append(f"{name}: {rec.get('driver', 'ollama')} {outcome}")
        _emit(root, rec)
        result.attempts.append(attempt)
        if out is not None and outcome == "ok":
            result.status, result.model, result.output = "ok", name, out
            result.payload = attempt["payload"]
            return result
    result.notes.append("chain exhausted with no usable output — escalate by hand "
                        f"per os/orchestration.md (ladder: {ladder_str(root)})")
    return result
