import time
import hashlib
from functools import wraps
from flask import request, session
from collections import defaultdict
from threading import Lock
import os
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_DURATION = 900  # 15 minutes
PROGRESSIVE_LOCKOUT = True  # Increase lockout time with each lockout
MAX_LOCKOUT_DURATION = 3600  # 1 hour maximum
_attempt_store = defaultdict(list)
_lockout_store = {}
_store_lock = Lock()


class BruteForceProtection:
    def __init__(self, max_attempts=MAX_LOGIN_ATTEMPTS, lockout_duration=LOCKOUT_DURATION,
                 use_redis=None, progressive=PROGRESSIVE_LOCKOUT):
        self.max_attempts = max_attempts
        self.base_lockout_duration = lockout_duration
        self.progressive = progressive
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

    def _get_identifier(self, identifier_type='email', identifier_value=None):
        ip = request.remote_addr if request else 'unknown'

        if identifier_type == 'ip':
            return f"bf:ip:{ip}"
        elif identifier_type == 'email' and identifier_value:
            email_hash = hashlib.sha256(identifier_value.lower().encode()).hexdigest()[:16]
            return f"bf:email:{email_hash}"
        elif identifier_type == 'combined' and identifier_value:
            email_hash = hashlib.sha256(identifier_value.lower().encode()).hexdigest()[:16]
            ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:8]
            return f"bf:combined:{email_hash}:{ip_hash}"

        return f"bf:ip:{ip}"

    def _get_lockout_duration(self, identifier):
        if not self.progressive:
            return self.base_lockout_duration
        lockout_count = self._get_lockout_count(identifier)
        duration = self.base_lockout_duration * (2 ** lockout_count)

        return min(duration, MAX_LOCKOUT_DURATION)

    def _get_lockout_count(self, identifier):
        if self.use_redis:
            try:
                count = self.redis_client.get(f"{identifier}:lockout_count")
                return int(count) if count else 0
            except Exception:
                return 0
        else:
            with _store_lock:
                return _lockout_store.get(f"{identifier}:count", 0)

    def is_locked(self, identifier_type='email', identifier_value=None):
        identifier = self._get_identifier(identifier_type, identifier_value)

        if self.use_redis:
            return self._is_locked_redis(identifier)
        else:
            return self._is_locked_memory(identifier)

    def _is_locked_memory(self, identifier):

        with _store_lock:
            lockout_until = _lockout_store.get(identifier)
            if lockout_until:
                remaining = lockout_until - time.time()
                if remaining > 0:
                    return True, int(remaining)
                else:
                    del _lockout_store[identifier]
        return False, 0

    def _is_locked_redis(self, identifier):

        try:
            lockout_until = self.redis_client.get(f"{identifier}:lockout")
            if lockout_until:
                remaining = float(lockout_until) - time.time()
                if remaining > 0:
                    return True, int(remaining)
        except Exception:
            pass
        return False, 0

    def record_attempt(self, identifier_type='email', identifier_value=None, success=False):
        identifier = self._get_identifier(identifier_type, identifier_value)

        if success:
            self._clear_attempts(identifier)
            return False, self.max_attempts

        if self.use_redis:
            return self._record_attempt_redis(identifier)
        else:
            return self._record_attempt_memory(identifier)

    def _record_attempt_memory(self, identifier):

        current_time = time.time()
        window_start = current_time - 3600  # 1 hour window

        with _store_lock:
            _attempt_store[identifier] = [
                ts for ts in _attempt_store[identifier]
                if ts > window_start
            ]
            _attempt_store[identifier].append(current_time)

            attempt_count = len(_attempt_store[identifier])

            if attempt_count >= self.max_attempts:
                lockout_duration = self._get_lockout_duration(identifier)
                _lockout_store[identifier] = current_time + lockout_duration
                _lockout_store[f"{identifier}:count"] = self._get_lockout_count(identifier) + 1
                _attempt_store[identifier] = []

                return True, 0

            return False, self.max_attempts - attempt_count

    def _record_attempt_redis(self, identifier):

        try:
            current_time = time.time()
            key = f"{identifier}:attempts"

            pipe = self.redis_client.pipeline()
            pipe.zadd(key, {str(current_time): current_time})
            pipe.zremrangebyscore(key, '-inf', current_time - 3600)
            pipe.zcard(key)
            pipe.expire(key, 3600)

            results = pipe.execute()
            attempt_count = results[2]

            if attempt_count >= self.max_attempts:
                lockout_duration = self._get_lockout_duration(identifier)
                lockout_until = current_time + lockout_duration

                self.redis_client.setex(
                    f"{identifier}:lockout",
                    int(lockout_duration),
                    str(lockout_until)
                )
                self.redis_client.incr(f"{identifier}:lockout_count")
                self.redis_client.expire(f"{identifier}:lockout_count", 86400 * 7)  # 7 days
                self.redis_client.delete(key)

                return True, 0

            return False, self.max_attempts - attempt_count

        except Exception:
            return False, self.max_attempts

    def _clear_attempts(self, identifier):

        if self.use_redis:
            try:
                self.redis_client.delete(f"{identifier}:attempts")
            except Exception:
                pass
        else:
            with _store_lock:
                _attempt_store[identifier] = []
brute_force_protection = BruteForceProtection()


def check_brute_force(identifier_type='email'):
    def decorator(view_func):
        @wraps(view_func)
        def decorated_function(*args, **kwargs):
            identifier_value = None
            if identifier_type in ('email', 'combined'):
                if request.is_json:
                    data = request.get_json(silent=True) or {}
                    identifier_value = data.get('email', '').lower()
                else:
                    identifier_value = request.form.get('email', '').lower()
            is_locked, remaining = brute_force_protection.is_locked(
                identifier_type, identifier_value
            )

            if is_locked:
                from utils.responses import make_error
                from utils.audit_log import log_security_event, AuditEvents

                log_security_event(AuditEvents.SECURITY_BRUTE_FORCE, {
                    'identifier_type': identifier_type,
                    'remaining_lockout': remaining
                })

                return make_error(
                    f"Too many failed attempts. Try again in {remaining // 60 + 1} minutes.",
                    status=429,
                    code='account_locked'
                ), 429

            return view_func(*args, **kwargs)

        return decorated_function
    return decorator


def record_login_attempt(email, success):
    brute_force_protection.record_attempt('email', email, success)
    brute_force_protection.record_attempt('ip', None, success)

    if not success:
        brute_force_protection.record_attempt('combined', email, success)
