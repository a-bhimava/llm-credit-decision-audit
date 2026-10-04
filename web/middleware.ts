import { type NextRequest } from "next/server";
import { updateSession } from "@/lib/supabase/session";

export async function middleware(request: NextRequest) {
  return updateSession(request);
}

export const config = {
  matcher: ["/reasontrace/:path*", "/api/reasontrace/:path*"],
};
