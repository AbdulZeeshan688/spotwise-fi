from spotwise.api.ratelimit import RateLimiter


def test_allows_limit_then_blocks_until_window_passes() -> None:
    now = [0.0]
    limiter = RateLimiter(2, clock=lambda: now[0])
    assert limiter.check("ip") == 0
    assert limiter.check("ip") == 0
    assert limiter.check("ip") > 0
    assert limiter.check("other-ip") == 0
    now[0] = 61.0
    assert limiter.check("ip") == 0
