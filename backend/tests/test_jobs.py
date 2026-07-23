from app.jobs import create_job, get_job, update_job


def test_create_job_returns_queued_record(tmp_path):
    db_path = tmp_path / "jobs.db"

    job_id = create_job("https://github.com/example/example", db_path=db_path)
    record = get_job(job_id, db_path=db_path)

    assert record is not None
    assert record.id == job_id
    assert record.repo_url == "https://github.com/example/example"
    assert record.status == "queued"
    assert record.stage is None
    assert record.markdown is None
    assert record.error is None


def test_get_job_returns_none_for_unknown_id(tmp_path):
    db_path = tmp_path / "jobs.db"
    create_job("https://github.com/example/example", db_path=db_path)

    assert get_job("does-not-exist", db_path=db_path) is None


def test_update_job_updates_only_given_fields(tmp_path):
    db_path = tmp_path / "jobs.db"
    job_id = create_job("https://github.com/example/example", db_path=db_path)

    update_job(job_id, status="running", stage="cloning_structure", db_path=db_path)
    record = get_job(job_id, db_path=db_path)
    assert record.status == "running"
    assert record.stage == "cloning_structure"
    assert record.markdown is None

    update_job(job_id, stage="parsing", db_path=db_path)
    record = get_job(job_id, db_path=db_path)
    assert record.status == "running"  # unchanged by the second call
    assert record.stage == "parsing"

    update_job(job_id, status="done", markdown="## Report", db_path=db_path)
    record = get_job(job_id, db_path=db_path)
    assert record.status == "done"
    assert record.markdown == "## Report"
    assert record.error is None


def test_update_job_can_record_an_error(tmp_path):
    db_path = tmp_path / "jobs.db"
    job_id = create_job("https://github.com/example/example", db_path=db_path)

    update_job(job_id, status="error", error="Repository clone timed out", db_path=db_path)
    record = get_job(job_id, db_path=db_path)

    assert record.status == "error"
    assert record.error == "Repository clone timed out"


def test_jobs_isolated_across_different_db_files(tmp_path):
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"

    job_id = create_job("https://github.com/example/example", db_path=db_a)

    assert get_job(job_id, db_path=db_a) is not None
    assert get_job(job_id, db_path=db_b) is None
