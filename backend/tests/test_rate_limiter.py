from app.rate_limiter import RateLimiter


def test_allows_requests_up_to_the_limit():
    limiter = RateLimiter(max_requests=3, window_seconds=60)

    assert limiter.allow("client-a", now=0)
    assert limiter.allow("client-a", now=1)
    assert limiter.allow("client-a", now=2)


def test_rejects_requests_beyond_the_limit_within_the_window():
    limiter = RateLimiter(max_requests=2, window_seconds=60)

    assert limiter.allow("client-a", now=0)
    assert limiter.allow("client-a", now=1)
    assert not limiter.allow("client-a", now=2)


def test_admits_again_once_old_hits_fall_outside_the_window():
    limiter = RateLimiter(max_requests=2, window_seconds=10)

    assert limiter.allow("client-a", now=0)
    assert limiter.allow("client-a", now=1)
    assert not limiter.allow("client-a", now=5)

    # both earlier hits (t=0, t=1) are now outside the 10s window at t=12
    assert limiter.allow("client-a", now=12)


def test_tracks_each_key_independently():
    limiter = RateLimiter(max_requests=1, window_seconds=60)

    assert limiter.allow("client-a", now=0)
    assert not limiter.allow("client-a", now=0)
    assert limiter.allow("client-b", now=0)
