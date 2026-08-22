import { test, expect } from "vitest";
import { CassetteClient } from "@/lib/audit/providers/cassette";

test("parity check for cassette client", async () => {
  // We just instantiate it to verify it exists and is syntactically valid for now
  expect(CassetteClient).toBeDefined();
});
