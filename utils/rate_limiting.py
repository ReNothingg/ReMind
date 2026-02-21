
import time
import os
from functools import wraps
from flask import request, current_app, session
from collections import defaultdict
from threading import Lock
rate_limit_store = defaultdict(list)
rate_limit_lock = Lock()


class RateLimiter:


    def __init__(self, max_requests=100, time_window=3600, use_redis=None):
        self.max_requests = max_requests
        self.time_window = time_window
        if use_redis is None:
            use_redis = bool(os.getenv("REDIS_URL"))

        self.use_redis = use_redis
        self.redis_client = None

        if use_redis:
            try:
                import redis
                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                self.redis_client = redis.from_url(redis_url)
                self.redis_client.ping()
            except Exception:
                self.use_redis = False
                import logging
                logging.getLogger('remind').warning('Redis not available, falling back to in-memory rate limiting')

    def get_identifier(self, request_obj):

        try:
            if session and 'user_id' in session:
                return f"user_{session.get('user_id')}"
        except RuntimeError:
            pass
        return f"ip_{request_obj.remote_addr}"

    def is_allowed(self, identifier):

        current_time = time.time()
        window_start = current_time - self.time_window

        if self.use_redis:
            return self._is_allowed_redis(identifier, current_time, window_start)
        else:
            return self._is_allowed_memory(identifier, current_time, window_start)

    def _is_allowed_memory(self, identifier, current_time, window_start):

        with rate_limit_lock:
            requests_in_window = [
                ts for ts in rate_limit_store[identifier]
                if ts > window_start
            ]
            rate_limit_store[identifier] = requests_in_window
            if len(requests_in_window) >= self.max_requests:
                return False
            rate_limit_store[identifier].append(current_time)
            return True

    def _is_allowed_redis(self, identifier, current_time, window_start):

        try:
            key = f"ratelimit:{identifier}"
            pipe = self.redis_client.pipeline()
            pipe.zremrangebyscore(key, '-inf', window_start)
            pipe.zcard(key)
            pipe.zadd(key, {str(current_time): current_time})
            pipe.expire(key, self.time_window)

            results = pipe.execute()
            request_count = results[1]

            return request_count < self.max_requests
        except Exception:
            import logging
            logging.getLogger('remind').warning('Redis rate limit error, allowing request')
            return True

    def get_remaining_requests(self, identifier):

        current_time = time.time()
        window_start = current_time - self.time_window

        with rate_limit_lock:
            requests_in_window = [
                ts for ts in rate_limit_store[identifier]
                if ts > window_start
            ]

        return max(0, self.max_requests - len(requests_in_window))
login_limiter = RateLimiter(max_requests=5, time_window=300)  # 5 attempts per 5 minutes
password_reset_limiter = RateLimiter(max_requests=3, time_window=3600)  # 3 per hour
api_limiter = RateLimiter(max_requests=100, time_window=3600)  # 100 per hour
upload_limiter = RateLimiter(max_requests=20, time_window=3600)  # 20 uploads per hour


def rate_limit(limiter, error_message='Too many requests'):
    def decorator(view_func):
        @wraps(view_func)
        def decorated_function(*args, **kwargs):
            identifier = limiter.get_identifier(request)

            if not limiter.is_allowed(identifier):
                remaining = limiter.get_remaining_requests(identifier)
                from utils.responses import make_error
                return make_error(
                    error_message,
                    status=429,
                    code='rate_limit_exceeded',
                    extra_data={'remaining_requests': remaining}
                ), 429

            return view_func(*args, **kwargs)

        return decorated_function

    return decorator


def get_rate_limit_headers(limiter, identifier):

    remaining = limiter.get_remaining_requests(identifier)
    return {
        'X-RateLimit-Limit': str(limiter.max_requests),
        'X-RateLimit-Remaining': str(remaining),
        'X-RateLimit-Reset': str(int(time.time()) + limiter.time_window),
    }
