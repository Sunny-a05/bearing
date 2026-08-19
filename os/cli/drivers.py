#!/usr/bin/env python3
"""drivers.py — the Driver layer: seats and how to reach them. Stdlib only.

Sits BELOW the orchestrator (orchestrator.py imports this, never the other
way around). The orchestrator decides WHO should work (routing policy) and
records WHAT happened (run-records); this module knows HOW to actually reach
each seat: which binary, which argv shape, how the prompt travels, and how to
clean the output. It never emits run-records itself — pure execution.

Three responsibilities:
  1. AGENT SPECS — a data-driven table of every drivable seat. Built-ins:
     ollama, claude (Claude Code headless `claude -p`), gemini (Gemini CLI),
     codex (Codex CLI). Adding a NEW agent (Hermes, OpenClaw, Odysseus, ...)
     is a JSON file in os/agents.d/, not code — see os/agents.d/README.md.
  2. SUBMIT — run one prompt on one seat, foreground, with timeout. Windows-
     proofed: UTF-8 decode (the cp1252 crash found in the 2026-07-10
     shakedown), ANSI/spinner stripping, thinking-block stripping.
  3. SESSIONS — background (detached) runs with a JSON registry at
     os/sessions.json and logs under os/sessions/. list / tail / kill.

Model names: submit() accepts either a roster alias (resolved through the
spec's "models" map — e.g. "haiku" -> claude --model haiku) or a raw tag
passed through untouched (e.g. an Ollama tag like "qwen3.5:0.8b").
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent
AGENTS_D_REL = Path("os") / "agents.d"
SESSIONS_FILE_REL = Path("os") / "sessions.json"
SESSIONS_DIR_REL = Path("os") / "sessions"

IS_WIN = sys.platform == "win32"

# ------------------------------------------------------------ output hygiene

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[<>=]")
_CUB_RE = re.compile(r"\x1b\[(\d*)D(?:\x1b\[K)?")   # cursor-back n (+ erase)
_SPINNER_LINE_RE = re.compile(r"^[⠀-⣿\s]+$", re.MULTILINE)  # braille spinners
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
# Ollama wraps visible chain-of-thought in "Thinking..." / "...done thinking."
_OLLAMA_THINK_RE = re.compile(r"Thinking\.\.\..*?\.\.\.done thinking\.?", re.DOTALL)


def _apply_erasures(text: str) -> str:
    """Honor terminal overwrite semantics instead of just deleting escape
    codes. Ollama line-rewrapping emits `pr` + ESC[2D ESC[K + `provide` —
    stripping only the codes leaves BOTH fragments ('pr' 'provide', the
    word-duplication bug from the 2026-07-10 shakedown). So: \\r collapses to
    the last overwrite of the line; cursor-back(n) really deletes n chars."""
    text = text.replace("\r\n", "\n")
    text = "\n".join(seg.split("\r")[-1] for seg in text.split("\n"))
    out, i = [], 0
    while i < len(text):
        m = _CUB_RE.match(text, i)
        if m:
            n = int(m.group(1) or "1")
            while out and n > 0 and out[-1] != "\n":
                out.pop()
                n -= 1
            i = m.end()
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def strip_noise(text: str, kinds=("ansi", "think")) -> str:
    """Remove terminal escape codes and visible thinking blocks from CLI
    output. 'think' is belt-and-braces — only marker-delimited blocks are
    removed, never a heuristic guess at what looks like reasoning."""
    if not text:
        return text
    if "ansi" in kinds:
        text = _apply_erasures(text)
        text = _ANSI_RE.sub("", text)
        text = _SPINNER_LINE_RE.sub("", text)
    if "think" in kinds:
        text = _THINK_BLOCK_RE.sub("", text)
        text = _OLLAMA_THINK_RE.sub("", text)
    return text.strip()


# --------------------------------------------------------------- agent specs
# Ollama tags verified against `ollama list`, 2026-07-10
# (the old best-guesses qwen3:0.6b / gemma3:4b did not exist). Override in
# os/agents.d/ollama.json without touching code.

OLLAMA_FIRST_PASS = "qwen3.5:0.8b"
OLLAMA_ESCALATION = "gemma4:e2b"     # 7.2 GB — a real capability step up
OLLAMA_TIMEOUT = 180

BUILTIN_AGENTS = {
    "ollama": {
        "name": "ollama", "binary": "ollama", "tier": "ollama", "cost": 0,
        "argv": ["{binary}", "run", "{model}"],
        "prompt_via": "argv", "stdin_ok": True,
        "models": {"first_pass": OLLAMA_FIRST_PASS,
                   "escalation": OLLAMA_ESCALATION,
                   "default": OLLAMA_FIRST_PASS},
        "timeout": OLLAMA_TIMEOUT, "strip": ["ansi", "think"],
        "notes": "local tier — free, machine-drivable, never writes to wiki/",
    },
    "claude": {
        "name": "claude", "binary": "claude", "tier": "claude", "cost": 2,
        "argv": ["{binary}", "-p", "--output-format", "text"],
        "prompt_via": "stdin", "stdin_ok": True,
        "model_flag": "--model",
        "models": {"haiku": "haiku", "sonnet": "sonnet",
                   "opus/fable": "opus", "default": "sonnet"},
        "timeout": 420, "strip": ["ansi"],
        "notes": "Claude Code headless print mode — spends your subscription",
    },
    "gemini": {
        "name": "gemini", "binary": "gemini", "tier": "gemini", "cost": 1,
        "argv": ["{binary}", "-p"],
        "prompt_via": "argv", "stdin_ok": False,
        "model_flag": "-m",
        "models": {"gemini-pro": "gemini-2.5-pro",
                   "gemini-flash": "gemini-2.5-flash",
                   "default": None},   # None -> omit flag, CLI default
        # headless runs need workspace trust (2026-07-10 shakedown finding)
        "env": {"GEMINI_CLI_TRUST_WORKSPACE": "true"},
        "timeout": 300, "strip": ["ansi"],
        "notes": "Gemini CLI — generous free tier; long-context + multimodal",
    },
    "codex": {
        "name": "codex", "binary": "codex", "tier": "codex", "cost": 2,
        "argv": ["{binary}", "exec"],
        "prompt_via": "argv", "stdin_ok": False,
        "models": {"default": None},
        "timeout": 300, "strip": ["ansi"],
        "notes": "Codex CLI — not installed 2026-07-10; probe reports absent",
    },
}

_AGENTS_CACHE = {}


def load_agents(root: Path = None) -> dict:
    """BUILTIN_AGENTS overlaid with os/agents.d/*.json. An overlay file whose
    stem matches a built-in updates it (dict-merge, one level deep for
    'models'); a new stem registers a brand-new agent. Files ending in
    .disabled or starting with _ are skipped. Cached per root."""
    root = Path(root) if root else DEFAULT_ROOT
    key = str(root)
    if key in _AGENTS_CACHE:
        return _AGENTS_CACHE[key]
    agents = {k: dict(v) for k, v in BUILTIN_AGENTS.items()}
    for k in agents:
        agents[k]["models"] = dict(agents[k].get("models", {}))
    d = root / AGENTS_D_REL
    if d.is_dir():
        for f in sorted(d.glob("*.json")):
            if f.name.startswith("_"):
                continue
            try:
                spec = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            name = spec.get("name", f.stem)
            if name in agents:
                models = spec.pop("models", None)
                agents[name].update(spec)
                if models:
                    agents[name]["models"].update(models)
            else:
                spec.setdefault("name", name)
                spec.setdefault("binary", name)
                spec.setdefault("tier", name)
                spec.setdefault("argv", ["{binary}"])
                spec.setdefault("prompt_via", "argv")
                spec.setdefault("models", {"default": None})
                spec.setdefault("timeout", 300)
                spec.setdefault("strip", ["ansi"])
                agents[name] = spec
    _AGENTS_CACHE[key] = agents
    return agents


def which(spec: dict):
    return shutil.which(spec.get("binary", spec["name"]))


def probe(root: Path = None) -> list:
    """One row per known agent: is its binary actually on this machine?"""
    rows = []
    for name, spec in load_agents(root).items():
        path = which(spec)
        rows.append({"name": name, "binary": spec.get("binary", name),
                     "available": path is not None, "path": path or "",
                     "tier": spec.get("tier", name),
                     "models": {k: v for k, v in spec.get("models", {}).items()},
                     "notes": spec.get("notes", "")})
    return rows


def resolve_model(spec: dict, model: str = None):
    """Roster alias -> CLI model arg via the spec's models map; unknown
    strings pass through raw (Ollama tags etc.). None -> the spec default."""
    models = spec.get("models", {})
    if model is None:
        return models.get("default")
    return models.get(model, model)


# ------------------------------------------------------------------- submit

def _build_cmd(spec: dict, prompt: str, model: str = None):
    """Returns (argv, stdin_payload). Long prompts travel via stdin when the
    spec allows it (Windows argv limit is ~32k; stay far under it)."""
    binary = which(spec)
    if binary is None:
        return None, None
    resolved = resolve_model(spec, model)
    argv = []
    for a in spec["argv"]:
        a = a.replace("{binary}", binary)
        if "{model}" in a:
            if resolved is None:
                raise ValueError(f"{spec['name']}: a model tag is required")
            a = a.replace("{model}", resolved)
        argv.append(a)
    if "{model}" not in "".join(spec["argv"]) and resolved and spec.get("model_flag"):
        argv += [spec["model_flag"], resolved]
    via = spec.get("prompt_via", "argv")
    if via == "argv" and spec.get("stdin_ok") and len(prompt) > 6000:
        via = "stdin"
    if via == "argv":
        argv.append(prompt)
        return argv, None
    return argv, prompt


def submit(agent: str, prompt: str, model: str = None, root: Path = None,
           timeout: int = None, cwd: str = None) -> dict:
    """Run one prompt on one seat, foreground. Never raises on the failure
    modes that matter — returns outcome: ok|empty|error|timeout|unavailable.
    Output is noise-stripped per the spec; 'raw' keeps the original."""
    agents = load_agents(root)
    if agent not in agents:
        return {"agent": agent, "model": model, "outcome": "unavailable",
                "output": None, "latency_s": 0.0,
                "error": f"unknown agent '{agent}' — see `agentos.py agents`"}
    spec = agents[agent]
    try:
        argv, stdin_payload = _build_cmd(spec, prompt, model)
    except ValueError as e:
        return {"agent": agent, "model": model, "outcome": "error",
                "output": None, "latency_s": 0.0, "error": str(e)}
    if argv is None:
        return {"agent": agent, "model": model, "outcome": "unavailable",
                "output": None, "latency_s": 0.0,
                "error": f"binary '{spec.get('binary')}' not on PATH"}
    resolved = resolve_model(spec, model)
    env = {**os.environ, **spec["env"]} if spec.get("env") else None
    t0 = time.monotonic()
    kw = dict(capture_output=True, encoding="utf-8", errors="replace",
              timeout=timeout or spec.get("timeout", 300), cwd=cwd, env=env)
    if stdin_payload is not None:
        kw["input"] = stdin_payload
    else:
        # NEVER inherit stdin: under a non-shell parent (the UI's Node server)
        # it's an open pipe that never closes, and CLIs like `ollama run`
        # read piped stdin to EOF -> infinite hang (found 2026-07-10).
        kw["stdin"] = subprocess.DEVNULL
    try:
        proc = subprocess.run(argv, **kw)   # utf-8: the cp1252 shakedown fix
    except subprocess.TimeoutExpired:
        return {"agent": agent, "model": resolved, "outcome": "timeout",
                "output": None, "latency_s": round(time.monotonic() - t0, 1)}
    except OSError as e:
        return {"agent": agent, "model": resolved, "outcome": "error",
                "output": None, "latency_s": round(time.monotonic() - t0, 1),
                "error": str(e)}
    lat = round(time.monotonic() - t0, 1)
    raw = proc.stdout or ""
    out = strip_noise(raw, tuple(spec.get("strip", ["ansi"])))
    if proc.returncode != 0:
        return {"agent": agent, "model": resolved, "outcome": "error",
                "output": out or None, "raw": raw, "latency_s": lat,
                "error": (proc.stderr or "")[-400:].strip()}
    if not out:
        return {"agent": agent, "model": resolved, "outcome": "empty",
                "output": None, "raw": raw, "latency_s": lat}
    return {"agent": agent, "model": resolved, "outcome": "ok",
            "output": out, "raw": raw, "latency_s": lat}


# ----------------------------------------------------------------- sessions

def _sessions_file(root: Path) -> Path:
    return Path(root or DEFAULT_ROOT) / SESSIONS_FILE_REL


def _sessions_dir(root: Path) -> Path:
    return Path(root or DEFAULT_ROOT) / SESSIONS_DIR_REL


def _read_sessions(root: Path) -> list:
    p = _sessions_file(root)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _write_sessions(root: Path, sessions: list):
    p = _sessions_file(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(sessions, indent=1, ensure_ascii=False),
                 encoding="utf-8")


def _alive(pid: int) -> bool:
    """Liveness WITHOUT os.kill(pid, 0) — on Windows that TERMINATES the
    process (TerminateProcess), it is not a POSIX-style probe."""
    if IS_WIN:
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, encoding="utf-8", errors="replace",
                timeout=10).stdout or ""
            return str(pid) in out
        except (OSError, subprocess.TimeoutExpired):
            return False
    import os as _os
    try:
        _os.kill(pid, 0)
        return True
    except OSError:
        return False


def spawn(agent: str, prompt: str, model: str = None, root: Path = None,
          task: str = "", item: str = "", cwd: str = None) -> dict:
    """Detached background run. Output streams to os/sessions/<sid>.log;
    the registry row lands in os/sessions.json. Returns the row."""
    root = Path(root) if root else DEFAULT_ROOT
    agents = load_agents(root)
    if agent not in agents:
        raise ValueError(f"unknown agent '{agent}'")
    spec = agents[agent]
    argv, stdin_payload = _build_cmd(spec, prompt, model)
    if argv is None:
        raise FileNotFoundError(f"binary '{spec.get('binary')}' not on PATH")
    sid = "s-" + uuid.uuid4().hex[:8]
    logdir = _sessions_dir(root)
    logdir.mkdir(parents=True, exist_ok=True)
    logfile = logdir / f"{sid}.log"
    stdin_src = subprocess.DEVNULL
    if stdin_payload is not None:
        pf = logdir / f"{sid}.prompt"
        pf.write_text(stdin_payload, encoding="utf-8")
        stdin_src = open(pf, "rb")
    creation = 0
    if IS_WIN:
        creation = (subprocess.CREATE_NEW_PROCESS_GROUP
                    | getattr(subprocess, "DETACHED_PROCESS", 0x00000008))
    env = {**os.environ, **spec["env"]} if spec.get("env") else None
    with open(logfile, "wb") as lf:
        proc = subprocess.Popen(argv, stdin=stdin_src, stdout=lf,
                                stderr=subprocess.STDOUT, cwd=cwd,
                                creationflags=creation, env=env)
    if stdin_src is not subprocess.DEVNULL:
        stdin_src.close()
    row = {"sid": sid, "agent": agent,
           "model": resolve_model(spec, model), "pid": proc.pid,
           "task": task, "item": item, "status": "running",
           "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "log": str(logfile.relative_to(root)),
           "prompt_head": prompt[:120]}
    sessions = _read_sessions(root)
    sessions.append(row)
    _write_sessions(root, sessions)
    return row


def sessions_list(root: Path = None, refresh: bool = True) -> list:
    root = Path(root) if root else DEFAULT_ROOT
    sessions = _read_sessions(root)
    if refresh:
        changed = False
        for s in sessions:
            if s.get("status") == "running" and not _alive(s.get("pid", -1)):
                s["status"] = "done"
                changed = True
        if changed:
            _write_sessions(root, sessions)
    return sessions


def session_tail(sid: str, root: Path = None, n: int = 40) -> str:
    root = Path(root) if root else DEFAULT_ROOT
    for s in _read_sessions(root):
        if s["sid"] == sid:
            p = root / s["log"]
            if not p.exists():
                return "(no log yet)"
            text = strip_noise(p.read_text(encoding="utf-8", errors="replace"))
            return "\n".join(text.splitlines()[-n:])
    raise KeyError(f"no session {sid}")


def session_kill(sid: str, root: Path = None) -> dict:
    root = Path(root) if root else DEFAULT_ROOT
    sessions = _read_sessions(root)
    for s in sessions:
        if s["sid"] == sid:
            pid = s.get("pid", -1)
            if s.get("status") == "running" and _alive(pid):
                if IS_WIN:
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                   capture_output=True)
                else:
                    import os as _os
                    import signal as _signal
                    try:
                        _os.kill(pid, _signal.SIGTERM)
                    except OSError:
                        pass
            s["status"] = "killed"
            _write_sessions(root, sessions)
            return s
    raise KeyError(f"no session {sid}")
