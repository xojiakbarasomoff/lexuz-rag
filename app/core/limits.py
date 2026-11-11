"""Public-demo guards backed by Redis (atomic Lua scripts).

- per-IP rate limit (per minute + per day; IPs are hashed, never stored raw)
- global concurrent LLM call slots (expiring, so a crashed worker frees its slot)
- daily AI budget with reserve → settle:
    1. reserve the worst-case estimated cost atomically before a provider call;
    2. settle with the actual usage afterwards (reserved -= est, spent += actual);
    3. a reservation that is never settled (worker crash) expires and is
       counted as *fully spent* — conservative, it may have been billed;
    4. when spent + reserved + new estimate > limit, new calls are refused.

If Redis is unavailable every guard raises GuardUnavailable and the API turns
public generation off (fail closed). Catalog endpoints keep working.

All amounts are *estimates* computed from configured prices.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

import redis

from app.core.config import Settings, get_settings

TASHKENT = ZoneInfo("Asia/Tashkent")
MICRO = 1_000_000


class GuardUnavailable(Exception):
    pass


class RateLimited(Exception):
    def __init__(self, scope: str, retry_after: int):
        super().__init__(scope)
        self.scope = scope
        self.retry_after = retry_after


class BudgetExceeded(Exception):
    pass


class Busy(Exception):
    pass


_RESERVE_LUA = """
-- KEYS[1]=totals hash, KEYS[2]=reservation hash, KEYS[3]=expiry zset
-- ARGV: now, amount, limit, ttl, id
local now = tonumber(ARGV[1])
local expired = redis.call('ZRANGEBYSCORE', KEYS[3], '-inf', now)
for _, rid in ipairs(expired) do
  local amt = tonumber(redis.call('HGET', KEYS[2], rid) or '0')
  redis.call('HINCRBY', KEYS[1], 'reserved', -amt)
  redis.call('HINCRBY', KEYS[1], 'spent', amt)
  redis.call('HINCRBY', KEYS[1], 'expired', 1)
  redis.call('HDEL', KEYS[2], rid)
  redis.call('ZREM', KEYS[3], rid)
end
local spent = tonumber(redis.call('HGET', KEYS[1], 'spent') or '0')
local reserved = tonumber(redis.call('HGET', KEYS[1], 'reserved') or '0')
local amount = tonumber(ARGV[2])
if spent + reserved + amount > tonumber(ARGV[3]) then
  return 0
end
redis.call('HINCRBY', KEYS[1], 'reserved', amount)
redis.call('HSET', KEYS[2], ARGV[5], amount)
redis.call('ZADD', KEYS[3], now + tonumber(ARGV[4]), ARGV[5])
for i = 1, 3 do redis.call('EXPIRE', KEYS[i], 259200) end
return 1
"""

_SETTLE_LUA = """
-- KEYS as above; ARGV: id, actual
local amt = redis.call('HGET', KEYS[2], ARGV[1])
if not amt then return 0 end  -- already expired and counted as spent
redis.call('HINCRBY', KEYS[1], 'reserved', -tonumber(amt))
redis.call('HINCRBY', KEYS[1], 'spent', tonumber(ARGV[2]))
redis.call('HDEL', KEYS[2], ARGV[1])
redis.call('ZREM', KEYS[3], ARGV[1])
return 1
"""

_SLOT_LUA = """
-- KEYS[1]=zset; ARGV: now, ttl, max, id
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', tonumber(ARGV[1]))
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then return 0 end
redis.call('ZADD', KEYS[1], tonumber(ARGV[1]) + tonumber(ARGV[2]), ARGV[4])
return 1
"""

_RATE_LUA = """
-- KEYS[1]=minute key, KEYS[2]=day key; ARGV: per_min, per_day
local m = redis.call('INCR', KEYS[1])
if m == 1 then redis.call('EXPIRE', KEYS[1], 60) end
local d = redis.call('INCR', KEYS[2])
if d == 1 then redis.call('EXPIRE', KEYS[2], 90000) end
if m > tonumber(ARGV[1]) then return 1 end
if d > tonumber(ARGV[2]) then return 2 end
return 0
"""


@lru_cache
def get_redis() -> redis.Redis:
    s = get_settings()
    return redis.Redis.from_url(s.redis_url, socket_timeout=2, socket_connect_timeout=2)


def usd_to_micro(usd: float) -> int:
    return int(round(usd * MICRO))


def _day(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(TASHKENT).strftime("%Y-%m-%d")


def hash_ip(ip: str) -> str:
    return hashlib.sha256(f"lexuz-rl:{ip}".encode()).hexdigest()[:20]


@dataclass
class Guards:
    r: redis.Redis
    settings: Settings

    def _call(self, fn, *args):
        try:
            return fn(*args)
        except redis.RedisError as exc:
            raise GuardUnavailable(type(exc).__name__) from exc

    # --- rate limit -------------------------------------------------------
    def check_rate(self, ip: str, now: float | None = None) -> None:
        now = now or time.time()
        h = hash_ip(ip)
        minute = int(now // 60)
        keys = [f"rl:m:{h}:{minute}", f"rl:d:{h}:{_day()}"]
        res = self._call(
            self.r.eval, _RATE_LUA, 2, *keys, self.settings.rate_limit_per_minute, self.settings.rate_limit_per_day
        )
        if res == 1:
            raise RateLimited("minute", 60 - int(now % 60))
        if res == 2:
            raise RateLimited("day", 3600)

    # --- concurrency --------------------------------------------------------
    def acquire_slot(self, call_id: str, now: float | None = None) -> None:
        now = now or time.time()
        ok = self._call(
            self.r.eval,
            _SLOT_LUA,
            1,
            "llm:slots",
            now,
            self.settings.llm_slot_ttl_s,
            self.settings.max_concurrent_llm_calls,
            call_id,
        )
        if not ok:
            raise Busy()

    def release_slot(self, call_id: str) -> None:
        try:
            self.r.zrem("llm:slots", call_id)
        except redis.RedisError:
            pass  # slot expires on its own

    # --- budget -------------------------------------------------------------
    def _budget_keys(self, scope: str) -> list[str]:
        base = f"budget:{scope}:{_day()}"
        return [base, f"{base}:res", f"{base}:exp"]

    def _limit(self, scope: str) -> float:
        return self.settings.daily_ingestion_budget_usd if scope == "ingestion" else self.settings.daily_ai_budget_usd

    def reserve(self, call_id: str, est_usd: float, scope: str = "public", now: float | None = None) -> None:
        now = now or time.time()
        ok = self._call(
            self.r.eval,
            _RESERVE_LUA,
            3,
            *self._budget_keys(scope),
            now,
            usd_to_micro(est_usd),
            usd_to_micro(self._limit(scope)),
            self.settings.budget_reservation_ttl_s,
            call_id,
        )
        if not ok:
            raise BudgetExceeded(scope)

    def settle(self, call_id: str, actual_usd: float, scope: str = "public") -> None:
        self._call(self.r.eval, _SETTLE_LUA, 3, *self._budget_keys(scope), call_id, usd_to_micro(actual_usd))

    def budget_state(self, scope: str = "public") -> dict:
        totals = self._call(self.r.hgetall, self._budget_keys(scope)[0])
        get = lambda k: int(totals.get(k.encode(), 0)) / MICRO  # noqa: E731
        return {
            "day": _day(),
            "limit_usd": self._limit(scope),
            "spent_usd": get("spent"),
            "reserved_usd": get("reserved"),
            "expired_reservations": int(totals.get(b"expired", 0)),
        }

    def ping(self) -> bool:
        try:
            return bool(self.r.ping())
        except redis.RedisError:
            return False


def get_guards() -> Guards:
    return Guards(get_redis(), get_settings())


def estimate_cost_usd(settings: Settings, input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens * settings.llm_input_price_per_mtok_usd + output_tokens * settings.llm_output_price_per_mtok_usd
    ) / 1_000_000
