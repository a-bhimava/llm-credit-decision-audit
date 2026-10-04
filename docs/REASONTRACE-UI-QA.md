# ReasonTrace UI polish

The five-case interview flow uses two adapted [React Bits](https://reactbits.dev/get-started/index) components:

- **Spotlight Card** marks each selectable synthetic case. The effect follows a fine pointer, while the active case keeps a stable border and background. The button remains the accessible control.
- **Glare Hover** gives the enabled audit action a restrained highlight. The effect is absent while the action is disabled.

Both components use the existing ReasonTrace colors. Touch and reduced-motion users see the static design. The source attribution and license are in `web/components/react-bits/`.

Verification on 2026-10-04: `pnpm typecheck`, `pnpm build` (including the security-boundary assertion), and the nine focused ReasonTrace unit tests passed. Local production-preview browser checks at 1440 × 900 and 390 × 844 found five case controls, no horizontal overflow or page errors, working case switching, a complete saved-fixture audit, and the reduced-motion fallback.

The repository-wide `pnpm exec vitest run` command currently fails in unrelated legacy parity suites (including unresolved aliases and monotonicity fixture mismatches). This visual change does not touch those suites; the focused ReasonTrace suite is the relevant regression check here.
