import { NextResponse } from "next/server";
import { libraryItems } from "@/lib/os";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({ items: libraryItems() });
}
