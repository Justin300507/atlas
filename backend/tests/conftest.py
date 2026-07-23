import pytest

from app.main import _RATE_LIMITER


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    # TestClient sends every request from the same fake client host, so
    # unrelated tests sharing the module-level limiter would otherwise
    # trip each other's rate limit.
    _RATE_LIMITER.reset()
    yield
