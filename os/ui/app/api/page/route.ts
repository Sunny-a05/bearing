import { NextRequest, NextResponse } from "next/server";
import { readText } from "@/lib/os";
import { renderMarkdown } from "@/lib/md";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const p = req.nextUrl.searchParams.get("p") || "";
  try {
    const content = readText(p);
    if (content === null) return NextResponse.json({ error: "not found" }, { status: 404 });
    return NextResponse.json({ path: p, content, html: p.endsWith(".md") ? renderMarkdown(content) : null });
  } catch (e: any) {
    return NextResponse.json({ error: e.message }, { status: 400 });
  }
}
