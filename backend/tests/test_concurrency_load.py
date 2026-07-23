import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app import main as app_main
from app.main import app
from app.rate_limiter import RateLimiter
from scripts.generate_synthetic_repo import generate_synthetic_repo

client = TestClient(app)


def test_concurrent_job_creation_respects_the_capacity_cap_and_all_accepted_jobs_finish(
    tmp_path, monkeypatch
):
    # What's under test here is Atlas's own concurrency machinery (the
    # _MAX_ACTIVE_JOBS cap, the job ThreadPoolExecutor, concurrent SQLite
    # writes) -- not clone performance, so this deliberately uses a local
    # fixture instead of 12 real concurrent GitHub clones.
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr("app.main._RATE_LIMITER", RateLimiter(max_requests=100, window_seconds=60))

    repo = generate_synthetic_repo(tmp_path / "repo", target_loc=500)

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        # The synthetic fixture is tiny and analysis finishes in well under
        # a second -- fast enough that, without this delay, earlier jobs
        # would complete and free up capacity before all `request_count`
        # requests even finish submitting, so the cap would never actually
        # face `request_count` truly-concurrent in-flight jobs. The delay
        # ensures a real peak-concurrency window exists to test against.
        time.sleep(0.5)
        yield repo

    monkeypatch.setattr("app.report_pipeline.clone_with_history", fake_clone_with_history)

    request_count = 12
    max_active = app_main._MAX_ACTIVE_JOBS

    def submit(i: int):
        return client.post("/jobs", json={"repo_url": f"https://github.com/example/repo-{i}"})

    with ThreadPoolExecutor(max_workers=request_count) as pool:
        responses = list(pool.map(submit, range(request_count)))

    statuses = [r.status_code for r in responses]
    accepted = [r for r in responses if r.status_code == 202]
    rejected = [r for r in responses if r.status_code == 429]

    assert len(accepted) == max_active, statuses
    assert len(rejected) == request_count - max_active, statuses

    job_ids = [r.json()["job_id"] for r in accepted]

    deadline = time.monotonic() + 30
    pending = set(job_ids)
    while pending and time.monotonic() < deadline:
        for job_id in list(pending):
            record = client.get(f"/jobs/{job_id}").json()
            if record["status"] in ("done", "error"):
                pending.discard(job_id)
        if pending:
            time.sleep(0.1)

    assert not pending, f"jobs never finished: {pending}"

    final_records = [client.get(f"/jobs/{job_id}").json() for job_id in job_ids]
    errors = [r for r in final_records if r["status"] == "error"]
    assert errors == [], errors
    assert all(r["status"] == "done" and r["markdown"] for r in final_records)
