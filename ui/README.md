# pgproof UI

Local browser UI: React, TypeScript, Vite. `docs/INTERFACE_DESIGN.md` is the
design system; `docs/ARCHITECTURE.md` section 5 is the directory layout.

```text
npm install
npm run dev          # local dev server
npm run build         # type-check + production build
npm run lint           # oxlint, including jsx-a11y
npm run test            # Vitest unit tests
npm run test:visual      # Playwright screenshots at 1440/1024/390 px, light/dark
```

`src/contract/` is the single point that imports the generated types in
`contracts/types/generated/` — feature code should import from there, not
reach across the repository boundary directly.

Visual baselines live in `tests/visual/__screenshots__/`. A baseline change
requires explicit review (`docs/INTERFACE_DESIGN.md` section 15) — regenerate
intentionally with `npx playwright test --update-snapshots`, never to silence
a failure you have not looked at.
