"use client";

import { useState, type FormEvent } from "react";
import { createClient } from "@/lib/supabase/client";

export function ReasonTraceLogin() {
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function signIn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const { error } = await createClient().auth.signInWithOtp({
        email,
        options: {
          emailRedirectTo: `${window.location.origin}/reasontrace/auth/callback`,
          shouldCreateUser: true,
        },
      });
      if (error) throw error;
      setMessage("Check your email for the sign-in link. You can close this tab and return after opening it.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Sign-in could not start.");
    } finally {
      setBusy(false);
    }
  }

  return <main className="rt-login">
    <span>ReasonTrace · synthetic interview case</span>
    <h1>Sign in to review the case</h1>
    <p>The application packet, reviewed observations, and audit runs are scoped to your Supabase account.</p>
    <form onSubmit={signIn}>
      <label htmlFor="rt-email">Email address</label>
      <input id="rt-email" type="email" autoComplete="email" required value={email}
        onChange={event => setEmail(event.target.value)} />
      <button type="submit" disabled={busy}>{busy ? "Sending…" : "Send sign-in link"}</button>
    </form>
    {message && <p role="status">{message}</p>}
  </main>;
}
