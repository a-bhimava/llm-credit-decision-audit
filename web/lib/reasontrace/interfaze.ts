import type { DocumentId } from "@/lib/reasontrace/demo";

type Output = Record<string, unknown> & { applicant_name: string };

const documentSpecs: Record<DocumentId, { properties: Record<string, unknown>; prompt: string }> = {
  "pay-stub": {
    properties: { applicant_name: { type: "string" }, annual_income_cents: { type: "integer" }, annual_income_quote: { type: "string" } },
    prompt: "Read only this fictional pay statement. Return the employee name, annualized gross income in integer cents, and an exact short quote containing that annualized income. Do not substitute net pay.",
  },
  "bank-statement": {
    properties: { applicant_name: { type: "string" }, statement_period: { type: "string" }, payroll_deposit_quote: { type: "string" } },
    prompt: "Read only this fictional bank statement. Return the account holder name, statement period, and an exact short quote showing the payroll deposit. The deposit is not annual gross income.",
  },
  "credit-report": {
    properties: { applicant_name: { type: "string" }, credit_score: { type: "integer" }, monthly_debt_cents: { type: "integer" }, credit_score_quote: { type: "string" }, monthly_debt_quote: { type: "string" } },
    prompt: "Read only this fictional credit summary. Return the consumer name, credit score, monthly debt payments in integer cents, and exact short quotes for each figure.",
  },
};

export async function extractDocument(id: DocumentId, image: Buffer, key: string): Promise<Output> {
  const spec = documentSpecs[id];
  let response: Response | null = null;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    response = await fetch("https://api.interfaze.ai/v1/chat/completions", {
      method: "POST",
      headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json", "x-interfaze-zdr": "true" },
      signal: AbortSignal.timeout(45_000),
      body: JSON.stringify({
        model: "interfaze",
        messages: [{ role: "user", content: [
          { type: "text", text: spec.prompt },
          { type: "image_url", image_url: { url: `data:image/png;base64,${image.toString("base64")}` } },
        ] }],
        response_format: { type: "json_schema", json_schema: {
          name: `reasontrace_${id.replaceAll("-", "_")}`, strict: true,
          schema: { type: "object", properties: spec.properties, required: Object.keys(spec.properties), additionalProperties: false },
        } },
      }),
    });
    if (response.ok || ![429, 502, 503, 504].includes(response.status) || attempt === 2) break;
    await new Promise(resolve => setTimeout(resolve, 250 * 2 ** attempt));
  }
  if (!response?.ok) throw new Error(`Interfaze returned ${response?.status ?? "no response"} for ${id}`);
  const body = await response.json();
  const content = body?.choices?.[0]?.message?.content;
  if (typeof content !== "string") throw new Error(`Interfaze returned no structured result for ${id}`);
  const parsed = JSON.parse(content);
  const output = parsed?.output ?? parsed;
  if (!output || typeof output !== "object" || typeof output.applicant_name !== "string" || !output.applicant_name.trim()) {
    throw new Error(`Interfaze returned an incomplete applicant name for ${id}`);
  }
  for (const [name, property] of Object.entries(spec.properties)) {
    const value = output[name];
    if ((property as { type: string }).type === "integer" && !Number.isSafeInteger(value)) {
      throw new Error(`Interfaze returned an invalid ${name} for ${id}`);
    }
    if ((property as { type: string }).type === "string" && (typeof value !== "string" || !value.trim())) {
      throw new Error(`Interfaze returned an invalid ${name} for ${id}`);
    }
  }
  return output as Output;
}
