import { Applicant, Decision, EpisodeKey, RenderMode, Termination } from "@/lib/audit/records";
import { Policy } from "@/lib/audit/policy";
import { applicantContentId, episodeInputHash } from "@/lib/audit/ids";
import { applicantReferenceFor } from "@/lib/audit/render/reference";

export type CreditEnvState = Readonly<{
  episode_key: EpisodeKey;
  applicant: Applicant;
  policy: Policy;
  application_text: string;
  applicant_ref: string;
  render_mode: RenderMode;

  step: number;
  tools_called: readonly string[];
  credit_report_pulled: boolean;
  income_verified: boolean;
  verified_income_cents: number | null;
  trap_called: boolean;
  decision: Decision | null;
  terminated: boolean;
  termination: Termination | null;
}>;

export function buildCreditEnvState(
  episodeKey: EpisodeKey,
  applicant: Applicant,
  policy: Policy,
  applicationText: string,
  applicantRef: string,
  renderMode: RenderMode
): CreditEnvState {
  if (episodeKey.applicant_id !== applicant.applicant_id) throw new Error("episode_key.applicant_id mismatch");
  if (episodeKey.applicant_content_id !== applicantContentId(applicant)) throw new Error("episode_key.applicant_content_id mismatch");
  if (episodeKey.render_id !== renderMode) throw new Error("episode_key.render_id mismatch");
  if (applicantRef !== applicantReferenceFor(applicant)) throw new Error("applicant_ref mismatch");
  const expectedHash = episodeInputHash(applicant, applicationText, applicantRef, renderMode);
  if (episodeKey.input_hash !== expectedHash) throw new Error("episode_key.input_hash mismatch");

  return {
    episode_key: episodeKey,
    applicant,
    policy,
    application_text: applicationText,
    applicant_ref: applicantRef,
    render_mode: renderMode,
    step: 0,
    tools_called: [],
    credit_report_pulled: false,
    income_verified: false,
    verified_income_cents: null,
    trap_called: false,
    decision: null,
    terminated: false,
    termination: null
  };
}

export function stateFingerprint(state: CreditEnvState): Record<string, any> {
  return {
    episode_id: state.episode_key.episode_id,
    applicant_id: state.applicant.applicant_id,
    applicant_ref: state.applicant_ref,
    render_mode: state.render_mode,
    step: state.step,
    tools_called: state.tools_called,
    credit_report_pulled: state.credit_report_pulled,
    income_verified: state.income_verified,
    verified_income_cents: state.verified_income_cents,
    trap_called: state.trap_called,
    decision: state.decision,
    terminated: state.terminated,
    termination: state.termination
  };
}
