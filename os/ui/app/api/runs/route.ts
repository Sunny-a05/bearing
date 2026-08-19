import { NextRequest, NextResponse } from "next/server";
import { runRecords, runsSummary } from "@/lib/os";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const days = Number(req.nextUrl.searchParams.get("days") || 7);
  const n = Number(req.nextUrl.searchParams.get("n") || 200);
  const records = runRecords();
  return NextResponse.json({ records: records.slice(-n).reverse(), summary: runsSummary(days) });
}
