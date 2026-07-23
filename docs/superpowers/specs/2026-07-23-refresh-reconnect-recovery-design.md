# Atlas: Refresh / Reconnect Recovery (v1)

## Problem

A job survives on the backend (SQLite-persisted, running on a thread pool)
independent of any browser tab. But the frontend keeps job state only in
React state, so a refresh, an accidental navigation, or a crashed tab during
a `running` analysis drops the user back to the `idle` form with no way to
find their job again, even though it's still running (or already finished)
server-side.

## Architecture

**Backend**: `GET /jobs/{id}` gains `created_at` in its response (already
stored in `JobRecord`, just not serialized). The frontend needs this to
reconstruct elapsed time without the server tracking anything extra.

**Frontend** (`App.tsx`):
- On successful `createJob`, persist `{ jobId, repoUrl }` as JSON to
  `localStorage["atlas.activeJob"]`.
- On mount (once, guarded against StrictMode's dev double-invoke with a
  ref), read that key. If present and parses cleanly:
  - Optimistically restore `repoUrl` and switch to the `running` view.
  - Fetch `GET /jobs/{id}` once.
    - 404 (or any fetch failure) → treat the job as gone/expired: clear the
      stored key, fall back to `idle`.
    - `status` is `queued`/`running` → set `elapsedSeconds` from
      `created_at` vs. now, then start the same poll+timer loop
      `handleSubmit` uses.
    - `status` is `done`/`error` → set the job and jump straight to that
      terminal view; no polling needed.
- Extract the poll/timer-start logic (currently inline in `handleSubmit`)
  into one `startTracking(jobId, startedAtMs)` helper so `handleSubmit` and
  the mount-recovery path share it instead of duplicating interval setup.
- Clear `atlas.activeJob` whenever a job reaches `done`/`error` (in the
  poll loop, in both the normal and recovery paths) and in `reset()`.

## Alternatives considered

- **Tick elapsed seconds into localStorage continuously** — rejected;
  needless writes every second. The server's `created_at` is authoritative
  and only needs reading once, on recovery.
- **`sessionStorage` instead of `localStorage`** — rejected; a refresh
  survives either, but `sessionStorage` doesn't survive closing and
  reopening the tab, which is a real case (walking away, laptop sleep). A
  stale entry pointing at a long-finished job is already handled safely (see
  edge cases), so persistence duration isn't a risk worth trading away.
- **Block rendering until the recovery fetch resolves** — rejected in favor
  of the same optimistic-`running` feel `handleSubmit` already has, for
  consistency.

## Edge cases

- Corrupted/garbage JSON in the stored key → wrapped in try/catch, treated
  as "no saved job," key cleared.
- Job ID refers to a job from a wiped/replaced dev DB → covered by the same
  404 path as a genuinely expired job.
- Multiple tabs each running a different analysis → last write to
  `localStorage` wins; out of scope for v1 (single active job per browser
  profile is an acceptable v1 limitation).
- React StrictMode double-invoking the mount effect → guarded with a
  `hasCheckedRecovery` ref so the recovery fetch fires at most once.
