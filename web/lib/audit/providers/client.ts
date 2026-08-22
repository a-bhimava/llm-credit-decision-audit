import { Message, RequestedToolCall, Usage } from "@/lib/audit/records";
import { ToolSpec } from "@/lib/audit/env/tools";

export interface ModelRequest {
  model_id: string;
  system: string;
  messages: readonly Message[];
  tools: readonly ToolSpec[];
  temperature: number | null;
  top_p: number | null;
  max_tokens: number | null;
  seed: number;
  context_hash: string;
  provider_state: Record<string, any>;
}

export interface ModelResponse {
  content: string;
  tool_calls: readonly RequestedToolCall[];
  stop_reason: "tool_calls" | "stop" | "refusal" | "max_tokens" | "error";
  usage: Usage;
  provider_state: Record<string, any>;
}

export interface ModelClient {
  modelId: string;
  complete(req: ModelRequest): Promise<ModelResponse>;
}
