# Atlas: Public Beta Frontend Polish (v1)

## Problem

A real Playwright-driven browser session (screenshots across idle/running/
done states, light/dark themes, mobile viewport, keyboard-only navigation)
surfaced concrete defects that neither unit tests nor code review had
caught, since none of them exercise actual rendered layout:

1. **Report content was center-aligned.** `#root { text-align: center }`
   applied to the entire app, including the actual analysis report —
   every bullet, table cell, and wrapped paragraph line was independently
   re-centered. On a real (non-trivial) report with longer text this
   makes the document genuinely hard to read; on mobile it's worse, with
   wrapped lines producing a ragged, unreadable shape.
2. **Tables had no visual styling.** `<table>`/`<th>`/`<td>` relied on
   browser defaults — no borders, no header distinction, no padding —
   making the churn/ownership tables hard to scan.
3. **Report sections had no spacing.** `p`/`h2` margins are zeroed
   globally (needed for the hero title), so every section ran directly
   into the next with no visual separation.
4. **The idle screen was nearly blank** — a bare title, input, and
   button, with no indication of what the tool does, in a large empty
   page.
5. **The running view's "current" stage was indistinguishable from a
   not-yet-reached one** — both rendered in the same grey; only
   completed steps were visually distinct.

## Architecture

- `index.css`: `text-align: center` moved off `#root` entirely and onto
  `h1` specifically — the only element that should stay centered
  regardless of view.
- `App.css`: `.app` gets an explicit `text-align: center` (covering the
  idle form and running-progress views, which are short/hero-like), and
  `.report` explicitly overrides back to `text-align: left`. Added
  section-spacing rules scoped to `.report` (`h2` top margin, `p`/`ul`
  margin, `li` spacing) and real table styling (`border-collapse`,
  bordered cells, a shaded header row using the existing `--code-bg`
  token so it's theme-aware for free).
- `App.tsx`: added a one-line `.tagline` paragraph above the idle-state
  form (moved outside the `<form>` itself — a first attempt placed it
  inside the flex-row form and it rendered squeezed next to the input,
  caught by re-screenshotting after the first pass). The progress list's
  per-stage class logic changed from a binary `done`/`""` to three states
  — `done` (`i < currentStageIndex`), `current` (`i === currentStageIndex`,
  styled in the existing `--accent` color), and pending (unstyled) — so
  the actively-running stage is visually distinct from both completed and
  future ones.
- `.error` (previously a hardcoded `#b00020`, invisible/low-contrast
  against a dark background) now themes properly via the existing
  light/dark custom-property pattern.

## Alternatives considered

- **A full visual redesign** — explicitly out of scope (this session's
  brief calls for polish, not a redesign); every change here is a fix to
  a concretely observed defect, not a stylistic preference.
- **Keeping the whole app left-aligned, including the hero title** —
  rejected; a large left-aligned "Atlas" title read as unstyled/broken in
  the screenshot review, whereas a centered hero title over a left-aligned
  document body is a completely standard, expected pattern.

## Validation

All of the above was found and confirmed via a real Playwright session
(Chromium, installed and run in this environment) against the actual dev
server — not just unit tests: light and dark theme screenshots of every
view (idle, running, done, error), a 390px mobile viewport check (no
horizontal overflow, confirmed both before and after), and a keyboard-only
navigation check (Tab order: input → button, both with a visible focus
ring). Existing Vitest suite (15 tests) updated for the `current`/`done`
class split and re-verified green; `npm run build` re-verified clean.
