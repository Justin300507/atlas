# Atlas

AI Engineering Intelligence Platform — paste a GitHub repo, get a full engineering
review instead of a chatbot.

Atlas is being built in phases. Phase 1 (this repo's current state) is **Repository
Intelligence + Architecture Graph**: given a public GitHub URL, Atlas clones it,
detects its tech stack, and builds a module/import/route dependency graph, served as
JSON from a FastAPI backend.

See `docs/superpowers/specs/` for design docs and `docs/superpowers/plans/` for
implementation plans.

## Phase 1: Repository Intelligence

See [`backend/README.md`](backend/README.md) to run it locally.

## Roadmap

Later phases (not yet built): Code Quality Engine, AI Architect, Security Scanner,
Technical Debt Analyzer, Documentation Generator, Git Intelligence, Performance
Analyzer, AI Mentor, and a frontend UI.
