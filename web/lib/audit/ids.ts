import { blake2bHex } from "blakejs";
import { canonicalJson, contentId, deriveSeed } from "./canonical";
import { Applicant, Trajectory, RenderMode } from "./records";

export { canonicalJson, contentId, deriveSeed };

export function shortId(obj: unknown, length = 8): string {
  const hex = blake2bHex(Buffer.from(canonicalJson(obj), "utf8"), undefined, 16);
  return hex.slice(0, length);
}

export function applicantContentId(applicant: Applicant): string {
  return contentId({ facts: applicant.facts, presentation: applicant.presentation });
}

export function episodeInputHash(
  applicant: Applicant,
  applicationText: string,
  applicantRef: string,
  renderMode: RenderMode
): string {
  return contentId({
    applicant_content_id: applicantContentId(applicant),
    application_text: applicationText,
    applicant_ref: applicantRef,
    render_mode: renderMode,
  });
}

export function trajectoryContentId(
  episodeId: string,
  messages: unknown,
  toolCalls: readonly any[],
  decision: unknown,
  termination: unknown
): string {
  const semanticToolCalls = toolCalls.map(call => ({
    call_id: call.call_id,
    turn_index: call.turn_index,
    step: call.step,
    name: call.name,
    arguments: call.arguments,
    result: call.result,
    ok: call.ok,
    error: call.error,
  }));

  return contentId({
    episode_id: episodeId,
    messages,
    tool_calls: semanticToolCalls,
    decision,
    termination,
  });
}

export function clusterIdFor(applicant: Applicant): string {
  const root = applicant.provenance.parent_applicant_id || applicant.applicant_id;
  return `cluster_${shortId({ source_applicant_id: root }, 16)}`;
}
