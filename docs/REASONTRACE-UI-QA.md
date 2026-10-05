# ReasonTrace UI polish

The five-case interview flow uses four adapted [React Bits](https://reactbits.dev/get-started/index) components:

- **Spotlight Card** marks each selectable synthetic case and frames the new home-page entry point to ReasonTrace. The effect follows a fine pointer, while the active case keeps a stable border and background. Buttons and links remain the accessible controls.
- **Glare Hover** gives the enabled audit action a restrained highlight. The effect is absent while the action is disabled.
- **Stepper** shows reviewed pages, confirmed facts, and audit readiness from the actual case state. Each step is a button that moves keyboard focus to the corresponding evidence panel. It stacks vertically on narrow screens so the status text stays readable. Audit Studio also uses an informational five-step variant with a progress track and `aria-current="step"`; Back and Continue remain its navigation controls.
- **Animated Content** briefly reveals a completed audit result and each Audit Studio intake form. The adaptation uses the app's existing Framer Motion dependency and removes movement for reduced-motion users.

These components use the existing ReasonTrace colors. Touch and reduced-motion users see the static design. The source attribution and license are in `web/components/react-bits/`.

Verification on 2026-10-04: `pnpm typecheck`, `pnpm build` (including the security-boundary assertion), and the nine focused ReasonTrace unit tests passed. Local production-preview browser checks at 1440 × 900 and 390 × 844 found five case controls, no horizontal overflow or page errors, working case switching, a complete saved-fixture audit, and the reduced-motion fallback.

The repository-wide `pnpm exec vitest run` command currently fails in unrelated legacy parity suites (including unresolved aliases and monotonicity fixture mismatches). This visual change does not touch those suites; the focused ReasonTrace suite is the relevant regression check here.

Verification on 2026-10-05: type checking, focused ReasonTrace tests, and the production build passed. Browser checks confirmed the stepper changes from 0/3 to 3/3 as the reviewer works, its buttons focus the matching panels, the audit result appears only after the local scripted run, and the 390px mobile view has no horizontal overflow or page errors.

The home-page callout links to `/reasontrace` while preserving the Audit Studio and evidence-ledger navigation. Browser checks at 1440px and 390px followed that link into all five selectable cases with no overflow or page errors.

Audit Studio verification on 2026-10-05: type checking, the nine focused ReasonTrace tests, and the production build including the security-boundary assertion passed. Local production browser checks at 1440 × 900 and 390 × 844 traversed all five intake stages and back without losing edited values. The active step and focus target updated on each move. The 390px layout has no horizontal overflow after tightening the grid's minimum width. Reduced-motion navigation also completed without page errors. The browser check stopped on the review step and did not launch a paid audit.

The document packet now has a separate React tab component. It exposes each page's missing, reviewed, or pending state; Arrow keys and Home/End switch pages with focus; source links focus the matching tab. Local production browser checks at 1440px and 390px verified keyboard navigation, the tab-to-panel relationship, source-link focus, the case-five missing label, and no page overflow. A mobile screenshot exposed a clipped initial third tab; the tab strip now scrolls the selection fully into view. The additional browser check for the status changing immediately after clicking **Mark reviewed** was not completed because automatic permission review timed out twice before that check ran; the status is derived from the same `review.documents` state used by the existing button.
