# Atlas: Security Scanner (v1)

## Objective

Add a deterministic Security Scanner: flag common, high-confidence security
anti-patterns (hardcoded secrets, dangerous shell/eval execution, unsafe
deserialization) via text/regex scanning of the same files Phase 1 already
parses. No AI involved — matches the project's "deterministic analysis first"
philosophy, and was repeatedly named across prior sessions as the strongest
next deterministic engine (unlike a real taint-analysis security scanner, this
doesn't require understanding data flow — it flags patterns that are risky by
construction regardless of context, the same posture Quality Engine took for
circular imports/naming/complexity).

## Architecture

New module `backend/app/security_scanner.py`:
`scan_files(files: list[FileSymbols]) -> SecurityReport` — re-reads each file's
raw text from `Path(f.path)` (files are already bounded to ≤2MB by
`report_pipeline._MAX_FILE_SIZE_BYTES`, so re-reading is cheap) and runs three
independent regex passes. No tree-sitter/AST needed — these are lexical
patterns, not syntactic ones, and a regex pass is simpler and language-agnostic
where the patterns themselves don't need to distinguish Python from JS (secrets
and private key headers look the same regardless of source language).

Wired in exactly where Quality Engine was: `report_pipeline.analyze_structure`
gains a `notify("scanning_security")` stage and returns a 5th tuple element;
`AnalyzeResponse` gains a required `security: SecurityReport` field (same
precedent as Phase 2 adding `quality` as required); `doc_generator.py` gains a
"Security Findings" section and the Analysis Coverage footer's Supported list
gains an entry.

```
files: list[FileSymbols]  (from analyze_structure's existing parse loop)
        │
        ▼
security_scanner.scan_files(files)
        │
        ├─ hardcoded secrets   <- regex: AWS keys, private-key headers,
        │                          "password/secret/token/api_key = '...'"
        ├─ dangerous execution <- regex: subprocess(shell=True), os.system,
        │                          eval/exec, child_process.exec
        └─ unsafe deserialization <- regex: pickle.loads, yaml.load without
                                       an explicit Loader
        │
        ▼
SecurityReport(issues: list[SecurityIssue])
```

## Data model

```python
class SecurityIssue(BaseModel):
    file: str
    line: int
    kind: str        # "hardcoded_secret" | "dangerous_execution" | "unsafe_deserialization"
    message: str
    severity: str     # "critical" | "important" | "minor"

class SecurityReport(BaseModel):
    issues: list[SecurityIssue]
```

**No numeric security score.** Quality Engine's score is already an
acknowledged, uncalibrated v1 heuristic; a "security score" formula would be
even less defensible with zero real-world calibration data. A count-and-list
is honest; a fabricated 0-100 number implying precision isn't. Explicitly
deferred until there's a real basis to calibrate one (matches the same
discipline Phase 2 used to justify shipping only 2 of 6 originally-envisioned
score categories).

## Checks (v1, three — chosen for high confidence / low noise)

1. **Hardcoded secrets** (`critical`):
   - AWS access key pattern: `AKIA[0-9A-Z]{16}`
   - Private key header: `-----BEGIN (RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----`
   - Generic secret assignment: a variable name containing
     `password|secret|api_key|apikey|access_key|token` (case-insensitive)
     assigned a quoted literal of 8+ characters, e.g. `API_KEY = "sk_live_..."`.
2. **Dangerous execution** (`important`):
   - Python: `subprocess.*(..., shell=True)`, `os.system(...)`, bare `eval(...)`/`exec(...)`.
   - JS/Node: `child_process.exec(...)` (as opposed to `execFile`/`spawn`, which
     take argument arrays and don't invoke a shell).
3. **Unsafe deserialization** (`important`):
   - Python: `pickle.loads(...)`/`pickle.load(...)`.
   - Python: `yaml.load(...)` without an explicit `Loader=` argument on the
     same line (bare `yaml.load` defaults to the unsafe loader in older PyYAML).

## Edge cases / accepted limitations

- **Regex over text, not AST, means no scope/type awareness** — a variable
  literally named `password` holding a non-secret test fixture value, or a
  comment mentioning "eval" in prose, can false-positive. Same accepted-heuristic
  posture as the bug-fix-commit regex and naming-convention checks elsewhere in
  Atlas — not tunable further without real semantic analysis, out of scope.
- **String-concatenation-based SQL injection was considered and deferred.**
  Reliably distinguishing `cursor.execute(f"SELECT * FROM {table}")` (risky,
  interpolates a possibly-untrusted value) from `cursor.execute(f"SELECT * FROM
  {CONSTANT_TABLE_NAME}")` (safe, but the same textual shape) needs real data-flow
  awareness that a regex pass can't provide — flagging every f-string/format
  call near `.execute(` would be noisy enough to erode trust in the whole
  scanner. Left for a later phase once there's appetite for real dataflow analysis.
- **Weak CORS / missing auth decorators were considered and deferred** — both
  are framework-specific (Flask's `@app.route` vs. Express's middleware chain
  vs. FastAPI's dependency injection look nothing alike), so a generic v1 check
  would either miss most real cases or need per-framework special-casing that
  doesn't fit a single regex pass. Left for a framework-aware follow-up.
- Binary/oversized files never reach this scanner — they're already excluded
  by `_iter_source_files`'s existing size/count bounds before parsing.

## Testing

- Unit tests in `test_security_scanner.py`: one fixture per check category with
  a clear positive case and a clear negative case (e.g. a real AWS-key-shaped
  string vs. an unrelated 20-character string; `subprocess.run(cmd,
  shell=True)` vs. `subprocess.run(["cmd"])`; `yaml.load(f, Loader=yaml.SafeLoader)`
  vs. bare `yaml.load(f)`).
- `test_report_pipeline.py`: `analyze_structure` returns a `SecurityReport` and
  `"scanning_security"` appears in the stage list at the right point.
- `test_api.py`: `/analyze`'s response includes a `security` field with the
  expected shape.
- `test_doc_generator.py`: the new report section renders known findings and
  the Analysis Coverage footer mentions security scanning as supported.
- Real-repo validation: run `/analyze` against a real repo and manually
  eyeball whether any flagged findings look like genuine, sensible results (a
  clean well-maintained repo like `tiangolo/typer` should report zero or very
  few hits) rather than a flood of noise.

## Risks

Low-to-moderate false-positive rate on the "generic secret assignment" pattern
specifically (the least specific of the three checks) — flagged in the design
above and something to sanity-check during real-repo validation before calling
this done.
