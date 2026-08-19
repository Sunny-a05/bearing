import { NextResponse } from "next/server";
import { probeAgents } from "@/lib/exec";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ agents: await probeAgents() });
}
