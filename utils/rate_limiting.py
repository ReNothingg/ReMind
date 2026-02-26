import os
import time
import logging
from dataclasses import dataclass
from functools import wraps
from collections import defaultdict
from threading import Lock

from flask import make_response, request, session

rate_limit_store = defaultdict(list)
rate_limit_lock = Lock()


@dataclass(frozen=True)
class RateLimitState:
    allowed: bool
    limit: int
    remaining: int
    reset_at: int


class RateLimiter:
    REDIS_LUA = """
local key = KEYS[1]
local seq_key = key .. ':seq'

local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local window_start = now - window

redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)

local count = redis.call('ZCARD', key)
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local reset_at = now + window
if oldest[2] then
  reset_at = tonumber(oldest[2]) + window
end

if count >= limit then
  return {0, limit, 0, math.floor(reset_at)}
end

local seq = redis.call('INCR', seq_key)
local member = tostring(now) .. '-' .. tostring(seq)
redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window)
redis.call('EXPIRE', seq_key, window)

count = redis.call('ZCARD', key)
oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
reset_at = now + window
if oldest[2] then
  reset_at = tonumber(oldest[2]) + window
end

local remaining = limit - count
if remaining < 0 then
  remaining = 0
end

return {1, limit, remaining, math.floor(reset_at)}
"""

    def __init__(self, max_requests=100, time_window=3600, use_redis=None):
        self.max_requests = max_requests
        self.time_window = time_window
        if use_redis is None:
            use_redis = bool(os.getenv("REDIS_URL"))

        self.use_redis = use_redis
        self.redis_client = None
        self._redis_script = None

        if use_redis:
            try:
                import redis

                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()
                self._redis_script = self.redis_client.register_script(self.REDIS_LUA)
            except Exception:
                self.use_redis = False
                logging.getLogger("remind").warning(
                    "Redis not available, falling back to in-memory rate limiting"
                )

    def get_identifier(self, request_obj):
        try:
            if session and "user_id" in session:
                return f"user_{session.get('user_id')}"
        except RuntimeError:
            pass
        return f"ip_{request_obj.remote_addr}"

    def evaluate(self, identifier):
        now = int(time.time())
        if self.use_redis and self.redis_client is not None and self._redis_script is not None:
            return self._evaluate_redis(identifier, now)
        return self._evaluate_memory(identifier, now)

    def is_allowed(self, identifier):
        return self.evaluate(identifier).allowed

    def _evaluate_memory(self, identifier, now):
        window_start = now - self.time_window

        with rate_limit_lock:
            requests_in_window = [ts for ts in rate_limit_store[identifier] if ts > window_start]
            rate_limit_store[identifier] = requests_in_window

            if len(requests_in_window) >= self.max_requests:
                oldest = min(requests_in_window) if requests_in_window else now
                reset_at = int(oldest + self.time_window)
                return RateLimitState(
                    allowed=False,
                    limit=self.max_requests,
                    remaining=0,
                    reset_at=reset_at,
                )

            requests_in_window.append(now)
            rate_limit_store[identifier] = requests_in_window
            remaining = max(0, self.max_requests - len(requests_in_window))
            oldest = min(requests_in_window) if requests_in_window else now
            reset_at = int(oldest + self.time_window)
            return RateLimitState(
                allowed=True,
                limit=self.max_requests,
                remaining=remaining,
                reset_at=reset_at,
            )

    def _evaluate_redis(self, identifier, now):
        key = f"ratelimit:{identifier}"
        try:
            raw = self._redis_script(keys=[key], args=[now, self.time_window, self.max_requests])
            allowed = bool(int(raw[0]))
            limit = int(raw[1])
            remaining = int(raw[2])
            reset_at = int(raw[3])
            return RateLimitState(
                allowed=allowed,
                limit=limit,
                remaining=max(0, remaining),
                reset_at=max(now, reset_at),
            )
        except Exception:
            logging.getLogger("remind").warning(
                "Redis rate limit script failed, request allowed",
                exc_info=True,
            )
            return RateLimitState(
                allowed=True,
                limit=self.max_requests,
                remaining=self.max_requests,
                reset_at=now + self.time_window,
            )

    def get_remaining_requests(self, identifier):
        return self.evaluate(identifier).remaining


login_limiter = RateLimiter(max_requests=5, time_window=300)
password_reset_limiter = RateLimiter(max_requests=3, time_window=3600)
api_limiter = RateLimiter(max_requests=100, time_window=3600)
upload_limiter = RateLimiter(max_requests=20, time_window=3600)


def _headers_from_state(state):
    return {
        "X-RateLimit-Limit": str(state.limit),
        "X-RateLimit-Remaining": str(max(0, state.remaining)),
        "X-RateLimit-Reset": str(max(int(time.time()), int(state.reset_at))),
    }


def _inject_rate_headers(response, state):
    for key, value in _headers_from_state(state).items():
        response.headers[key] = value
    return response


def rate_limit(limiter, error_message="Too many requests"):
    def decorator(view_func):
        @wraps(view_func)
        def decorated_function(*args, **kwargs):
            identifier = limiter.get_identifier(request)
            state = limiter.evaluate(identifier)

            if not state.allowed:
                from utils.responses import make_error

                blocked = make_response(
                    make_error(
                        error_message,
                        status=429,
                        code="rate_limit_exceeded",
                        extra={"remaining_requests": state.remaining},
                    )
                )
                retry_after = max(1, state.reset_at - int(time.time()))
                blocked.headers["Retry-After"] = str(retry_after)
                return _inject_rate_headers(blocked, state)

            result = view_func(*args, **kwargs)
            response = make_response(result)
            return _inject_rate_headers(response, state)

        return decorated_function

    return decorator


def get_rate_limit_headers(limiter, identifier):
    state = limiter.evaluate(identifier)
    return _headers_from_state(state)
