from ratelimiter import RateLimiter

limiter = RateLimiter(max_calls=32, period=1)
