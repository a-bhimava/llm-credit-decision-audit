import { fieldIds, type CaseReview } from "./demo";

/** Keep unsaved field edits visible after an unrelated document/name save reloads the case. */
export function retainFieldDrafts(visible: CaseReview, saved: CaseReview | null,
  refreshed: CaseReview): CaseReview {
  if (!saved) return refreshed;
  const fields = { ...refreshed.fields };
  for (const id of fieldIds) {
    const draft = visible.fields[id];
    const previous = saved.fields[id];
    if (draft.value !== previous.value || draft.confirmed !== previous.confirmed) {
      fields[id] = { ...refreshed.fields[id], value: draft.value, confirmed: false };
    }
  }
  return { ...refreshed, fields };
}
