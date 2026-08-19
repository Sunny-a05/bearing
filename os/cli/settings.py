#!/usr/bin/env python3
"""settings.py — the Connections layer: which seats are ON, and what we know
about them. Stdlib only.

Sits BESIDE drivers.py and BELOW the orchestrator. `drivers.py` answers "how
do I reach this seat" (binary, argv, model map) from hand-authored specs in
os/agents.d/. This module answers "is it switched on, is it authenticated,
when did we last check" from os/settings.json, which is written mechanically
by the CLI and UI.

THE SPLIT IS THE POINT (ticket 01):

    os/agents.d/<seat>.json    how to reach a seat   hand-authored, rare edits
    os/settings.json           whether it's on       machine-written, constant

Putting `enabled: false` in a seat spec would park mutable state inside a
hand-authored file and guarantee drift — the same reasoning that keeps the
registry (status) separate from the wiki (memory).

FAIL-OPEN IS A HARD RULE. A missing settings.json, an unreadable one, or a
seat with no entry all mean `enabled: true, auth: unknown`. Deleting
os/settings.json must leave the OS behaving exactly as it does today. A
connections layer that can brick the OS by losing one file is worse than no
connections layer at all.

SECRETS NEVER LIVE HERE. A provider entry stores the *name* of an env var
(`"api_key_env": "OPENROUTER_API_KEY"`), never a key. If a key ever appears
in this file, that is a leak, not a config.
"""
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS_REL = Path("os") / "settings.json"

SCHEMA_VERSION = 1

# Wider than today's needs on purpose: an MCP server or a browser-only service
# can register later without a schema break.
KINDS = ("agent-seat", "provider", "mcp", "service")
AUTH_STATES = ("ok", "needs-auth", "missing-binary", "missing-key", "unknown")

# The state every unknown seat inherits. Fail-open: present but unverified.
DEFAULT_ENTRY = {"kind": "agent-seat", "enabled": True, "auth": "unknown"}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def settings_path(root: Path = None) -> Path:
    return Path(root or DEFAULT_ROOT) / SETTINGS_REL


# ------------------------------------------------------------------ store io

def load(root: Path = None) -> dict:
    """Read the store. Never raises: a missing or corrupt file yields an empty
    v1 store, which fail-open turns into 'every seat enabled'."""
    p = settings_path(root)
    if not p.exists():
        return {"version": SCHEMA_VERSION, "connections": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": SCHEMA_VERSION, "connections": {}}
    if not isinstance(data, dict):
        return {"version": SCHEMA_VERSION, "connections": {}}
    data.setdefault("version", SCHEMA_VERSION)
    conns = data.get("connections")
    data["connections"] = conns if isinstance(conns, dict) else {}
    return data


def save(data: dict, root: Path = None) -> Path:
    """Atomic write — temp file in the same directory, then os.replace.
    A half-written settings.json must never exist, because the OS reads this
    file on every routing decision once ticket 03 lands."""
    p = settings_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    data.setdefault("version", SCHEMA_VERSION)
    data.setdefault("connections", {})
    payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)      # atomic on Windows and POSIX alike
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return p


# --------------------------------------------------------------- connections

def _known_seats(root: Path = None) -> dict:
    """Seat specs from the driver layer. Imported lazily so settings.py stays
    usable (and testable) even if drivers.py is mid-edit."""
    try:
        import drivers as drv
    except ImportError:
        try:
            from . import drivers as drv       # package-style import
        except ImportError:
            return {}
    try:
        return drv.load_agents(root)
    except Exception:
        return {}


def _infer_kind(spec: dict) -> str:
    """A seat reached over HTTP is a provider, not an agent seat. `transport`
    does not exist until ticket 06; defaulting keeps this forward-compatible."""
    return "provider" if spec.get("transport") == "http" else "agent-seat"


def connection(seat: str, root: Path = None) -> dict:
    """Effective state for one seat: stored entry over defaults. Always
    returns a usable dict — an unknown seat is enabled and unverified."""
    stored = load(root)["connections"].get(seat) or {}
    specs = _known_seats(root)
    entry = dict(DEFAULT_ENTRY)
    if seat in specs:
        entry["kind"] = _infer_kind(specs[seat])
    entry.update({k: v for k, v in stored.items() if v is not None})
    entry["name"] = seat
    if entry.get("kind") not in KINDS:
        entry["kind"] = "agent-seat"
    if entry.get("auth") not in AUTH_STATES:
        entry["auth"] = "unknown"
    entry["enabled"] = bool(entry.get("enabled", True))
    return entry


def connections(root: Path = None) -> dict:
    """Every seat the OS knows about (specs ∪ stored entries), each resolved
    through the fail-open defaults. Stored-only names are kept so an MCP or
    service entry survives even though it has no agents.d spec."""
    names = set(_known_seats(root)) | set(load(root)["connections"])
    return {n: connection(n, root) for n in sorted(names)}


def is_enabled(seat: str, root: Path = None) -> bool:
    """The single question routing asks (ticket 03). Fail-open by design."""
    return connection(seat, root)["enabled"]


def update(seat: str, root: Path = None, **fields) -> dict:
    """Merge fields into one connection entry and persist atomically.
    Returns the resolved entry. Validates the two enumerated fields — a typo
    like auth='OK' must not silently become a state nothing matches."""
    if "kind" in fields and fields["kind"] not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got {fields['kind']!r}")
    if "auth" in fields and fields["auth"] not in AUTH_STATES:
        raise ValueError(f"auth must be one of {AUTH_STATES}, got {fields['auth']!r}")
    if any(k.lower() in ("api_key", "key", "token", "secret") for k in fields):
        raise ValueError("settings.json stores the NAME of an env var "
                         "(api_key_env), never a secret value")
    data = load(root)
    entry = data["connections"].setdefault(seat, {})
    entry.setdefault("kind", connection(seat, root)["kind"])
    entry.update(fields)
    save(data, root)
    return connection(seat, root)


# ------------------------------------------------------- the governance trail

def _record(root: Path, event: str, seat: str, **fields):
    """Append one `kind: settings` line to os/runs.jsonl.

    Emission lives HERE, not in the CLI (ticket 02), so the guarantee is a
    property of the store: any caller that flips a seat — CLI today, UI
    tomorrow, orchestrator code later — lands on the trail without having to
    remember to. "Why did this stop routing to gemini" is then answerable from
    runs.jsonl alone, which is the whole reason config changes belong on it.

    Written AFTER the state change, never before: the trail follows the fact.
    A failed emit therefore raises rather than silently succeeding — a
    config change nobody can audit is the failure mode this ticket exists to
    close. (ImportError is the one tolerated case: settings.py must stay
    usable standalone, per its own module docstring.)
    """
    try:
        import orchestrator as orc
    except ImportError:
        try:
            from . import orchestrator as orc       # package-style import
        except ImportError:
            return None
    rec = {"kind": "settings", "event": event, "seat": seat}
    rec.update(fields)
    return orc._emit(Path(root or DEFAULT_ROOT), rec)


def set_enabled(seat: str, enabled: bool, root: Path = None,
                record: bool = True, note: str = "") -> dict:
    """Turn a seat on or off, and put the change on the run trail.

    A no-op (already in the requested state) writes nothing and records
    nothing — the trail holds *changes*. The caller is told so out loud;
    a silently-skipped write is how this OS's characteristic failure starts.
    Read `entry["changed"]` to tell the two apart.
    """
    before = connection(seat, root)["enabled"]
    want = bool(enabled)
    if before == want:
        entry = connection(seat, root)
        entry["changed"] = False
        return entry
    entry = update(seat, root=root, enabled=want)
    entry["changed"] = True
    if record:
        rec = _record(root, "enable" if want else "disable", seat,
                      field="enabled", was=before, now=want, note=note)
        entry["run"] = (rec or {}).get("run", "")
    return entry


def set_field(seat: str, key: str, value, root: Path = None,
              record: bool = True) -> dict:
    """`tools set <seat> k=v`. Routes `enabled` through set_enabled so one
    field can't reach the store by two paths with two different trail
    behaviours. Everything else is recorded as `event: set`.

    The secret refusal in update() is the load-bearing check here — this is
    the one entry point a human types a value into, so it is the one most
    likely to be handed an API key."""
    if key == "enabled":
        return set_enabled(seat, bool(value), root=root, record=record)
    before = connection(seat, root).get(key)
    entry = update(seat, root=root, **{key: value})
    entry["changed"] = before != value
    if record and entry["changed"]:
        rec = _record(root, "set", seat, field=key, was=before, now=value)
        entry["run"] = (rec or {}).get("run", "")
    return entry


# -------------------------------------------------------------------- probes

def _probe_provider(entry: dict) -> tuple:
    """Provider seats: is the named env var present, and does one cheap
    authenticated GET succeed? Returns (auth, detail). The key is read from
    the environment and used only for this request — never stored, never
    logged, never echoed into the detail string."""
    var = entry.get("api_key_env")
    if not var:
        return "unknown", "no api_key_env named in settings"
    key = os.environ.get(var)
    if not key:
        return "missing-key", f"env var {var} is not set"
    url = entry.get("probe_url")
    if not url:
        return "unknown", f"{var} present; no probe_url to verify it"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return ("ok", f"{url} -> {r.status}") if r.status < 400 else \
                   ("needs-auth", f"{url} -> {r.status}")
    except urllib.error.HTTPError as e:
        return ("needs-auth" if e.code in (401, 403) else "unknown",
                f"{url} -> HTTP {e.code}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        return "unknown", f"{url} unreachable: {e}"


def _probe_module(entry: dict, root: Path) -> tuple:
    """Services and MCP servers are too different from each other for one
    generic check ('is a binary on PATH' means nothing to either). So an entry
    may name its own prober — `probe_module: worldmonitor` — and this module
    calls it rather than pretending to know how to test it.

    The contract is one function: `probe(root) -> (auth, detail)`. Keeping the
    knowledge in the service's own module is the same split the whole layer
    rests on; settings.py must not grow a special case per connection."""
    name = entry.get("probe_module")
    if not name:
        return None
    if not str(name).isidentifier():          # it is an import target, not a path
        return "unknown", f"invalid probe_module {name!r}"
    try:
        mod = __import__(str(name))
    except ImportError:
        # Same assumption drivers.py is imported under, made explicit: the
        # prober lives beside this file, whether or not the caller put os/cli
        # on sys.path.
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        try:
            mod = __import__(str(name))
        except ImportError as e:
            return "unknown", f"probe_module '{name}' not importable: {e}"
    fn = getattr(mod, "probe", None)
    if not callable(fn):
        return "unknown", f"probe_module '{name}' has no probe()"
    try:
        auth, detail = fn(root)
    except Exception as e:                     # a broken prober must not brick `tools`
        return "unknown", f"probe_module '{name}' raised: {e}"
    return (auth if auth in AUTH_STATES else "unknown"), str(detail)


def probe(seat: str, root: Path = None, write: bool = True) -> dict:
    """Check one connection and (by default) record the result.

    CLI seats  -> is the binary on PATH?
    Providers  -> is the env var set, and does a cheap authenticated GET pass?
    probe_module -> delegated to the service's own probe(root), whatever kind
                    it is; a service knows how to test itself, this file doesn't

    A probe records what it found; it never flips `enabled`. You turn seats
    off, discovery does not — otherwise a flaky network would silently
    reconfigure routing."""
    entry = connection(seat, root)
    delegated = _probe_module(entry, root)
    if delegated:
        auth, detail = delegated
    elif entry["kind"] == "provider":
        auth, detail = _probe_provider(entry)
    elif entry["kind"] in ("mcp", "service"):
        auth, detail = entry.get("auth", "unknown"), "not machine-probeable"
    else:
        spec = _known_seats(root).get(seat)
        if not spec:
            auth, detail = "unknown", "no spec in os/agents.d/ or built-ins"
        else:
            binary = spec.get("binary", seat)
            path = shutil.which(binary)
            if path:
                # On PATH is not the same as authenticated — gemini's pending
                # interactive login is exactly this case, so a previously
                # recorded needs-auth is NOT overwritten by a PATH hit.
                auth = "needs-auth" if entry.get("auth") == "needs-auth" else "ok"
                detail = f"binary-found: {path}"
            else:
                auth, detail = "missing-binary", f"'{binary}' not on PATH"
    result = {"name": seat, "kind": entry["kind"], "auth": auth,
              "probe": detail, "last_probe": _now()}
    if write:
        update(seat, root=root, auth=auth, probe=detail,
               last_probe=result["last_probe"])
    return result


def probe_all(root: Path = None, write: bool = True) -> list:
    return [probe(n, root, write) for n in connections(root)]


def status_rows(root: Path = None) -> list:
    """One row per connection, ready for the `tools` table (ticket 02) and the
    UI panel (ticket 05). Reads only — no probing, no writes."""
    rows = []
    for name, e in connections(root).items():
        rows.append({"name": name, "kind": e["kind"],
                     "enabled": e["enabled"], "auth": e["auth"],
                     "last_probe": e.get("last_probe", ""),
                     "probe": e.get("probe", ""),
                     "api_key_env": e.get("api_key_env", ""),
                     "note": e.get("note", "")})
    return rows


if __name__ == "__main__":       # smoke view; the real CLI is ticket 02
    for r in status_rows():
        print(f"{r['name']:<12} {r['kind']:<11} "
              f"{'on' if r['enabled'] else 'OFF':<4} {r['auth']:<15} "
              f"{r['probe'][:52]}")
