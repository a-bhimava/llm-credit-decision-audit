import { Applicant } from "../records";
import { contentId } from "../ids";

export function applicantReference(applicantId: string): string {
  const digest = contentId(applicantId, 16);
  const hexPart = digest.split(":")[1]!;
  return `MPL-${hexPart.slice(0, 10).toUpperCase()}`;
}

export function applicantReferenceFor(applicant: Applicant): string {
  return applicantReference(applicant.applicant_id);
}
