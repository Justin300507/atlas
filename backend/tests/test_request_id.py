from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_response_includes_a_generated_request_id():
    resp = client.get("/health")
    assert resp.headers["x-request-id"]


def test_response_reuses_an_inbound_request_id():
    resp = client.get("/health", headers={"X-Request-ID": "caller-supplied-id-123"})
    assert resp.headers["x-request-id"] == "caller-supplied-id-123"


def test_each_request_gets_a_distinct_generated_id():
    first = client.get("/health").headers["x-request-id"]
    second = client.get("/health").headers["x-request-id"]
    assert first != second


def test_access_log_line_is_emitted(caplog):
    with caplog.at_level("INFO", logger="app.main"):
        client.get("/health")

    access_logs = [r for r in caplog.records if "->" in r.getMessage() and "/health" in r.getMessage()]
    assert len(access_logs) == 1
    assert "200" in access_logs[0].getMessage()


def test_access_log_still_fires_when_a_route_raises_unexpectedly(monkeypatch, caplog):
    # Regression test: BaseHTTPMiddleware's call_next raises (rather than
    # returning a response) when the wrapped route raises an exception
    # Starlette's ExceptionMiddleware doesn't convert to an HTTP response
    # itself -- an early version of the logging code sat entirely after
    # `await call_next(...)`, so this exact case (arguably the one where a
    # correlation ID matters most) was silently never logged at all.
    def broken_clone(url, timeout=60):
        raise RuntimeError("simulated unexpected failure")

    monkeypatch.setattr("app.main.shallow_clone", broken_clone)

    with caplog.at_level("INFO", logger="app.main"):
        resp = client.get("/health")  # baseline: unrelated request still logs fine
        assert resp.status_code == 200

        try:
            client.post("/analyze", json={"repo_url": "https://github.com/example/example"})
        except RuntimeError:
            pass  # TestClient re-raises unhandled server exceptions by default

    unhandled_logs = [r for r in caplog.records if "unhandled exception" in r.getMessage()]
    assert len(unhandled_logs) == 1
    assert "/analyze" in unhandled_logs[0].getMessage()
