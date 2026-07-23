# File-walk cap should count source-file candidates, not every file

## Problem, confirmed empirically

Turning on the truncation-visibility fix (`FileCoverage.files_capped`,
shipped in `91fd850`) immediately surfaced a real, quantified problem on
re-validation: Django's report says `files_capped: true` at only 1,511
files analyzed — nowhere near the 5,000 cap. Direct measurement:

- Django has **7,077** total non-excluded files.
- Of those, **2,927** are real `.py` source files.
- The walk hit the 5,000-file cap before finishing the tree, having
  spent most of that budget on non-source files (docs, `.po`/`.mo`
  translation files, fixtures, static assets, HTML templates) — leaving
  only 1,511 of Django's 2,927 real Python files ever examined.

**Nearly half of Django's actual Python source was silently excluded from
analysis** — not because 2,927 exceeds a reasonable cap, but because the
cap counts every file the walk touches, source or not, so a repo with a
lot of non-source clutter interleaved with its source tree starves real
coverage before ever getting close to a source-file count that would
actually justify capping.

## Fix

Two caps doing two different jobs, where there was only one before:

1. **`_MAX_FILES_PER_REPO` (unchanged at 5,000)** now counts only files
   that pass `language_for(path) is not None` — i.e. files the pipeline
   will actually attempt to parse. Walking past a non-source file (a
   cheap suffix lookup, no I/O beyond what `rglob`/`is_file` already
   costs) no longer consumes this budget. `language_for` is a plain dict
   lookup by extension, already called inside `parse_file` — calling it
   once more during the walk to decide whether a file counts is
   negligible.

2. **New `_MAX_TOTAL_ENTRIES_WALKED = 50,000`**: the original cap's
   stated purpose (see its comment: "must not be able to exhaust
   memory/CPU") was never really about *source* file count — it was
   about bounding the filesystem walk itself against a pathological repo
   (a huge vendored/binary/data tree, hundreds of thousands of files).
   Making the 5,000 cap source-only removes that protection unless
   something else provides it: a repo with 500,000 total files but only
   100 real source files would now walk the entire 500,000-entry tree
   before naturally finishing, since it would never hit a source-file
   cap it's nowhere close to. The new ceiling is a circuit-breaker on raw
   entries examined, independent of file type, set generously high (10x
   the source cap) so it essentially never fires on any real repo in
   this project's validation set (the largest, React, has ~1,079 import
   edges across way under 50,000 total files) but still bounds worst-case
   pathological input. Hitting *either* cap sets `files_capped = True` —
   both represent a genuinely incomplete analysis.

## What does NOT change

- `_MAX_FILE_SIZE_BYTES` (2MB per-file skip) — unrelated axis, unaffected.
- The `FileCoverage` model and its consumers (doc_generator's coverage
  note, `/analyze`'s JSON response) — same fields, now fed more accurate
  numbers.
- Non-source files are still walked past (`rglob` still visits them) —
  this fix doesn't skip the filesystem cost of encountering them, only
  the "counts against the source cap" cost. That's an acceptable
  trade-off: `is_file()` + a dict lookup per entry is cheap; the earlier
  cap protected against *parsing* cost more than walk cost, and the new
  total-entries ceiling still bounds worst-case walk cost.

## Validation plan

Re-run `validate_real_repos.py` against Django specifically after the
fix and confirm: `files_capped` is now `false`, `files_analyzed` is close
to the true 2,927 Python files (not exactly equal — `parse_file` still
returns `None` for any `.py` file `language_for` matches but that
otherwise fails to parse, though that's the `files_parse_failed` path,
not this one), and the resulting quality/architecture scores are
recomputed on the fuller picture.
