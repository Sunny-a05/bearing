import { NextResponse } from "next/server";
import { buildGraph } from "@/lib/graph";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json(buildGraph());
}
