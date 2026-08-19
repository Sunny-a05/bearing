#!/usr/bin/env python3
"""dockyard.py — dock v3 mechanics (spec: os/dock/DOCK.md). Stdlib only.

Implements the machine half of the pipeline:
  dedup (hash vs raw/ AND library/, fuzzy vs both indexes) -> thin digest
  ("graphify": entities + relationships, draft-only; model execution is
  delegated to orchestrator.py — the Orchestration layer owns routing,
  escalation, and run-records) -> filing (library sidecar YAML + catalog +
  log, or handoff to INGEST) -> reactivation logging -> enrichment (rich
  tier + claims) -> breadth-or-frequency promotion check -> promotion.

The DECISION step (DOCK.md step 2) is deliberately NOT here — a Sonnet+ agent
(or you) reads the thin digest and decides; this module only executes the
outcome. Local-model output drafts, never decides (OS hard rule 4).

Used via agentos.py; every function takes `root` = repo root.
"""
import hashlib
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import extract as extract_mod
import orchestrator as orc

# Model roster, routing, and execution live in orchestrator.py (the
# Orchestration layer — os/orchestration.md). Dockyard owns the dock's prompt
# and parsing only; it asks the orchestrator to run models, never runs them
# itself. Backcompat aliases (docs/STATE referenced these constants here):
OLLAMA_FIRST_PASS = orc.OLLAMA_FIRST_PASS
OLLAMA_ESCALATION = orc.OLLAMA_ESCALATION
OLLAMA_TIMEOUT = orc.OLLAMA_TIMEOUT

URGENCIES = ("routine", "worth-a-look", "surface-now")
VERDICTS = ("ingest", "library", "ask-user")

RAW_EXCLUDE = {"index.md", "log.md", "desktop.ini"}
LIB_EXCLUDE = {"index.md", "readme.md"}
DIGEST_SUFFIX = ".digest.yaml"
DIGEST_TRUNCATE = 6000   # chars of extracted text fed to the local model
STALE_DAYS = 14

DIGEST_PROMPT = """You are indexing a document for an AI-maintained knowledge base. Read the text below and output EXACTLY these 6 lines, in this order, with no preamble, no markdown, nothing else:

GIST: <what this document is, one short line>
ENTITIES: <named people, projects, tools, concepts — separated by "; ", 3 to 10 of them>
RELATIONSHIPS: <subject | verb | object>; <subject | verb | object>  <- 1 to 6 triples between the entities above
TAGS: <which of these project slugs this touches: {slugs} — comma-separated, or "none">
URGENCY: <one of: routine | worth-a-look | surface-now>
VERDICT: <one of: ingest (clearly, broadly, immediately valuable) | library (the default — archive it) | ask-user (genuinely ambiguous)>

Document filename: {filename}
Document text (may be truncated):
---
{content}
---
"""


# ------------------------------------------------------------------- layout

def P(root: Path) -> dict:
    root = Path(root)
    return {
        "root": root,
        "inbox": root / "os" / "dock" / "inbox",
        "raw": root / "raw",
        "library": root / "library",
        "registry": root / "os" / "registry",
        "index": root / "index.md",
        "lib_index": root / "library" / "index.md",
        "log": root / "log.md",
    }


def today() -> str:
    return date.today().isoformat()


def slugify(name: str) -> str:
    s = Path(name).stem.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "item"


def registry_slugs(root: Path) -> list:
    reg = P(root)["registry"]
    if not reg.exists():
        return []
    return sorted(p.stem for p in reg.glob("*.md") if not p.name.startswith("_"))


def inbox_items(root: Path) -> list:
    inbox = P(root)["inbox"]
    if not inbox.exists():
        return []
    return sorted(p for p in inbox.iterdir()
                  if p.is_file() and p.name.lower() != "readme.md"
                  and not p.name.endswith(DIGEST_SUFFIX))


# ------------------------------------------------------------ mini-YAML I/O
# The sidecar schema is fixed (DOCK.md step 3b), so we emit and parse exactly
# that shape instead of depending on pyyaml. Round-trip is guaranteed only for
# files this module wrote.

def _q(s) -> str:
    """Quote a scalar for YAML if needed."""
    s = str(s)
    if s == "":
        return '""'
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _./-]*", s) and s.strip() == s \
            and s.lower() not in ("true", "false", "null", "none"):
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _unq(s: str):
    s = s.strip()
    if s.startswith('"') and s.endswith('"') and len(s) >= 2:
        return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if s == "true":
        return True
    if s == "false":
        return False
    return s


def _split_flow(body: str) -> list:
    """Split 'a, b, "c, d"' on top-level commas."""
    out, buf, inq = [], "", False
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == '"' and (i == 0 or body[i - 1] != "\\"):
            inq = not inq
        if ch == "," and not inq:
            out.append(buf.strip())
            buf = ""
        else:
            buf += ch
        i += 1
    if buf.strip():
        out.append(buf.strip())
    return [x for x in out if x]


def emit_digest(d: dict) -> str:
    lines = []
    for key in ("source", "dropped", "gist"):
        if key in d:
            lines.append(f"{key}: {_q(d.get(key, ''))}")
    lines.append("entities: [" + ", ".join(_q(e) for e in d.get("entities", [])) + "]")
    rels = d.get("relationships", [])
    if rels:
        lines.append("relationships:")
        for r in rels:
            lines.append("  - {from: %s, verb: %s, to: %s}"
                         % (_q(r.get("from", "")), _q(r.get("verb", "")), _q(r.get("to", ""))))
    else:
        lines.append("relationships: []")
    lines.append("tags: [" + ", ".join(_q(t) for t in d.get("tags", [])) + "]")
    lines.append(f"urgency: {d.get('urgency', 'routine')}")
    if "verdict" in d:
        lines.append(f"verdict: {d['verdict']}")
    lines.append(f"tier: {d.get('tier', 'thin')}")
    claims = d.get("claims", [])
    if claims:
        lines.append("claims:")
        for c in claims:
            lines.append(f"  - {_q(c)}")
    else:
        lines.append("claims: []")
    reacts = d.get("reactivations", [])
    if reacts:
        lines.append("reactivations:")
        for r in reacts:
            lines.append("  - {date: %s, trigger: %s, note: %s}"
                         % (_q(r.get("date", "")), _q(r.get("trigger", "")), _q(r.get("note", ""))))
    else:
        lines.append("reactivations: []")
    lines.append(f"promoted: {'true' if d.get('promoted') else 'false'}")
    # draft-only provenance for the deciding agent (dropped when filed to library)
    if d.get("model"):
        lines.append(f"model: {_q(d['model'])}")
    if d.get("notes"):
        lines.append("notes:")
        for n_ in d["notes"]:
            lines.append(f"  - {_q(n_)}")
    return "\n".join(lines) + "\n"


def _parse_flow_map(body: str) -> dict:
    out = {}
    for part in _split_flow(body):
        if ":" in part:
            k, _, v = part.partition(":")
            out[k.strip()] = _unq(v)
    return out


def parse_digest(text: str) -> dict:
    d = {"entities": [], "relationships": [], "tags": [], "claims": [],
         "reactivations": [], "promoted": False, "tier": "thin", "urgency": "routine"}
    current_list = None
    for line in text.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if line.startswith("  - ") and current_list is not None:
            item = line[4:].strip()
            if item.startswith("{") and item.endswith("}"):
                d[current_list].append(_parse_flow_map(item[1:-1]))
            else:
                d[current_list].append(_unq(item))
            continue
        current_list = None
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val == "":
            if key in ("relationships", "claims", "reactivations", "notes"):
                current_list = key
                d[key] = []
            continue
        if val.startswith("[") and val.endswith("]"):
            items = _split_flow(val[1:-1])
            if key == "relationships":
                d[key] = [_parse_flow_map(x[1:-1]) for x in items
                          if x.startswith("{") and x.endswith("}")]
            else:
                d[key] = [_unq(x) for x in items]
        else:
            d[key] = _unq(val)
    d["promoted"] = d.get("promoted") is True
    return d


# ------------------------------------------------------------------- dedup

def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _corpus_files(root: Path):
    """(kind, path) for every dedup-relevant file in raw/ and library/."""
    p = P(root)
    if p["raw"].exists():
        for f in p["raw"].rglob("*"):
            if f.is_file() and f.name not in RAW_EXCLUDE and ".claude" not in f.parts:
                yield "raw", f
    if p["library"].exists():
        for f in p["library"].iterdir():
            if (f.is_file() and f.name.lower() not in LIB_EXCLUDE
                    and not f.name.endswith(DIGEST_SUFFIX)):
                yield "library", f


def _normalize_title(name: str) -> str:
    stem = Path(name).stem.lower()
    return re.sub(r"\s+", " ", re.sub(r"[-_]+", " ", stem)).strip()


def _fuzzy_hits(item: Path, index_path: Path) -> list:
    if not index_path.exists():
        return []
    words = {w for w in _normalize_title(item.name).split() if len(w) > 3}
    if not words:
        return []
    hits = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.strip().startswith("-"):
            continue
        low = line.lower()
        if sum(1 for w in words if w in low) >= max(2, len(words) // 2):
            hits.append(line.strip())
    return hits


def dedup_check(item: Path, root: Path) -> dict:
    """DOCK.md step 0 — exact hash vs raw/ + library/, fuzzy vs both catalogs."""
    result = {"exact_raw": None, "exact_library": None, "fuzzy": []}
    try:
        item_hash = _hash_file(item)
    except OSError:
        return result
    for kind, f in _corpus_files(root):
        try:
            if _hash_file(f) == item_hash:
                result["exact_" + kind] = f
                break
        except OSError:
            continue
    p = P(root)
    result["fuzzy"] = (_fuzzy_hits(item, p["index"])
                       + _fuzzy_hits(item, p["lib_index"]))
    return result


# -------------------------------------------------------------- thin digest

def run_ollama(model: str, prompt: str, timeout: int = OLLAMA_TIMEOUT):
    """Backcompat shim — execution belongs to the orchestrator now."""
    out, _, _ = orc.run_ollama(model, prompt, timeout=timeout)
    return out


def parse_model_output(out: str) -> dict:
    """Parse the 6-line digest format; missing fields stay empty."""
    d = {"gist": "", "entities": [], "relationships": [], "tags": [],
         "urgency": "", "verdict": ""}
    for line in out.splitlines():
        line = line.strip()
        low = line.lower()
        if low.startswith("gist:"):
            d["gist"] = line[5:].strip()
        elif low.startswith("entities:"):
            d["entities"] = [e.strip() for e in re.split(r"[;,]", line[9:]) if e.strip()]
        elif low.startswith("relationships:"):
            for triple in line[14:].split(";"):
                bits = [b.strip() for b in triple.split("|")]
                if len(bits) == 3 and all(bits):
                    d["relationships"].append(
                        {"from": bits[0], "verb": bits[1], "to": bits[2]})
        elif low.startswith("tags:"):
            tags = [t.strip().lower() for t in line[5:].split(",") if t.strip()]
            d["tags"] = [t for t in tags if t != "none"]
        elif low.startswith("urgency:"):
            v = line[8:].strip().lower()
            d["urgency"] = v if v in URGENCIES else ""
        elif low.startswith("verdict:"):
            v = line[8:].strip().lower().split()[0] if line[8:].strip() else ""
            d["verdict"] = v if v in VERDICTS else ""
    return d


def _digest_is_thin(d: dict) -> bool:
    return not d["entities"] or not d["verdict"] or not d["urgency"]


def thin_digest(item: Path, root: Path, model: str = None) -> dict:
    """Extract text, run the graphify pass on the local tier, return the digest
    dict (with 'model' and 'extraction' provenance). Draft only — never a decision."""
    ex = extract_mod.extract(item)
    result = {
        "source": f"os/dock/inbox/{item.name}",
        "gist": "", "entities": [], "relationships": [], "tags": [],
        "urgency": "routine", "verdict": "", "tier": "thin",
        "claims": [], "reactivations": [], "promoted": False,
        "extraction": ex, "model": None, "notes": [],
    }
    if ex.needs_ocr:
        result["notes"].append("NO machine-readable text (scanned?) — route to "
                               "Gemini/Claude vision per os/orchestration.md, then re-digest.")
        return result
    if not ex.ok or not ex.text.strip():
        result["notes"].append("extraction failed — digest skipped: "
                               + "; ".join(ex.warnings))
        return result
    slugs = registry_slugs(root)
    prompt = DIGEST_PROMPT.format(slugs=", ".join(slugs) or "none registered",
                                  filename=item.name,
                                  content=ex.text[:DIGEST_TRUNCATE])

    def validate(out):
        parsed = parse_model_output(out)
        if _digest_is_thin(parsed):
            return False, parsed, "output too thin"
        return True, parsed, ""

    # Execution, escalation, failure handling, and run-records all belong to
    # the Orchestration layer — task class dock.digest (local ladder -> Haiku).
    rr = orc.run("dock.digest", prompt, root=root, item=item.name,
                 validate=validate, model=model)
    for a in rr.attempts:                       # keep best partial from any pass
        p = a.get("payload")
        if p and (p.get("entities") or p.get("gist")):
            result.update({k: v for k, v in p.items() if v})
    if rr.ok:
        result.update(rr.payload)
        result["model"] = rr.model
    result["tags"] = [t for t in result.get("tags", []) if t in slugs]
    result["notes"].extend(rr.notes)
    return result


def draft_sidecar_path(item: Path) -> Path:
    return item.with_name(item.name + DIGEST_SUFFIX)


def save_draft(item: Path, digest: dict) -> Path:
    out = draft_sidecar_path(item)
    out.write_text(emit_digest(digest), encoding="utf-8")
    return out


def load_draft(item: Path):
    p = draft_sidecar_path(item)
    return parse_digest(p.read_text(encoding="utf-8")) if p.exists() else None


# ------------------------------------------------------------------ filing

def _append(path: Path, text: str):
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    path.write_text(existing + text, encoding="utf-8")


def append_log(root: Path, kind: str, title: str, bullets: list):
    entry = f"\n## [{today()}] {kind} | {title}\n\n"
    entry += "".join(f"- {b}\n" for b in bullets)
    _append(P(root)["log"], entry)


def _dock_history(root: Path, card_slug: str, line: str):
    card = P(root)["registry"] / f"{card_slug}.md"
    if not card.exists():
        return False
    text = card.read_text(encoding="utf-8")
    if "## Dock history" not in text:
        text = text.rstrip("\n") + "\n\n## Dock history\n"
    text = text.rstrip("\n") + f"\n- {line}\n"
    card.write_text(text, encoding="utf-8")
    return True


def _try_unlink(path: Path) -> bool:
    """Delete if the filesystem lets us; otherwise report instead of crashing."""
    try:
        path.unlink()
        return True
    except OSError as e:
        print(f"  (could not delete {path.name}: {e.__class__.__name__} — remove it manually)")
        return False


def _unique_dest(folder: Path, name: str) -> Path:
    dest = folder / name
    n = 2
    while dest.exists():
        dest = folder / f"{Path(name).stem}-{n}{Path(name).suffix}"
        n += 1
    return dest


def file_to_library(item: Path, root: Path) -> dict:
    """DOCK.md step 3b — move to library/, write sidecar, catalog, log, history."""
    p = P(root)
    digest = load_draft(item) or {}
    dest = _unique_dest(p["library"], item.name)
    slug = slugify(dest.name)
    sidecar = p["library"] / f"{slug}{DIGEST_SUFFIX}"
    n = 2
    while sidecar.exists():
        sidecar = p["library"] / f"{slug}-{n}{DIGEST_SUFFIX}"
        n += 1

    final = {
        "source": f"library/{dest.name}",
        "dropped": today(),
        "gist": digest.get("gist", ""),
        "entities": digest.get("entities", []),
        "relationships": digest.get("relationships", []),
        "tags": digest.get("tags", []),
        "urgency": digest.get("urgency", "routine") or "routine",
        "tier": "thin",
        "claims": [],
        "reactivations": [],
        "promoted": False,
    }
    item.replace(dest)
    sidecar.write_text(emit_digest(final), encoding="utf-8")

    # catalog line (drop the "*Empty*" placeholder on first real entry)
    idx = p["lib_index"]
    if idx.exists():
        text = idx.read_text(encoding="utf-8")
        text = "\n".join(l for l in text.splitlines()
                         if not l.strip().startswith("*Empty"))
        idx.write_text(text.rstrip("\n") + "\n", encoding="utf-8")
    gist = final["gist"] or "(no gist — digest was empty)"
    if not gist.endswith((".", "!", "?", ")")):
        gist += "."
    tags = ", ".join(final["tags"]) or "none"
    _append(idx, f"- [{dest.name}]({sidecar.name}) — {gist} tier: thin. "
                 f"tags: [{tags}]. dropped: {today()}.\n")

    append_log(root, "library", dest.name,
               [f"archived to `library/{dest.name}` (sidecar `{sidecar.name}`)",
                f"gist: {gist}", f"tags: {tags}"])
    touched = []
    for t in final["tags"]:
        if _dock_history(root, t, f"{today()} — `library/{dest.name}` docked to library ({gist})"):
            touched.append(t)
    # the draft sidecar lived in inbox next to the original name — retire it
    old_draft = p["inbox"] / (item.name + DIGEST_SUFFIX)
    if old_draft.exists():
        _try_unlink(old_draft)
    return {"dest": dest, "sidecar": sidecar, "slug": sidecar.name[:-len(DIGEST_SUFFIX)],
            "cards": touched}


def file_to_raw(item: Path, root: Path) -> dict:
    """DOCK.md step 3a — move to raw/; the INGEST workflow (agent work) takes over.
    The draft digest is printed by the caller to seed the source page, then removed."""
    p = P(root)
    digest = load_draft(item)
    dest = _unique_dest(p["raw"], item.name)
    item.replace(dest)
    old_draft = p["inbox"] / (item.name + DIGEST_SUFFIX)
    if old_draft.exists():
        _try_unlink(old_draft)
    return {"dest": dest, "digest": digest}


# ------------------------------------------- reactivation / enrich / promote

def find_sidecar(slug: str, root: Path):
    p = P(root)["library"] / f"{slug}{DIGEST_SUFFIX}"
    return p if p.exists() else None


def sidecar_for_file(filename: str, root: Path):
    """Locate the sidecar whose `source:` matches a library filename."""
    lib = P(root)["library"]
    for sc in lib.glob(f"*{DIGEST_SUFFIX}"):
        d = parse_digest(sc.read_text(encoding="utf-8"))
        if d.get("source", "").endswith("/" + filename) or d.get("source") == f"library/{filename}":
            return sc, d
    return None, None


def check_promotion(d: dict, root: Path):
    """Breadth (2+ registry cards) OR frequency (3+ reactivations, same card).
    A rich digest is a prerequisite — promotion runs INGEST against the cached
    claims (DOCK.md), so a thin item must be enriched first."""
    if d.get("promoted"):
        return False, "already promoted"
    slugs = set(registry_slugs(root))
    if d.get("tier") != "rich":
        triggers_ = [r.get("trigger", "") for r in d.get("reactivations", [])]
        cards_ = ({t for t in d.get("tags", []) if t in slugs}
                  | {t for t in triggers_ if t in slugs})
        counts_ = Counter(t for t in triggers_ if t in slugs)
        would = (len(cards_) >= 2 or any(n >= 3 for n in counts_.values()))
        hint = " — bar already met, promote right after enriching" if would else ""
        return False, f"tier still thin — enrich first (rich digest is the promotion prerequisite){hint}"
    triggers = [r.get("trigger", "") for r in d.get("reactivations", [])]
    cards = ({t for t in d.get("tags", []) if t in slugs}
             | {t for t in triggers if t in slugs})
    if len(cards) >= 2:
        return True, f"breadth: touches {len(cards)} registry cards ({', '.join(sorted(cards))})"
    counts = Counter(t for t in triggers if t in slugs)
    for card, n in counts.items():
        if n >= 3:
            return True, f"frequency: {n} reactivations by [{card}]"
    return False, (f"below bar — cards: {sorted(cards) or 'none'}, "
                   f"max same-card reactivations: {max(counts.values()) if counts else 0}")


def reactivate(slug: str, trigger: str, note: str, root: Path):
    sc = find_sidecar(slug, root)
    if sc is None:
        raise FileNotFoundError(f"no sidecar library/{slug}{DIGEST_SUFFIX}")
    d = parse_digest(sc.read_text(encoding="utf-8"))
    d["reactivations"].append({"date": today(), "trigger": trigger, "note": note or ""})
    sc.write_text(emit_digest(d), encoding="utf-8")
    append_log(root, "reactivation", d.get("source", slug),
               [f"trigger: {trigger}" + (f" — {note}" if note else "")])
    if trigger in registry_slugs(root):
        _dock_history(root, trigger,
                      f"{today()} — reactivated `{d.get('source', slug)}`"
                      + (f" ({note})" if note else ""))
    return d, check_promotion(d, root)


def enrich(slug: str, claims: list, add_tags: list, root: Path):
    sc = find_sidecar(slug, root)
    if sc is None:
        raise FileNotFoundError(f"no sidecar library/{slug}{DIGEST_SUFFIX}")
    d = parse_digest(sc.read_text(encoding="utf-8"))
    d["claims"] = list(d.get("claims", [])) + [c for c in claims if c.strip()]
    known = set(registry_slugs(root))
    for t in add_tags:
        t = t.strip().lower()
        if t and t in known and t not in d["tags"]:
            d["tags"].append(t)
    d["tier"] = "rich"
    sc.write_text(emit_digest(d), encoding="utf-8")
    # keep the catalog line's tier honest
    idx = P(root)["lib_index"]
    if idx.exists():
        text = idx.read_text(encoding="utf-8")
        lines = []
        for l in text.splitlines():
            if f"({sc.name})" in l:
                l = l.replace("tier: thin.", "tier: rich.")
            lines.append(l)
        idx.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d, check_promotion(d, root)


def promote(slug: str, root: Path, force: bool = False):
    """Mechanics of consolidation: library file -> raw/, sidecar retired,
    catalog line removed, promotion logged. The INGEST workflow itself is agent
    work — the caller prints the to-do."""
    p = P(root)
    sc = find_sidecar(slug, root)
    if sc is None:
        raise FileNotFoundError(f"no sidecar library/{slug}{DIGEST_SUFFIX}")
    d = parse_digest(sc.read_text(encoding="utf-8"))
    ok, reason = check_promotion(d, root)
    if not ok and not force:
        return None, reason
    src_name = d.get("source", "").rsplit("/", 1)[-1]
    src = p["library"] / src_name
    if not src.exists():
        raise FileNotFoundError(f"library file missing: {src}")
    dest = _unique_dest(p["raw"], src_name)
    src.replace(dest)
    _try_unlink(sc)
    idx = p["lib_index"]
    if idx.exists():
        lines = [l for l in idx.read_text(encoding="utf-8").splitlines()
                 if f"({sc.name})" not in l]
        idx.write_text("\n".join(lines) + "\n", encoding="utf-8")
    append_log(root, "promotion", src_name,
               [f"consolidated: `library/{src_name}` -> `raw/{dest.name}`",
                f"reason: {reason if ok else 'FORCED — ' + reason}",
                "INGEST workflow pending — create wiki/sources page, cross-link, index."])
    for t in d.get("tags", []):
        _dock_history(root, t, f"{today()} — `{src_name}` promoted library -> raw/+wiki")
    return {"dest": dest, "digest": d, "reason": reason if ok else f"forced ({reason})"}, None
