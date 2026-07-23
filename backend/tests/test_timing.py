from app.timing import StageTimer


def test_forwards_every_call_to_the_wrapped_callback():
    seen: list[str] = []
    timer = StageTimer(seen.append)

    timer("cloning")
    timer("parsing")

    assert seen == ["cloning", "parsing"]


def test_works_with_no_wrapped_callback():
    timer = StageTimer()
    timer("cloning")
    timer("parsing")

    durations = timer.finish()
    assert set(durations.keys()) == {"cloning", "parsing", "total"}


def test_records_a_duration_for_each_completed_stage(monkeypatch):
    times = iter([0.0, 1.0, 3.0, 6.0])
    monkeypatch.setattr("app.timing.time.monotonic", lambda: next(times))

    timer = StageTimer()
    timer("cloning")  # started at t=1.0 (t=0.0 was __init__)
    timer("parsing")  # cloning ran 1.0 -> 3.0 = 2.0s; parsing starts at 3.0
    durations = timer.finish()  # parsing ran 3.0 -> 6.0 = 3.0s

    assert durations["cloning"] == 2.0
    assert durations["parsing"] == 3.0
    assert durations["total"] == 6.0


def test_finish_with_no_stages_entered_only_reports_total(monkeypatch):
    times = iter([0.0, 5.0])
    monkeypatch.setattr("app.timing.time.monotonic", lambda: next(times))

    timer = StageTimer()
    durations = timer.finish()

    assert durations == {"total": 5.0}
