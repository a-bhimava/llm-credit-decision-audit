import { ModelClient, ModelRequest, ModelResponse } from "./client";
import { getRuntimeConfiguration } from "@/lib/audit/runtime";
import { GoogleGenAI } from "@google/genai";
import { Usage, RequestedToolCall } from "@/lib/audit/records";

export const DEFAULT_MODEL = "gemini-2.5-flash-lite";

/**
 * Per-million-token pricing, in USD.
 * Extend this table when onboarding new models.
 * Prices: https://ai.google.dev/pricing
 */
const MODEL_PRICING: Record<string, { inputPerM: number; outputPerM: number; cachedPerM: number }> = {
  "gemini-2.5-flash-lite": { inputPerM: 0.075,  outputPerM: 0.30,  cachedPerM: 0.01875 },
  "gemini-2.5-flash":      { inputPerM: 0.30,   outputPerM: 1.00,  cachedPerM: 0.075   },
  "gemini-2.5-pro":        { inputPerM: 1.25,   outputPerM: 10.00, cachedPerM: 0.3125  },
};

function costUsd(modelId: string, inputTokens: number, outputTokens: number, cachedTokens: number = 0): number {
  const pricing = MODEL_PRICING[modelId];
  if (!pricing) {
    // Throw a terminal error so the workflow aborts immediately rather than
    // propagating NaN through budget arithmetic and silently disabling cost guards.
    const err = new Error(`Unpriced model "${modelId}": add it to MODEL_PRICING in gemini.ts before use.`);
    (err as any).isTerminal = true;
    throw err;
  }
  return (
    (inputTokens  * pricing.inputPerM  / 1_000_000) +
    (outputTokens * pricing.outputPerM / 1_000_000) +
    (cachedTokens * pricing.cachedPerM / 1_000_000)
  );
}

export class GeminiClient implements ModelClient {
  public modelId: string;
  private client: GoogleGenAI;

  constructor(modelId: string = DEFAULT_MODEL) {
    this.modelId = modelId;
    const config = getRuntimeConfiguration();
    
    if (config.vertexApiKey) {
      this.client = new GoogleGenAI({ apiKey: config.vertexApiKey });
    } else {
      this.client = new GoogleGenAI({
        vertexai: true,
        project: config.vertexProject,
        location: config.vertexLocation,
      });
    }
  }

  async complete(req: ModelRequest): Promise<ModelResponse> {
    const systemInstruction = req.system;
    
    // Map our messages to Gemini SDK contents
    const contents: any[] = [];
    for (const m of req.messages) {
      const role = m.role === "assistant" ? "model" : "user";
      const parts: any[] = [];
      
      if (m.role === "user" || m.role === "assistant") {
        if (m.content) parts.push({ text: m.content });
        if (m.tool_calls) {
          for (const tc of m.tool_calls) {
            parts.push({ functionCall: { name: tc.name, args: tc.arguments } });
          }
        }
      } else if (m.role === "tool") {
        parts.push({ functionResponse: { name: m.tool_call_id, response: JSON.parse(m.content) } });
      } else {
        throw new Error(`Unsupported role ${m.role}`);
      }

      if (contents.length > 0 && contents[contents.length - 1].role === role) {
        contents[contents.length - 1].parts.push(...parts);
      } else {
        if (parts.length > 0) contents.push({ role, parts });
      }
    }

    // Map tools
    const geminiTools = req.tools.length > 0 ? [{
      functionDeclarations: req.tools.map(t => ({
        name: t.name,
        description: t.description,
        parameters: t.parameters
      }))
    }] : [];

    console.log(`[LLM] Calling ${this.modelId} with ${req.messages.length} messages...`);

    try {
      const response = await this.client.models.generateContent({
        model: this.modelId,
        contents,
        config: {
          systemInstruction: systemInstruction,
          tools: geminiTools,
          temperature: req.temperature ?? 0,
          topP: req.top_p ?? undefined,
          maxOutputTokens: req.max_tokens ?? undefined,
          // seed: req.seed // Google GenAI TS doesn't seem to have seed directly?
        }
      });

      let content = "";
      const toolCalls: RequestedToolCall[] = [];
      
      const firstCandidate = response.candidates?.[0];
      if (firstCandidate?.content?.parts) {
        for (const part of firstCandidate.content.parts) {
          if (part.text) content += part.text;
          if (part.functionCall) {
            toolCalls.push({
              call_id: part.functionCall.name || "",
              name: part.functionCall.name || "",
              arguments: part.functionCall.args as Record<string, any>
            });
          }
        }
      }

      const rawUsage = response.usageMetadata;
      const inputTokens = rawUsage?.promptTokenCount ?? 0;
      const outputTokens = rawUsage?.candidatesTokenCount ?? 0;
      const cachedTokens = rawUsage?.cachedContentTokenCount ?? 0;
      
      const usage: Usage = {
        costUsd: costUsd(this.modelId, inputTokens, outputTokens, cachedTokens),
        inputTokens,
        outputTokens,
        cachedTokens,
        thoughtTokens: 0,
        cacheHit: cachedTokens > 0,
        replayed: false
      };

      let stopReason: "tool_calls" | "stop" | "refusal" | "max_tokens" | "error" = "stop";
      if (firstCandidate?.finishReason === "MAX_TOKENS") stopReason = "max_tokens";
      else if (firstCandidate?.finishReason === "SAFETY") stopReason = "refusal";
      else if (toolCalls.length > 0) stopReason = "tool_calls";

      console.log(`[LLM] Generated response (${usage.inputTokens} in / ${usage.outputTokens} out). Stop reason: ${stopReason}`);
      if (toolCalls.length > 0) {
        console.log(`[LLM] Called tools: ${toolCalls.map(t => t.name).join(", ")}`);
      }

      return {
        content,
        tool_calls: toolCalls,
        stop_reason: stopReason,
        usage,
        provider_state: {}
      };
    } catch (e: any) {
      if (e.status === 429) {
        throw new Error("429 Quota Exhausted");
      }
      if (e.status >= 400 && e.status < 500) {
        // We'll throw a distinct error to be caught as FatalError in the workflow
        const err = new Error(`Terminal Model Error: ${e.message}`);
        (err as any).isTerminal = true;
        throw err;
      }
      throw e;
    }
  }
}
