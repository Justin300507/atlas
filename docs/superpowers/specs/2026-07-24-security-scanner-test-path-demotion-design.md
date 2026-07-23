# Security scanner: demote findings in test/fixture paths

## Problem, confirmed empirically

Real-world validation asked "were security findings believable?" — reading
the actual findings (not just counting them) against Django and React
found the answer was largely no:

- **Django**: of the 20 shown findings (out of 151 total), all 20 are
  `hardcoded_secret` hits inside `tests/` — Django's own unit tests
  assigning dummy passwords like `password="testpass123"` to test
  fixtures, flagged `critical`.
- **React**: the first 20 shown findings are almost entirely `eval()`/
  `exec()` calls inside `__tests__/fixtures/compiler/...` — a JS compiler
  test suite whose entire job is to feed `eval`/`exec` source strings
  through the compiler and assert on the output. Flagged `important`.

Neither is a real security risk. Both are exactly what a test suite is
supposed to contain. Surfacing them at `critical`/`important` severity,
sorted to the top of every report (Risk Areas and Security Findings both
sort by severity), drowns out any real findings and reads as the tool not
understanding what it's looking at — a direct hit to "would an engineer
trust this."

## Fix

Detect paths that look like tests or fixtures (a directory segment named
`test`, `tests`, `__tests__`, `fixtures`, `testdata`, `spec`, or `specs`;
or a filename matching `test_*`, `*_test`, `*.test.*`, `*.spec.*`) and
demote — not delete — findings in those paths to `minor` severity, with
the message amended to say why (`"... (in a test/fixture path — lower
confidence)"`).

Deliberately demote rather than exclude: a real secret can genuinely leak
into a test fixture (an API key pasted into a test by mistake is a real
incident, not a false positive), so silently dropping test-path findings
would itself violate the "surface it honestly, never silently discard"
principle applied elsewhere in this project (git-history truncation,
file-cap truncation). Demoting keeps the finding visible to someone who
scrolls past the `critical`/`important` findings, while no longer letting
routine test fixtures dominate the top of every report.

## What does NOT change

- Detection logic itself (the six regexes) — unaffected, still runs
  against every file including test files.
- Non-test-path findings — severity and message unchanged.
- The private-key-header check, which already scans the whole file for a
  literal `-----BEGIN ... PRIVATE KEY-----` block: still checked
  everywhere, still demoted if the file is a test path, same as the rest.

## Test impact

All existing `test_security_scanner.py` fixtures use flat filenames at
`tmp_path` root (e.g. `config.py`, `runner.py`) — none match the new
test-path heuristic, so no existing assertion changes. New tests added
for: directory-segment detection, filename-pattern detection, and
confirming demotion changes severity + message without dropping the
finding.
