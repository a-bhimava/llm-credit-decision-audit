import { ModelRequest } from "./client";
import { contentId } from "@/lib/audit/ids";

export function cacheKey(req: ModelRequest, provider: string = "gemini"): string {
  const payload = {
    provider,
    model_id: req.model_id,
    params: {
      temperature: req.temperature,
      top_p: req.top_p,
      max_tokens: req.max_tokens,
      seed: req.seed
    },
    system: req.system,
    messages: req.messages,
    tools: req.tools,
    context_hash: req.context_hash
  };
  return contentId(payload);
}
