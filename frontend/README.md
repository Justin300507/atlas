# Atlas Frontend

React + Vite + TypeScript. Single-page: paste a GitHub URL, submit, poll
job progress, render the resulting Markdown report.

## Setup

```bash
npm install
npm run dev
```

Needs the backend running (see `../backend/README.md`) and
`VITE_API_BASE` pointed at it — see `../DEPLOYMENT.md` for the default
and how it's baked in at build time.

## Scripts

```bash
npm run dev       # dev server with HMR
npm run build     # tsc -b && vite build
npm run lint       # oxlint
npm test           # vitest run
```

## Structure

`src/App.tsx` (submit → poll → render), `src/MarkdownReport.tsx`
(renders the Markdown, lazy-loads Mermaid only when a diagram is
present). Job state persists to `localStorage` so it survives a page
refresh — see `../docs/superpowers/specs/2026-07-23-refresh-reconnect-recovery-design.md`.

See `../ARCHITECTURE.md` for how this fits into the rest of Atlas.
