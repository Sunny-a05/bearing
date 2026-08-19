import { NextResponse } from "next/server";
import { connectionsView } from "@/lib/exec";
import { runRecords } from "@/lib/os";

export const dynamic = "force-dynamic";

// The connections table plus the trail that explains it. `settings` records are
// the changes themselves (ticket 02); `skip` records are the consequence — a
// rung routing stepped over because its connection was off (ticket 03). Shown
// together because "why did this stop routing to gemini" is answered by the
// pair, not by either alone.
export async function GET() {
  const view = await connectionsView();
  const trail = runRecords()
    .filter((r) => r.kind === "settings" || r.kind === "skip")
    .slice(-25)
    .reverse();
  return NextResponse.json({ ...view, trail });
}
