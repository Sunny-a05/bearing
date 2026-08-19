import { NextRequest, NextResponse } from "next/server";
import { runCli } from "@/lib/exec";

export const dynamic = "force-dynamic";

// The single mutation endpoint. Body: { args: string[] } — argv array passed
// to `python os/cli/agentos.py <args...>`. Allowlist enforced in lib/exec.ts.
export async function POST(req: NextRequest) {
  let body: any;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "bad json" }, { status: 400 });
  }
  const args = Array.isArray(body?.args) ? body.args.map(String) : null;
  if (!args) return NextResponse.json({ error: "args: string[] required" }, { status: 400 });
  const res = await runCli(args, Math.min(Number(body?.timeoutMs) || 600_000, 600_000));
  return NextResponse.json(res);
}
