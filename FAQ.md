# FAQ

## What is Atlas?

Paste a public GitHub URL, get back a full engineering review: stack
detection, an architecture/dependency graph, code quality scores,
security findings, and git-history intelligence (churn, ownership,
co-change), assembled into a single Markdown report. See
[`README.md`](README.md) for the feature list and
[`ARCHITECTURE.md`](ARCHITECTURE.md) for how the pieces fit together.

## Why does it exist?

Most AI coding tools answer "can this generate code for me?" Atlas asks
"can this help me understand code that already exists?" — a repo you've
inherited, a PR you're reviewing, a dependency you're evaluating. That's
a narrower problem than code generation, but a more stable one: it
doesn't depend on the latest model, and deterministic analysis is
something you can actually trust the output of.

## How does it work?

Entirely static analysis — no LLM calls anywhere in the pipeline:

1. Shallow-clones the repo (plus a bounded history depth for git
   intelligence).
2. Parses Python and JavaScript/TypeScript/TSX with tree-sitter into an
   import/route dependency graph (NetworkX).
3. Runs quality checks (circular imports via strongly-connected
   components, long/complex functions, naming) and a regex-based
   security scanner (secrets, dangerous exec, unsafe deserialization)
   over the parsed files.
4. Parses `git log --numstat` for churn, ownership, and co-change
   patterns.
5. Assembles everything into one Markdown report with a Mermaid diagram.

## Why not just use an LLM to review the repo?

An LLM summarizing a codebase can be fluent and still wrong — it can
describe a dependency that doesn't exist or miss one that does. Every
finding in an Atlas report traces back to a deterministic check you can
verify yourself (a specific regex match, a specific cycle in the import
graph, a specific line in `git log`). That's a narrower set of things
Atlas can tell you than an LLM could improvise, but everything in that
narrower set is real. See
[`ARCHITECTURE.md`](ARCHITECTURE.md#why-deterministic-analysis-not-an-llm-wrapper).

## How do I run it?

`docker compose up --build` is the fastest path — see
[`DEPLOYMENT.md`](DEPLOYMENT.md). For local backend/frontend dev without
Docker, see the [`CONTRIBUTING.md`](CONTRIBUTING.md) setup steps.

## How was it validated?

Against real public repositories (Django, FastAPI, Flask, React,
Express, and requests — five web frameworks plus one non-framework
library, to check the scoring/scanning generalize), not synthetic test
fixtures — see
[`docs/benchmarks/2026-07-24-real-world-validation.md`](docs/benchmarks/2026-07-24-real-world-validation.md)
for methodology and results, and
[`docs/benchmarks/real-world-validation-reports/`](docs/benchmarks/real-world-validation-reports/)
for the full generated report from each run. Performance/load numbers
are in
[`docs/benchmarks/2026-07-23-performance-and-load-benchmark.md`](docs/benchmarks/2026-07-23-performance-and-load-benchmark.md).
One repo in the validation list (`vercel/next.js`) is documented as
failing to clone in the benchmark environment — a local git/Windows
issue, not an Atlas bug; see that doc for detail.

## What does Atlas *not* do?

See [`ROADMAP.md`](ROADMAP.md) for planned-but-not-built subsystems
(AI Architect Q&A, Technical Debt Analyzer, Performance Analyzer). See
**Known Limitations** below for caveats in what *is* built.

## Known Limitations

Every item below is a currently-true, code-verified limitation — pulled
from the design doc for the relevant feature (`docs/superpowers/specs/`)
and cross-checked against the shipped code, not aspirational. If a spec
described a limitation that a later fix removed, it's omitted here.

### Language support

- Only Python and JavaScript/TypeScript/TSX get deep parsing (import
  graph, routes, symbols). Every other language gets coarse stack
  detection only (file extensions, known config files) — no dependency
  graph, no quality/security analysis of that code.
- `require("literal/path")` is resolved; `require(pathVariable)` and
  dynamic `import(computedExpr)` with a non-literal argument are not —
  only the first string-literal argument is tracked.
- A locally-defined identifier named `require` that isn't Node's module
  loader is indistinguishable from the real one and can produce a
  spurious import edge.

### Repo size caps

- Repos are capped at 5,000 source files (`_MAX_FILES_PER_REPO`) and
  50,000 total filesystem entries walked (`_MAX_TOTAL_ENTRIES_WALKED`).
  A repo exceeding either gets a partial analysis, surfaced via a
  `files_capped` flag in the report rather than hidden.
- Individual files over 2MB are skipped entirely — no parsing, no
  quality checks, no security scan of that file.
- Git history is bounded to the last 500 commits per analysis
  (`history_truncated` flag surfaces this) — churn/ownership/co-change
  are blind to anything older.
- The Mermaid dependency diagram in the generated report is capped at
  the top 40 nodes by degree; larger graphs get a truncated diagram.

### Security scanner

- Detection is regex/text-based over raw file content, not AST- or
  type-aware. It can false-positive (a variable literally named
  `password` holding a non-secret) and can't reason about scope.
- SQL injection via string concatenation/f-strings into a query call is
  **not** detected — that needs data-flow analysis a regex pass can't
  do.
- Weak CORS configuration and missing auth middleware are **not**
  checked — too framework-specific for one generic rule.
- No numeric security score — only a list/count of findings.
- Findings inside files that look like tests/fixtures are demoted to
  `minor` severity, not removed, so they still appear in reports (a real
  leaked secret in a test file is possible).

### Quality scoring

- Only Maintainability, Architecture, and a derived Overall score are
  computed. Testing, Security, and Documentation scores described in
  early planning were never built as scores (Security has a separate
  finding list instead).
- Duplicate-code and dead-code detection are not implemented.
- Naming-convention checks are regex-based against extracted names, with
  the same false-positive/negative class as the security scanner.
- Scoring weights and smoothing constants are hand-picked heuristics,
  not calibrated against a labeled dataset.

### Semantic repository intelligence

- Layer detection matches directory names against a fixed vocabulary
  (presentation/api/service/domain/infrastructure/persistence). A repo
  organized by feature instead of by layer correctly gets "insufficient
  evidence" — verified on Atlas's own repo, which reports 0% coverage
  since it's organized by technical role (`app/`, `tests/`), not layer.
- Betweenness/closeness centrality are skipped above 5,500 modules (a
  defensive ceiling — measured cost was 4.28s on Django's 3038 modules,
  trivial next to that repo's 40-80s clone+parse time, and the existing
  5,000-file analysis cap means module count can't actually reach the
  ceiling in practice).
- Coupling/smell thresholds are percentile-based within the analyzed
  repo, not fixed magic numbers — a repo where the large majority of
  modules share the same fan-in/fan-out value will correctly report
  nothing (no real variance to rank against) rather than a false
  positive, which means very sparse or undifferentiated repos get less
  coupling analysis, not wrong analysis.
- Facade/utility-dumping detection is a pattern match (filename +
  fan-in/fan-out shape), not a claim about the author's intent.

### Git intelligence

- Bug-fix commit detection is one regex against the commit subject line
  (`fix|fixes|fixed|bug|hotfix|patch|bugfix`) — misses unconventional
  commit message styles.
- No per-directory churn rollups, no per-author leaderboard, no time
  windowing (e.g. "churn in the last 30 days").
- Co-change pairing is permanently skipped for any single commit
  touching more than 100 files (e.g. an initial "add everything" commit)
  — a deliberate bound to avoid O(k²) blowup, not a bug pending a fix.

### Production / deployment posture

- **No authentication.** Atlas is a fully public, unauthenticated
  analysis tool for any repo URL — a scope choice, not an oversight.
- The rate limiter keys on the raw TCP peer address. Behind any reverse
  proxy or typical PaaS deployment, every request's peer is the proxy
  itself, so the "per-client" budget collapses into one shared budget
  for the whole service. `X-Forwarded-For` is deliberately not trusted
  (spoofable without a known trusted proxy in front). See the
  [production checklist in `DEPLOYMENT.md`](DEPLOYMENT.md#production-checklist).
  This is the single most important thing to fix before a real-traffic
  public launch.
- Job completion is logged from a background thread, decoupled from the
  `Request` that queued it. `POST /jobs` threads its request ID through
  explicitly so the per-job completion log line still correlates back to
  the request that started it — the log line for an in-flight job's
  stage progress does not carry the same ID.
- No hard timeout on an in-flight analysis job — Python has no reliable
  cross-thread preemption, so the file/history caps above are the only
  mitigation against a pathological repo.
- `VITE_API_BASE` is baked into the frontend bundle at Docker build
  time, not configurable at container runtime — one built image is
  locked to one backend URL.
- `GET /health` returns HTTP 200 even when its DB check fails (reports
  `"degraded"` in the body) — a probe that only checks status code won't
  see a degraded dependency.
- Logging is plain-text (`logging.basicConfig`), not structured/JSON.
- Only one active job is tracked per browser via `localStorage`;
  multiple tabs each starting a different analysis will have the last
  write silently win.
- No job cancellation, retry, or history/listing UI — a failed job
  requires submitting a new one.

None of the above are hidden from the report itself where they affect
correctness (`files_capped`, `history_truncated`, and similar flags are
part of the API response) — this page exists so you don't have to read
19 design docs to find them.
