# Contributing to Atlas

Atlas is in public beta and the backend is feature-frozen for now — the
highest-value contributions right now are bug fixes, documentation,
additional real-repository validation, and test coverage rather than new
analysis engines. If you want to build one of the "not yet built" pieces
in [`README.md`](README.md) / [`ROADMAP.md`](ROADMAP.md), open an issue
first so the scope is agreed before you write code.

## Local setup

**Backend** (Python 3.12+):

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate   # .venv/bin/activate on macOS/Linux
pip install -r requirements.txt -r requirements-dev.txt
```

**Frontend** (Node 20+):

```bash
cd frontend
npm install
```

Run both (`backend`: `uvicorn app.main:app --reload`, `frontend`: `npm run dev`)
or use `docker compose up --build` — see [`DEPLOYMENT.md`](DEPLOYMENT.md).

## Before opening a PR

Everything below is what [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
runs — run it locally first so CI isn't your linter:

```bash
# backend
cd backend
ruff check .
pytest -q                    # full suite, including the real-network test
pytest -q -m "not slow"      # fast loop, skips the live GitHub clone test

# frontend
cd frontend
npm run lint
npx tsc -b --noEmit
npm test -- --run
npm run build
```

[`docker-validate.yml`](.github/workflows/docker-validate.yml) additionally
proves the `docker-compose` stack builds and boots — it isn't something you
can easily run locally without Docker, so a passing PR check there is the
real signal.

## Design docs

Every non-trivial feature in this repo has a dated design doc under
[`docs/superpowers/specs/`](docs/superpowers/specs/) written *before* the
code, including its known limitations. If you're adding a new engine,
scoring rule, or anything with a non-obvious tradeoff, write one first
(a few paragraphs: problem, approach, limitations) — it's the difference
between a maintainer trusting a PR and re-deriving your reasoning from a
diff.

Bug fixes and doc-only changes don't need one.

## Code conventions

- No LLM calls in the analysis pipeline. Atlas's whole positioning is
  deterministic static analysis — see [`ARCHITECTURE.md`](ARCHITECTURE.md#why-deterministic-analysis-not-an-llm-wrapper).
  A PR that makes a scoring or detection result depend on a model call
  will be rejected regardless of how well it tests.
- Match existing patterns before introducing new ones (e.g. how
  `quality_engine.py` and `security_scanner.py` structure findings) —
  don't add a second convention for the same problem.
- New backend modules go in `backend/app/`, with tests in `backend/tests/`
  mirroring the module name (`test_<module>.py`).
- Prefer a failing test that reproduces the bug before fixing it.

## Reporting bugs / false positives

Atlas's credibility depends on findings being real. If you find a false
positive (a security finding, quality score, or graph edge that doesn't
hold up against the actual repo), that's a high-value bug report — please
include the repo/file/line and what you expected instead.

## Known limitations

See [`docs/superpowers/specs/`](docs/superpowers/specs/) (each design doc
documents its own limitations) and the benchmark docs under
[`docs/benchmarks/`](docs/benchmarks/) for what's measured vs. not. A
consolidated summary lives in [`FAQ.md`](FAQ.md#known-limitations).
