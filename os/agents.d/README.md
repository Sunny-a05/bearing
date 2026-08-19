# agents.d — drop-in agent definitions

**Adding a new agent to the OS is a JSON file here, not code.** `os/cli/drivers.py`
merges every `*.json` in this folder over its built-ins (ollama, claude, gemini,
codex) at load time. A file whose `name` matches a built-in *updates* it (models
map merges); a new name *registers* a new agent — Hermes, OpenClaw, Odysseus,
whatever comes next.

Files starting with `_` or not ending in `.json` are ignored (rename to
`foo.json.disabled` to switch one off).

## Schema

```json
{
  "name": "hermes",                     // seat name used by drive/council/route
  "binary": "hermes",                   // executable probed on PATH
  "tier": "hermes",                     // tier label for run-records
  "cost": 2,                            // 0=free .. 3=scarce (frontier)
  "argv": ["{binary}", "run", "-p"],    // command shape; {binary} and {model} substituted
  "prompt_via": "argv",                 // "argv" appends prompt | "stdin" pipes it
  "stdin_ok": true,                     // long prompts may fall back to stdin
  "model_flag": "--model",              // appended when a model is given (if no {model} in argv)
  "models": {                           // roster-alias -> CLI model arg
    "default": null                     // null = omit the flag, CLI decides
  },
  "timeout": 300,
  "strip": ["ansi", "think"],           // output hygiene passes
  "env": {"SOME_VAR": "true"},          // extra env vars for headless runs
  "notes": "what this seat is for"
}
```

## Current overlays

- `ollama.json` — pins the **verified** local tags (checked against
  `ollama list` on Khan's machine 2026-07-10). Edit this file when models
  change — never the Python.
- `hermes.json` — the paid seat. Argv probed live 2026-07-22 (wayfinder
  `os-v2-heavy-usage` ticket 04) against Hermes Agent v0.19.0; it replaced a
  guessed `_hermes.json.example`, which is now deleted. Two traps worth
  knowing before you edit it:
  - **`stdin_ok` must stay `false`.** `-z` takes the prompt as its flag
    *value*, so `_build_cmd`'s >6000-char stdin fallback would emit a
    valueless `-z`. Prompts on this seat are capped by the Windows argv limit.
  - **Use `{model}` in `argv`, not `model_flag`.** `_build_cmd` appends
    `model_flag` *before* the prompt, which would hand `-z` the string `-m`.
    This applies to any seat whose prompt flag takes a value.

  It also carries a known upstream defect — Hermes exits 0 and prints errors
  to stdout on API failure, so `submit()` scores a failed run as
  `outcome: ok`. Tracked as ticket 21, not fixed in the spec.

## Rules

1. A new seat here makes it reachable by `drive`, `council`, and sessions.
   It does **not** add it to the routing policy — task-class chains live in
   `os/orchestration.md` + `orchestrator.py` and change deliberately.
2. Frontier-cost seats (`cost: 3`) are never auto-driven by escalation;
   they must be named explicitly (token-economy guard).
3. OS hard rule 4 applies to every seat defined here: driver output drafts,
   it never writes to `wiki/` unreviewed.
