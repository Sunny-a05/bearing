import { NextResponse } from "next/server";
import { dockItems } from "@/lib/os";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ items: dockItems() });
}
