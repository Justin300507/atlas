# Atlas: Production Polish (v1)

## Problem

A pass over the actual frontend (`App.tsx`, `MarkdownReport.tsx`,
`App.css`, `index.css`) surfaced three concrete, verifiable gaps rather
than subjective taste — this phase fixes those, not a redesign:

1. **Accessibility**: the repo-URL `<input>` has only a placeholder, not a
   `<label>` (placeholders are not an accepted label substitute per WCAG
   1.3.1); the error message and the running/done/error state transitions
   have no ARIA live region, so a screen-reader user gets no announcement
   when a long-running analysis finishes, fails, or gets a validation
   error — everything is silent until they happen to navigate to it.
2. **Responsiveness**: GFM tables (`ownership`/`churn` rollups have several
   columns) rendered by `react-markdown` + `remark-gfm` have no overflow
   handling. `.report pre` already wraps preformatted text, but a wide
   `<table>` on a narrow viewport just overflows the page instead of
   scrolling within its own bounds.
3. **Dead CSS**: `index.css` styles `#social .button-icon` and `.counter`
   — leftover template selectors with zero matching elements anywhere in
   the actual app (confirmed via grep across all `.tsx` files). Dead rules
   like this actively mislead a future reader into thinking there's a
   social-links section or a counter component somewhere.

## Architecture

- `App.tsx`: repo-URL input gets a real `<label htmlFor="repo-url">`
  (visually a `.sr-only` visually-hidden style, since the placeholder
  already conveys the same information sighted users need — this isn't a
  visual change, just an accessible name). The error paragraph gets
  `role="alert"`. The `.progress` container gets `aria-live="polite"
  aria-busy="true"` so a stage change or the terminal done/error view is
  announced without needing `aria-live="assertive"` spam on every
  elapsed-second tick (elapsed-seconds text stays outside the live region).
- `MarkdownReport.tsx`: add a `table` renderer to the existing
  `components` prop (same pattern already used for `code`/`MermaidBlock`)
  that wraps the rendered `<table>` in a `<div className="table-scroll">`
  with `overflow-x: auto`.
- `index.css`: delete the `#social .button-icon` rule and the `.counter`
  selector's now-unused half (keep `code`'s shared styling, since `code`
  *is* used).

## Alternatives considered

- **A full visual redesign** — rejected; out of scope for a "polish, don't
  rewrite" pass, and the existing dark/light-aware CSS custom properties
  already work. Fix concrete defects, not subjective style.
- **`aria-live="assertive"` on the whole progress view** — rejected; would
  re-announce "Xs elapsed" every second, which is worse than the silence
  it replaces. Scope the live region to stage/status changes only.

## Edge cases

- Visually-hidden label must not be `display: none` (that removes it from
  the accessibility tree too) — uses the standard clip-based `.sr-only`
  pattern instead.
- The `table-scroll` wrapper must not clip a table's own box-shadow/border
  if one is added later — plain `overflow-x: auto`, no `overflow: hidden`.
