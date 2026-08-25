# Next.js 15 & Tailwind V4 Guidelines

## 1. Next.js Build Constraint [CRITICAL]
- **NEVER** run `next build` or `pnpm build` while the Next.js development server (`next dev`) is actively running.
- **Why:** It corrupts the `.next` cache, causing React hydration failures and unclickable interactive elements.
- **Protocol:** You must always terminate the dev server (`killall node`), run `rm -rf .next`, and then run the build or restart the dev server.

## 2. Tailwind V4 Dark Mode Quirks
- **Constraint:** In Tailwind v4, `dark` is a variant, not a standard utility class.
- **Rule:** DO NOT use `@apply dark;` inside CSS files. This will throw a fatal PostCSS/Webpack build error (`Cannot apply unknown utility class 'dark'`).
- **Protocol:** To enable dark mode via CSS variables on custom elements, append your component classes directly to the `.dark` selector block in `globals.css` (e.g., `.dark, .myCustomShell, .studio { ... }`).
