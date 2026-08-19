import { NextRequest, NextResponse } from "next/server";
import fs from "node:fs";
import { safePath, sessionRows } from "@/lib/os";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const tail = req.nextUrl.searchParams.get("tail");
  if (tail) {
    const row = sessionRows().find((s) => s.sid === tail);
    if (!row) return NextResponse.json({ error: "no such session" }, { status: 404 });
    let log = "";
    try {
      log = fs.readFileSync(safePath(row.log), "utf-8");
    } catch {
      log = "(no log yet)";
    }
    // strip ANSI + braille spinners for readability
    log = log.replace(/\x1b\[[0-9;?]*[A-Za-z]/g, "").replace(/^[⠀-⣿\s]+$/gm, "").replace(/\r/g, "");
    return NextResponse.json({ sid: tail, log: log.split("\n").slice(-200).join("\n") });
  }
  return NextResponse.json({ sessions: sessionRows().reverse() });
}
