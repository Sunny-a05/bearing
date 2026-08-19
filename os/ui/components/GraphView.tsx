"use client";
// Obsidian-style knowledge-graph canvas. Hand-rolled force simulation —
// zero graph dependencies, so it still builds in 2029. O(n²) repulsion is
// fine at wiki scale (~100–600 nodes).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import LibrarianBar from "./LibrarianBar";

type GNode = { id: string; label: string; type: string; deg: number; status?: string };
type GLink = { source: string; target: string };
type Graph = { nodes: GNode[]; links: GLink[] };

// Hand-rolled fuzzy match (subsequence) — keeps os/ui's three-runtime-deps
// durability contract: no Fuse.js, same reasoning that hand-rolls the force
// sim below. Both args must be lowercased by the caller.
function fuzzyMatch(q: string, s: string): boolean {
  if (!q) return false;
  let i = 0;
  for (let j = 0; j < s.length && i < q.length; j++) {
    if (s[j] === q[i]) i++;
  }
  return i === q.length;
}

// Pull [[wikilinks]] out of a single frontmatter field (related:/sources:) of
// a page's raw markdown. Returns lowercased stems (last path segment), which
// resolve to node ids the same way lib/graph.ts resolves them.
function fmFieldLinks(content: string, field: string): string[] {
  const m = content.match(/^---\s*\n([\s\S]*?)\n---/);
  if (!m) return [];
  const line = m[1]
    .split("\n")
    .find((l) => l.trimStart().toLowerCase().startsWith(field + ":"));
  if (!line) return [];
  const out: string[] = [];
  const re = /\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]/g;
  let x: RegExpExecArray | null;
  while ((x = re.exec(line))) out.push(x[1].split("/").pop()!.trim().toLowerCase());
  return out;
}

export const TYPE_COLORS: Record<string, string> = {
  entity: "#d4a853",
  concept: "#7aa2f7",
  skill: "#9ece6a",
  prompt: "#bb9af7",
  template: "#e0af68",
  stack: "#2ac3de",
  pattern: "#f7768e",
  context: "#c8b6ff",
  source: "#8a877d",
  registry: "#ff9e64",
  library: "#5f6996",
  meta: "#565f89",
  note: "#565f89",
};

type Sim = {
  x: Float64Array; y: Float64Array; vx: Float64Array; vy: Float64Array;
  fixed: Int8Array;
  idx: Map<string, number>;
  edges: [number, number][];
  adj: Map<number, Set<number>>;
  alpha: number;
};

export default function GraphView() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [selected, setSelected] = useState<GNode | null>(null);
  const [preview, setPreview] = useState<{ html: string | null; content: string } | null>(null);
  const [search, setSearch] = useState("");
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [hideOrphans, setHideOrphans] = useState(false);
  const simRef = useRef<Sim | null>(null);
  const viewRef = useRef({ ox: 0, oy: 0, scale: 1 });
  const hoverRef = useRef<number>(-1);
  const searchRef = useRef("");
  const hiddenRef = useRef<Set<string>>(new Set());
  const hideOrphansRef = useRef(false);
  const selectedRef = useRef<string | null>(null);
  // draw only when something changed — a cooled graph costs zero CPU
  const dirtyRef = useRef(true);

  useEffect(() => {
    fetch("/api/graph").then((r) => r.json()).then(setGraph);
  }, []);

  // ---- build simulation when data arrives
  useEffect(() => {
    if (!graph) return;
    const n = graph.nodes.length;
    const idx = new Map(graph.nodes.map((nd, i) => [nd.id, i]));
    const sim: Sim = {
      x: new Float64Array(n), y: new Float64Array(n),
      vx: new Float64Array(n), vy: new Float64Array(n),
      fixed: new Int8Array(n),
      idx,
      edges: graph.links
        .map((l) => [idx.get(l.source)!, idx.get(l.target)!] as [number, number])
        .filter((e) => e[0] !== undefined && e[1] !== undefined),
      adj: new Map(),
      alpha: 1,
    };
    // seed positions: type-clustered ring + jitter, keeps first frames coherent
    const types = [...new Set(graph.nodes.map((d) => d.type))];
    graph.nodes.forEach((nd, i) => {
      const a = (types.indexOf(nd.type) / types.length) * Math.PI * 2;
      const r = 220 + Math.random() * 160;
      sim.x[i] = Math.cos(a) * r + (Math.random() - 0.5) * 120;
      sim.y[i] = Math.sin(a) * r + (Math.random() - 0.5) * 120;
    });
    for (const [a, b] of sim.edges) {
      if (!sim.adj.has(a)) sim.adj.set(a, new Set());
      if (!sim.adj.has(b)) sim.adj.set(b, new Set());
      sim.adj.get(a)!.add(b);
      sim.adj.get(b)!.add(a);
    }
    simRef.current = sim;
  }, [graph]);

  useEffect(() => { searchRef.current = search.toLowerCase(); dirtyRef.current = true; }, [search]);
  useEffect(() => { hiddenRef.current = hiddenTypes; dirtyRef.current = true; }, [hiddenTypes]);
  useEffect(() => { hideOrphansRef.current = hideOrphans; dirtyRef.current = true; }, [hideOrphans]);
  useEffect(() => { selectedRef.current = selected?.id ?? null; dirtyRef.current = true; }, [selected]);

  // ---- render + physics loop
  useEffect(() => {
    if (!graph) return;
    const canvas = canvasRef.current!;
    const ctx = canvas.getContext("2d")!;
    let raf = 0;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.parentElement!.getBoundingClientRect();
      canvas.width = rect.width * dpr;
      canvas.height = rect.height * dpr;
      canvas.style.width = rect.width + "px";
      canvas.style.height = rect.height + "px";
      if (viewRef.current.ox === 0 && viewRef.current.oy === 0) {
        viewRef.current.ox = rect.width / 2;
        viewRef.current.oy = rect.height / 2;
      }
      dirtyRef.current = true;
    };
    resize();
    window.addEventListener("resize", resize);

    const step = () => {
      const sim = simRef.current;
      if (!sim) { raf = requestAnimationFrame(step); return; }
      const n = sim.x.length;
      const { alpha } = sim;
      const hot = alpha > 0.002;
      if (!hot && !dirtyRef.current) { raf = requestAnimationFrame(step); return; }
      dirtyRef.current = false;
      if (hot) {
        // repulsion (capped inverse-square)
        for (let i = 0; i < n; i++) {
          for (let j = i + 1; j < n; j++) {
            let dx = sim.x[i] - sim.x[j];
            let dy = sim.y[i] - sim.y[j];
            let d2 = dx * dx + dy * dy;
            if (d2 < 1) d2 = 1;
            if (d2 > 160_000) continue;
            const f = (1400 * alpha) / d2;
            const d = Math.sqrt(d2);
            dx /= d; dy /= d;
            sim.vx[i] += dx * f; sim.vy[i] += dy * f;
            sim.vx[j] -= dx * f; sim.vy[j] -= dy * f;
          }
        }
        // springs
        for (const [a, b] of sim.edges) {
          const dx = sim.x[b] - sim.x[a];
          const dy = sim.y[b] - sim.y[a];
          const d = Math.sqrt(dx * dx + dy * dy) || 1;
          const f = (d - 70) * 0.04 * alpha;
          sim.vx[a] += (dx / d) * f; sim.vy[a] += (dy / d) * f;
          sim.vx[b] -= (dx / d) * f; sim.vy[b] -= (dy / d) * f;
        }
        // gravity + integrate
        for (let i = 0; i < n; i++) {
          sim.vx[i] -= sim.x[i] * 0.004 * alpha;
          sim.vy[i] -= sim.y[i] * 0.004 * alpha;
          if (!sim.fixed[i]) {
            sim.vx[i] *= 0.85; sim.vy[i] *= 0.85;
            sim.x[i] += sim.vx[i]; sim.y[i] += sim.vy[i];
          } else {
            sim.vx[i] = 0; sim.vy[i] = 0;
          }
        }
        sim.alpha *= 0.995;
      }
      draw();
      raf = requestAnimationFrame(step);
    };

    const draw = () => {
      const sim = simRef.current!;
      const dpr = window.devicePixelRatio || 1;
      const { ox, oy, scale } = viewRef.current;
      const W = canvas.width / dpr, H = canvas.height / dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      ctx.save();
      ctx.translate(ox, oy);
      ctx.scale(scale, scale);

      const hover = hoverRef.current;
      const hidden = hiddenRef.current;
      const q = searchRef.current;
      const selId = selectedRef.current;
      const focus = hover >= 0 ? hover : selId ? sim.idx.get(selId) ?? -1 : -1;
      const neighbors = focus >= 0 ? sim.adj.get(focus) || new Set() : null;
      const hideOrph = hideOrphansRef.current;
      const visible = (i: number) =>
        !hidden.has(graph.nodes[i].type) && !(hideOrph && graph.nodes[i].deg === 0);

      // edges
      ctx.lineWidth = 1 / scale;
      for (const [a, b] of sim.edges) {
        if (!visible(a) || !visible(b)) continue;
        const lit = focus >= 0 && (a === focus || b === focus);
        ctx.strokeStyle = lit ? "rgba(212,168,83,0.55)" : focus >= 0 ? "rgba(255,255,255,0.03)" : "rgba(255,255,255,0.09)";
        ctx.beginPath();
        ctx.moveTo(sim.x[a], sim.y[a]);
        ctx.lineTo(sim.x[b], sim.y[b]);
        ctx.stroke();
      }

      // nodes
      for (let i = 0; i < sim.x.length; i++) {
        if (!visible(i)) continue;
        const nd = graph.nodes[i];
        const r = 3 + Math.sqrt(nd.deg + 1) * 1.7;
        const isFocus = i === focus;
        const isNb = neighbors?.has(i) ?? false;
        const matches = q ? fuzzyMatch(q, nd.label.toLowerCase()) : false;
        let alpha = 1;
        if (focus >= 0) alpha = isFocus || isNb ? 1 : 0.12;
        else if (q) alpha = matches ? 1 : 0.1;
        ctx.globalAlpha = alpha;
        ctx.fillStyle = TYPE_COLORS[nd.type] || TYPE_COLORS.note;
        if (isFocus || matches) {
          ctx.shadowColor = ctx.fillStyle;
          ctx.shadowBlur = 14;
        }
        ctx.beginPath();
        ctx.arc(sim.x[i], sim.y[i], r, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
        // labels: focused / matched always; otherwise when zoomed in
        if (isFocus || isNb || matches || scale > 1.35) {
          ctx.font = `${11 / scale}px ui-sans-serif, system-ui`;
          ctx.fillStyle = isFocus ? "#f2f0e9" : "rgba(242,240,233,0.72)";
          ctx.textAlign = "center";
          ctx.fillText(nd.label, sim.x[i], sim.y[i] + r + 12 / scale);
        }
        ctx.globalAlpha = 1;
      }
      ctx.restore();
    };

    // ---- interactions
    const toWorld = (cx: number, cy: number) => {
      const { ox, oy, scale } = viewRef.current;
      const rect = canvas.getBoundingClientRect();
      return { x: (cx - rect.left - ox) / scale, y: (cy - rect.top - oy) / scale };
    };
    const pick = (cx: number, cy: number): number => {
      const sim = simRef.current!;
      const { x, y } = toWorld(cx, cy);
      let best = -1, bestD = 12 / viewRef.current.scale + 4;
      for (let i = 0; i < sim.x.length; i++) {
        if (hiddenRef.current.has(graph.nodes[i].type)) continue;
        if (hideOrphansRef.current && graph.nodes[i].deg === 0) continue;
        const d = Math.hypot(sim.x[i] - x, sim.y[i] - y);
        if (d < bestD) { bestD = d; best = i; }
      }
      return best;
    };

    let dragNode = -1, panning = false, lastX = 0, lastY = 0, moved = false;
    const down = (e: PointerEvent) => {
      moved = false;
      lastX = e.clientX; lastY = e.clientY;
      dragNode = pick(e.clientX, e.clientY);
      if (dragNode >= 0) {
        simRef.current!.fixed[dragNode] = 1;
        simRef.current!.alpha = Math.max(simRef.current!.alpha, 0.3);
      } else panning = true;
      canvas.setPointerCapture(e.pointerId);
    };
    const move = (e: PointerEvent) => {
      if (dragNode >= 0) {
        const { x, y } = toWorld(e.clientX, e.clientY);
        simRef.current!.x[dragNode] = x;
        simRef.current!.y[dragNode] = y;
        simRef.current!.alpha = Math.max(simRef.current!.alpha, 0.25);
        moved = true;
      } else if (panning) {
        viewRef.current.ox += e.clientX - lastX;
        viewRef.current.oy += e.clientY - lastY;
        lastX = e.clientX; lastY = e.clientY;
        moved = true;
        dirtyRef.current = true;
      } else {
        const h = pick(e.clientX, e.clientY);
        if (h !== hoverRef.current) dirtyRef.current = true;
        hoverRef.current = h;
        canvas.style.cursor = h >= 0 ? "pointer" : "grab";
      }
    };
    const up = (e: PointerEvent) => {
      if (dragNode >= 0) simRef.current!.fixed[dragNode] = 0;
      if (!moved) {
        const i = pick(e.clientX, e.clientY);
        selectNode(i >= 0 ? graph.nodes[i] : null);
      }
      dragNode = -1; panning = false;
    };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left, my = e.clientY - rect.top;
      const v = viewRef.current;
      const k = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const ns = Math.min(6, Math.max(0.15, v.scale * k));
      // zoom toward cursor
      v.ox = mx - ((mx - v.ox) / v.scale) * ns;
      v.oy = my - ((my - v.oy) / v.scale) * ns;
      v.scale = ns;
      dirtyRef.current = true;
    };

    canvas.addEventListener("pointerdown", down);
    canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("wheel", wheel, { passive: false });
    raf = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
      canvas.removeEventListener("pointerdown", down);
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerup", up);
      canvas.removeEventListener("wheel", wheel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph]);

  const selectNode = useCallback((nd: GNode | null) => {
    setSelected(nd);
    setPreview(null);
    if (nd) {
      fetch(`/api/page?p=${encodeURIComponent(nd.id)}`)
        .then((r) => r.json())
        .then((d) => setPreview({ html: d.html, content: d.content || "" }))
        .catch(() => {});
    }
  }, []);

  const typesInUse = useMemo(() => {
    if (!graph) return [];
    const counts = new Map<string, number>();
    for (const n of graph.nodes) counts.set(n.type, (counts.get(n.type) || 0) + 1);
    return [...counts.entries()].sort((a, b) => b[1] - a[1]);
  }, [graph]);

  const orphanCount = useMemo(
    () => (graph ? graph.nodes.filter((n) => n.deg === 0).length : 0),
    [graph]
  );

  const nodeById = useMemo(() => {
    const m = new Map<string, GNode>();
    if (graph) for (const n of graph.nodes) m.set(n.id, n);
    return m;
  }, [graph]);

  // stem -> id, wiki/ pages winning resolution (mirrors lib/graph.ts) — for
  // resolving related:/sources: frontmatter wikilinks to graph nodes.
  const byStem = useMemo(() => {
    const m = new Map<string, string>();
    if (graph)
      for (const n of graph.nodes) {
        const stem = n.label.toLowerCase();
        const cur = m.get(stem);
        if (!cur || (!cur.startsWith("wiki/") && n.id.startsWith("wiki/"))) m.set(stem, n.id);
      }
    return m;
  }, [graph]);

  // Connections for the detail panel: Outbound/Inbound from the graph edges we
  // already fetched, Related/Sources from the selected page's frontmatter.
  // Curated frontmatter links are pulled out of Outbound so they don't double.
  const connections = useMemo(() => {
    if (!selected || !graph) return null;
    const id = selected.id;
    const outIds = new Set<string>();
    const inIds = new Set<string>();
    for (const l of graph.links) {
      if (l.source === id) outIds.add(l.target);
      if (l.target === id) inIds.add(l.source);
    }
    const relIds = new Set<string>();
    const srcIds = new Set<string>();
    if (preview?.content) {
      for (const stem of fmFieldLinks(preview.content, "related")) {
        const t = byStem.get(stem);
        if (t && t !== id) relIds.add(t);
      }
      for (const stem of fmFieldLinks(preview.content, "sources")) {
        const t = byStem.get(stem);
        if (t && t !== id) srcIds.add(t);
      }
    }
    for (const t of relIds) outIds.delete(t);
    for (const t of srcIds) outIds.delete(t);
    const toItems = (ids: Set<string>) =>
      [...ids].map((i) => nodeById.get(i)).filter(Boolean) as GNode[];
    const sections = [
      { label: "Outbound", items: toItems(outIds) },
      { label: "Inbound", items: toItems(inIds) },
      { label: "Related", items: toItems(relIds) },
      { label: "Sources", items: toItems(srcIds) },
    ];
    return sections.some((s) => s.items.length) ? sections : null;
  }, [selected, graph, preview, byStem, nodeById]);

  return (
    <div className="relative h-full w-full overflow-hidden bg-deep">
      <canvas ref={canvasRef} className="h-full w-full" style={{ cursor: "grab" }} />

      {/* top bar */}
      <div className="absolute left-4 top-4 flex items-center gap-2">
        <input
          className="input w-64 bg-panel/90 backdrop-blur"
          placeholder="Search pages…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {graph && (
          <span className="rounded-lg bg-panel/90 px-2.5 py-1.5 text-xs text-faint backdrop-blur">
            {graph.nodes.length} pages · {graph.links.length} links
          </span>
        )}
      </div>

      {/* legend */}
      <div className="absolute bottom-4 left-4 flex max-w-[60%] flex-wrap gap-1.5">
        {typesInUse.map(([t, count]) => {
          const off = hiddenTypes.has(t);
          return (
            <button
              key={t}
              onClick={() => {
                const next = new Set(hiddenTypes);
                off ? next.delete(t) : next.add(t);
                setHiddenTypes(next);
              }}
              className={`chip gap-1.5 border border-line bg-panel/90 backdrop-blur transition-opacity ${off ? "opacity-35" : ""}`}
            >
              <span className="h-2 w-2 rounded-full" style={{ background: TYPE_COLORS[t] || TYPE_COLORS.note }} />
              <span className="text-muted">{t}</span>
              <span className="text-faint">{count}</span>
            </button>
          );
        })}
        {orphanCount > 0 && (
          <button
            onClick={() => setHideOrphans((v) => !v)}
            title="Orphans are pages with no connections"
            className={`chip gap-1.5 border border-line bg-panel/90 backdrop-blur transition-opacity ${hideOrphans ? "opacity-35" : ""}`}
          >
            <span className="text-muted">{hideOrphans ? "orphans hidden" : "orphans"}</span>
            <span className="text-faint">{orphanCount}</span>
          </button>
        )}
      </div>

      {/* detail panel */}
      {selected && (
        <div className="fade-up absolute bottom-4 right-4 top-4 flex w-[420px] flex-col rounded-xl border border-line bg-panel/95 shadow-2xl backdrop-blur">
          <div className="flex items-start justify-between gap-2 border-b border-line px-4 py-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: TYPE_COLORS[selected.type] || TYPE_COLORS.note }} />
                <h3 className="truncate text-sm font-semibold">{selected.label}</h3>
              </div>
              <div className="mt-0.5 truncate font-mono text-[11px] text-faint">{selected.id}</div>
            </div>
            <button className="btn px-2 py-1 text-xs" onClick={() => selectNode(null)}>✕</button>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {!preview && <div className="py-6 text-center text-xs text-faint">loading…</div>}
            {preview?.html && <div className="md" dangerouslySetInnerHTML={{ __html: preview.html }} />}
            {preview && !preview.html && <pre className="console">{preview.content.slice(0, 4000)}</pre>}

            {connections && (
              <div className="mt-6 border-t border-line pt-4">
                <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-faint">
                  Connections
                </h4>
                <div className="space-y-3">
                  {connections.map(
                    (s) =>
                      s.items.length > 0 && (
                        <div key={s.label}>
                          <div className="mb-1 text-[10px] uppercase tracking-wider text-faint">
                            {s.label}
                          </div>
                          <ul className="flex flex-wrap gap-1.5">
                            {s.items.map((r) => (
                              <li key={`${s.label}-${r.id}`}>
                                <button
                                  onClick={() => selectNode(r)}
                                  className="flex items-center gap-1.5 rounded-md border border-line bg-deep px-2 py-1 text-xs text-muted transition hover:border-accent/60 hover:text-ink"
                                >
                                  <span
                                    className="h-1.5 w-1.5 shrink-0 rounded-full"
                                    style={{ background: TYPE_COLORS[r.type] || TYPE_COLORS.note }}
                                  />
                                  {r.label}
                                </button>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )
                  )}
                </div>
              </div>
            )}
          </div>

          <div className="border-t border-line px-4 py-3">
            <LibrarianBar
              pageId={selected.id}
              pageLabel={selected.label}
              pageContent={preview?.content ?? null}
            />
          </div>
        </div>
      )}
    </div>
  );
}
