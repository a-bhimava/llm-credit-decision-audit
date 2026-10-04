import "server-only";
import { createClient } from "@supabase/supabase-js";

/** Only use after a normal user-session ownership check in a server route. */
export function createAdminClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.SUPABASE_SECRET_KEY;
  if (!url || !key) throw new Error("Server-side Supabase audit storage is not configured");
  return createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });
}
