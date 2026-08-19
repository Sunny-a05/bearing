#!/usr/bin/env python3
"""librarian.py — ranked retrieval over wiki/. Stdlib only.

BM25 over whole pages -> tag-overlap boost -> [[wiki-link]] graph expansion of the
top hits -> best-matching section returned as the excerpt. The graph expansion is
the part a plain grep cannot do: your curated links encode relatedness that term
frequency never sees.

Ported out of the MCP frontend on 2026-08-19 when that frontend was cut — the
retrieval was worth keeping, the transport was not. Surface: `agentos.py query`
and `agentos.py search`.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIKI = ROOT / "wiki"


def set_root(root: Path) -> None:
    """Point the librarian at a different repo (the CLI's --root override)."""
    global ROOT, WIKI
    ROOT = Path(root).resolve()
    WIKI = ROOT / "wiki"
    _CACHE.clear()
    _CACHE["sig"] = None


_TOKEN = re.compile(r"[a-z0-9]+")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_LINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
_STOP = frozenset(
    "the a an and or of to in is are be it its on for with as by at from this that "
    "these those not no i you we they he she but if then so than into out over under "
    "can will would should could may might do does did has have had was were which "
    "what when where who why how about your our their my me us".split()
)

# In-memory index, rebuilt only when the wiki changes (mtime/count signature).
_CACHE: dict = {"sig": None}


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"(cannot read {p.name}: {e})"


def _tok(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if len(t) > 1 and t not in _STOP]


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[text.find("\n", end + 1) + 1:]
    return text


def _parse_fm(text: str) -> tuple[str, set[str]]:
    """(type, tags) from YAML frontmatter — a light regex read, no yaml dep."""
    ptype, tags = "", set()
    if not text.startswith("---"):
        return ptype, tags
    block = text[3:text.find("\n---", 3)] if "\n---" in text else ""
    for line in block.splitlines():
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k == "type":
            ptype = v
        elif k == "tags":
            tags = {t.strip().lower() for t in v.strip("[]").split(",") if t.strip()}
    return ptype, tags


def _frontmatter_dict(path: Path) -> dict:
    """Full frontmatter as a flat dict (registry cards: project/domain/status/…)."""
    meta, text = {}, _read(path)
    if not text.startswith("---") or "\n---" not in text:
        return meta
    for line in text[3:text.find("\n---", 3)].splitlines():
        if ":" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    return meta


def _title(text: str, slug: str) -> str:
    for line in _strip_frontmatter(text).splitlines():
        m = _HEADING.match(line)
        if m and len(m.group(1)) == 1:
            return m.group(2).strip()
    return slug


def _sections(text: str) -> list[tuple[str, str]]:
    """Split a page body into (heading, body) chunks by markdown heading."""
    body = _strip_frontmatter(text)
    out, head, buf = [], "(top)", []
    for line in body.splitlines():
        m = _HEADING.match(line)
        if m:
            if buf:
                out.append((head, "\n".join(buf).strip()))
            head, buf = m.group(2).strip(), []
        else:
            buf.append(line)
    if buf:
        out.append((head, "\n".join(buf).strip()))
    return [(h, b) for h, b in out if b] or [("(top)", body.strip())]


def _ensure_index() -> tuple[list[dict], dict, float]:
    """Build (docs, idf, avgdl); cache until the wiki changes."""
    paths = sorted(WIKI.glob("**/*.md"))
    sig = (len(paths), max((p.stat().st_mtime for p in paths), default=0))
    if _CACHE.get("sig") == sig:
        return _CACHE["docs"], _CACHE["idf"], _CACHE["avgdl"]

    docs = []
    for p in paths:
        text = _read(p)
        ptype, tags = _parse_fm(text)
        toks = _tok(text)
        docs.append({
            "slug": p.stem,
            "rel": p.relative_to(ROOT).as_posix(),
            "title": _title(text, p.stem),
            "type": ptype,
            "tags": tags,
            "links": {m.split("/")[-1].lower() for m in _LINK.findall(text)},
            "tf": Counter(toks),
            "dl": len(toks),
        })
    N = len(docs) or 1
    df: Counter = Counter()
    for d in docs:
        df.update(d["tf"].keys())
    idf = {t: math.log(1 + (N - n + 0.5) / (n + 0.5)) for t, n in df.items()}
    avgdl = (sum(d["dl"] for d in docs) / N) or 1.0
    _CACHE.update(sig=sig, docs=docs, idf=idf, avgdl=avgdl)
    return docs, idf, avgdl


def _bm25(q: list[str], d: dict, idf: dict, avgdl: float, k1=1.5, b=0.75) -> float:
    score = 0.0
    for t in q:
        tf = d["tf"].get(t, 0)
        if not tf:
            continue
        denom = tf + k1 * (1 - b + b * d["dl"] / avgdl)
        score += idf.get(t, 0.0) * (tf * (k1 + 1)) / denom
    return score


def _best_section(slug: str, q: list[str]) -> tuple[str, str]:
    hits = list(WIKI.glob(f"**/{slug}.md"))
    if not hits:
        return "(top)", ""
    qs = set(q)
    best, best_score = ("(top)", ""), -1.0
    for head, body in _sections(_read(hits[0])):
        s = sum(1 for t in _tok(body) if t in qs)
        if s > best_score:
            best, best_score = (head, body), s
    head, body = best
    return head, re.sub(r"\s+", " ", body)[:240]


# ============================================================ tools

def wiki_search(query: str, kind: str = "") -> str:
    """Literal lookup: pages whose filename or text contains `query`.
    Optional `kind` filters by frontmatter type (entity|concept|skill|stack|
    pattern|context|source|prompt|template). Use wiki_query for ranked,
    answer-oriented retrieval."""
    q, out = query.lower(), []
    for p in WIKI.glob("**/*.md"):
        text = _read(p)
        if kind and f"type: {kind}" not in text[:400]:
            continue
        if q in p.stem.lower() or q in text.lower():
            line = next((l for l in text.splitlines() if q in l.lower()), "")
            out.append(f"[[{p.stem}]]  {p.relative_to(ROOT).as_posix()}\n    {line.strip()[:120]}")
    return "\n".join(out[:25]) or f"no literal match for '{query}'"


def wiki_query(question: str, kind: str = "", k: int = 6) -> str:
    """Ranked retrieval for a question. Pipeline: BM25 over (title+tags+body)
    -> +tag-overlap boost -> [[wiki-link]] graph expansion of the top hits ->
    best section per page. Returns citations + snippets (NOT full pages) so the
    agent then opens only the pages it needs. `kind` restricts the
    keyword candidates to one frontmatter type; graph neighbours are unrestricted."""
    docs, idf, avgdl = _ensure_index()
    q = _tok(question)
    if not q:
        return "empty query"
    by_slug = {d["slug"]: d for d in docs}

    scores: dict[str, float] = {}
    via: dict[str, str] = {}
    for d in docs:
        if kind and d["type"] != kind:
            continue
        s = _bm25(q, d, idf, avgdl)
        s += 0.8 * len(d["tags"] & set(q))          # structural boost: tag overlap
        if s > 0:
            scores[d["slug"]] = s

    # Graph expansion: neighbours of the top 3 hits surface even with no keyword
    # match — your curated [[links]] encode relatedness that BM25 can't see.
    for parent in sorted(scores, key=scores.get, reverse=True)[:3]:
        pscore = scores[parent]
        for tgt in by_slug[parent]["links"]:
            if tgt in by_slug and scores.get(tgt, 0) < 0.4 * pscore:
                scores[tgt] = 0.4 * pscore
                via.setdefault(tgt, parent)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
    if not ranked:
        return f"no matches for '{question}'" + (f" (kind={kind})" if kind else "")

    lines = [f'{len(ranked)} chunk(s) for "{question}"  (BM25 + tag boost + graph expansion)\n']
    for slug, score in ranked:
        d = by_slug[slug]
        head, snip = _best_section(slug, q)
        prov = f"  <- linked from [[{via[slug]}]]" if slug in via else ""
        lines.append(f"[[{slug}]] §{head}  ({d['type'] or '?'})  score {score:.1f}{prov}")
        lines.append(f"    {snip}")
    lines.append("\nOpen a full page at the path shown beside each hit.")
    return "\n".join(lines)


# ============================================================ OS core bridge (M2)
# The wiki layer (M1) reads files only. This layer wraps the OS control plane by
# importing the CLI modules from os/cli/ — LAZILY, so M1 never depends on them
# (same detachability, one level down). They're stdlib-only; we import, never fork.
