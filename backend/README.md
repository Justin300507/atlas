# Atlas Backend (Phase 1: Repository Intelligence)

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

## Run

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload
```

## Try it

```bash
curl -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d "{\"repo_url\": \"https://github.com/octocat/Hello-World\"}"
```

## Test

```bash
# fast suite (no network)
.venv/Scripts/python -m pytest tests/ -m "not slow"

# full suite including real-network integration test
.venv/Scripts/python -m pytest tests/
```
