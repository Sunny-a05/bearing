// lib/md.ts — a deliberately tiny markdown -> HTML renderer for page previews.
// No dependency to rot; covers what the wiki actually uses (headings, lists,
// bold/italic/code, tables, wikilinks, blockquotes, fences, hr).

function esc(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function inline(s: string): string {
  let x = esc(s);
  x = x.replace(/`([^`]+)`/g, '<code>$1</code>');
  x = x.replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?\|([^\]]+)\]\]/g, '<span class="wikilink">$2</span>');
  x = x.replace(/\[\[([^\]|#]+)(?:#[^\]|]*)?\]\]/g, '<span class="wikilink">$1</span>');
  x = x.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  x = x.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  x = x.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  x = x.replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  return x;
}

export function renderMarkdown(src: string): string {
  // frontmatter -> chip block
  let fmHtml = "";
  const fm = src.match(/^---\s*\n([\s\S]*?)\n---\n?/);
  if (fm) {
    const rows = fm[1]
      .split("\n")
      .filter((l) => l.includes(":"))
      .map((l) => {
        const i = l.indexOf(":");
        return `<span class="fm-chip"><b>${esc(l.slice(0, i).trim())}</b> ${inline(l.slice(i + 1).trim())}</span>`;
      })
      .join("");
    fmHtml = `<div class="fm">${rows}</div>`;
    src = src.slice(fm[0].length);
  }

  const lines = src.split("\n");
  const out: string[] = [fmHtml];
  let inCode = false, inList = false, inQuote = false, inTable = false;
  const close = () => {
    if (inList) { out.push("</ul>"); inList = false; }
    if (inQuote) { out.push("</blockquote>"); inQuote = false; }
    if (inTable) { out.push("</table>"); inTable = false; }
  };
  for (const line of lines) {
    if (line.trimStart().startsWith("```")) {
      close();
      out.push(inCode ? "</code></pre>" : "<pre><code>");
      inCode = !inCode;
      continue;
    }
    if (inCode) { out.push(esc(line)); continue; }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) { close(); out.push(`<h${h[1].length}>${inline(h[2])}</h${h[1].length}>`); continue; }
    if (/^(-{3,}|\*{3,})\s*$/.test(line)) { close(); out.push("<hr/>"); continue; }
    if (line.startsWith("|")) {
      if (!inTable) { close(); out.push("<table>"); inTable = true; }
      if (/^\|[\s:|-]+\|?\s*$/.test(line)) continue; // separator row
      const cells = line.split("|").slice(1, -1).map((c) => `<td>${inline(c.trim())}</td>`).join("");
      out.push(`<tr>${cells}</tr>`);
      continue;
    } else if (inTable) { out.push("</table>"); inTable = false; }
    const li = line.match(/^\s*[-*]\s+(.*)$/);
    if (li) {
      if (!inList) { close(); out.push("<ul>"); inList = true; }
      out.push(`<li>${inline(li[1].replace(/^\[([ x])\]\s*/, (_, c) => (c === "x" ? "☑ " : "☐ ")))}</li>`);
      continue;
    } else if (inList && line.trim() === "") { out.push("</ul>"); inList = false; continue; }
    const q = line.match(/^>\s?(.*)$/);
    if (q) {
      if (!inQuote) { close(); out.push("<blockquote>"); inQuote = true; }
      out.push(inline(q[1]) + "<br/>");
      continue;
    } else if (inQuote) { out.push("</blockquote>"); inQuote = false; }
    if (line.trim() === "") { out.push(""); continue; }
    out.push(`<p>${inline(line)}</p>`);
  }
  close();
  if (inCode) out.push("</code></pre>");
  return out.join("\n");
}
