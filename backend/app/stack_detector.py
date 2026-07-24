from __future__ import annotations

import json
from pathlib import Path

from .models import StackReport

_BACKEND_MARKERS = {
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "express": "Express",
}

_FRONTEND_MARKERS = {
    "next": "Next.js",
    "vue": "Vue",
    "svelte": "Svelte",
}

_DB_MARKERS = {
    "psycopg2": "PostgreSQL",
    "asyncpg": "PostgreSQL",
    "postgres": "PostgreSQL",
    "pymongo": "MongoDB",
    "mongoose": "MongoDB",
    "sqlite3": "SQLite",
}

_AUTH_MARKERS = {
    "pyjwt": "JWT",
    "jsonwebtoken": "JWT",
    "python-jose": "JWT",
}


# Manifest files are checked at the repo root AND one level into each
# top-level directory -- covers the common backend/ + frontend/ monorepo
# split (this is literally Atlas's own layout: backend/requirements.txt,
# frontend/package.json) without an unbounded recursive walk. Reported
# against a real repo whose manifest lived at backend/requirements.txt and
# was invisible to a root-only check, so a FastAPI backend with 107 real
# routes reported "Backend: Not detected" (2026-07-24).
_MANIFEST_EXCLUDED_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}


def _manifest_locations(repo_path: Path, name: str) -> list[Path]:
    locations = [repo_path / name]
    if repo_path.is_dir():
        for child in sorted(repo_path.iterdir()):
            if child.is_dir() and child.name not in _MANIFEST_EXCLUDED_DIRS:
                locations.append(child / name)
    return locations


def _read_text_files(repo_path: Path, names: list[str]) -> str:
    combined = ""
    for name in names:
        for f in _manifest_locations(repo_path, name):
            if f.exists():
                combined += f.read_text(errors="ignore").lower() + "\n"
    return combined


def _known_dir_names(repo_path: Path) -> set[str]:
    """Directory names at the repo root AND one level into each top-level
    directory -- same rationale as _manifest_locations: a backend/ +
    frontend/ split (or similar) puts routers/services/models one level
    deeper than a flat layout, so a root-only check misses it. Reported
    against a real repo with backend/services and backend/routes
    (2026-07-24)."""
    names: set[str] = set()
    if not repo_path.is_dir():
        return names
    for child in repo_path.iterdir():
        if not child.is_dir():
            continue
        names.add(child.name)
        if child.name in _MANIFEST_EXCLUDED_DIRS:
            continue
        for grandchild in child.iterdir():
            if grandchild.is_dir():
                names.add(grandchild.name)
    return names


def _package_json(repo_path: Path) -> dict:
    merged = {"dependencies": {}, "devDependencies": {}}
    found_any = False
    for f in _manifest_locations(repo_path, "package.json"):
        if not f.exists():
            continue
        try:
            data = json.loads(f.read_text(errors="ignore"))
        except json.JSONDecodeError:
            continue
        found_any = True
        merged["dependencies"].update(data.get("dependencies", {}))
        merged["devDependencies"].update(data.get("devDependencies", {}))
    return merged if found_any else {}


def detect(repo_path: Path) -> StackReport:
    py_manifest = _read_text_files(repo_path, ["requirements.txt", "pyproject.toml"])
    pkg = _package_json(repo_path)
    pkg_deps = " ".join(
        list(pkg.get("dependencies", {}).keys()) + list(pkg.get("devDependencies", {}).keys())
    ).lower()

    backend = None
    for marker, name in _BACKEND_MARKERS.items():
        if marker in py_manifest or marker in pkg_deps:
            backend = name
            break

    frontend = None
    if "react" in pkg_deps:
        frontend = "React + Vite" if "vite" in pkg_deps else "React"
    else:
        for marker, name in _FRONTEND_MARKERS.items():
            if marker in pkg_deps:
                frontend = name
                break

    combined = py_manifest + " " + pkg_deps
    database = next((name for marker, name in _DB_MARKERS.items() if marker in combined), None)
    auth = next((name for marker, name in _AUTH_MARKERS.items() if marker in combined), None)

    deployment = None
    if (repo_path / "Dockerfile").exists():
        deployment = "Docker"
    if (repo_path / "docker-compose.yml").exists() or (repo_path / "docker-compose.yaml").exists():
        deployment = "Docker Compose"

    # "routes" added alongside the existing "routers" -- both are common
    # naming conventions for the same thing (a real repo used "routes").
    architecture = None
    known_dirs = _known_dir_names(repo_path)
    if {"routers", "routes", "services", "models"} & known_dirs:
        architecture = "Layered / Service-Oriented"
    elif backend and frontend:
        # Weaker evidence than a recognized directory layout, but a repo
        # with both a detected backend and a detected frontend is still a
        # client-server split, not "Not detected" -- a real repo had
        # FastAPI + React + PostgreSQL + JWT + Docker all detected
        # individually, yet architecture stayed blank (2026-07-24).
        # Labeled explicitly as inferred (lower confidence than the
        # directory-layout match above) -- requested: extend the
        # high/low-confidence pattern already used for debt/performance
        # findings to inferred stack/architecture info too (2026-07-24).
        architecture = "Client-Server (inferred from detected backend + frontend, lower confidence)"

    return StackReport(
        backend=backend,
        frontend=frontend,
        database=database,
        auth=auth,
        deployment=deployment,
        architecture=architecture,
    )
