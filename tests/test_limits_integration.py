"""Rate limit, concurrency slots and budget reservation against real Redis."""

import threading

import pytest
import redis

from app.core.limits import BudgetExceeded, Busy, Guards, GuardUnavailable, RateLimited

pytestmark = pytest.mark.integration


def guards(r, settings):
    return Guards(r, settings)


def test_rate_limit_per_minute(redis_client, settings):
    g = guards(redis_client, settings.model_copy(update={"rate_limit_per_minute": 3, "rate_limit_per_day": 100}))
    for _ in range(3):
        g.check_rate("203.0.113.7", now=1_000_020)
    with pytest.raises(RateLimited) as e:
        g.check_rate("203.0.113.7", now=1_000_030)
    assert e.value.scope == "minute" and 0 < e.value.retry_after <= 60
    g.check_rate("198.51.100.1", now=1_000_030)  # other IP unaffected
    g.check_rate("203.0.113.7", now=1_000_090)  # next minute window


def test_rate_limit_per_day(redis_client, settings):
    g = guards(redis_client, settings.model_copy(update={"rate_limit_per_minute": 100, "rate_limit_per_day": 2}))
    g.check_rate("203.0.113.8", now=2_000_000)
    g.check_rate("203.0.113.8", now=2_000_100)
    with pytest.raises(RateLimited) as e:
        g.check_rate("203.0.113.8", now=2_000_200)
    assert e.value.scope == "day"


def test_ip_is_not_stored_in_clear(redis_client, settings):
    guards(redis_client, settings).check_rate("203.0.113.9")
    assert not [k for k in redis_client.keys("*") if b"203.0.113.9" in k]


def test_parallel_budget_reservation_never_overspends(redis_client, settings):
    g = guards(redis_client, settings.model_copy(update={"daily_ai_budget_usd": 1.0}))
    ok, refused = [], []
    barrier = threading.Barrier(20)

    def worker(i):
        barrier.wait()
        try:
            g.reserve(f"call-{i}", 0.3)
            ok.append(i)
        except BudgetExceeded:
            refused.append(i)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(ok) == 3 and len(refused) == 17  # 3 * 0.3 <= 1.0 < 4 * 0.3
    state = g.budget_state()
    assert state["reserved_usd"] == pytest.approx(0.9)


def test_settle_replaces_estimate_with_actual(redis_client, settings):
    g = guards(redis_client, settings.model_copy(update={"daily_ai_budget_usd": 1.0}))
    g.reserve("a", 0.6)
    g.settle("a", 0.05)
    st = g.budget_state()
    assert st["reserved_usd"] == 0 and st["spent_usd"] == pytest.approx(0.05)
    g.reserve("b", 0.9)  # room again after settlement


def test_crashed_reservation_expires_as_spent(redis_client, settings):
    g = guards(redis_client, settings.model_copy(update={"daily_ai_budget_usd": 1.0, "budget_reservation_ttl_s": 10}))
    g.reserve("crashed", 0.7, now=1000)
    with pytest.raises(BudgetExceeded):
        g.reserve("next", 0.5, now=1005)
    with pytest.raises(BudgetExceeded):
        g.reserve("later", 0.5, now=1011)  # expired -> counted as fully spent (conservative)
    st = g.budget_state()
    assert st["spent_usd"] == pytest.approx(0.7) and st["expired_reservations"] == 1
    g.settle("crashed", 0.01)  # late settle of an expired reservation is a no-op
    assert g.budget_state()["spent_usd"] == pytest.approx(0.7)


def test_ingestion_has_a_separate_budget(redis_client, settings):
    g = guards(
        redis_client, settings.model_copy(update={"daily_ai_budget_usd": 0.1, "daily_ingestion_budget_usd": 1.0})
    )
    g.reserve("ing", 0.5, scope="ingestion")
    with pytest.raises(BudgetExceeded):
        g.reserve("pub", 0.5, scope="public")


def test_concurrency_slots(redis_client, settings):
    g = guards(redis_client, settings.model_copy(update={"max_concurrent_llm_calls": 2, "llm_slot_ttl_s": 30}))
    g.acquire_slot("x", now=100)
    g.acquire_slot("y", now=100)
    with pytest.raises(Busy):
        g.acquire_slot("z", now=101)
    g.release_slot("x")
    g.acquire_slot("z", now=102)
    g.acquire_slot("w", now=200)  # expired slots are reclaimed


def test_redis_outage_fails_closed(settings):
    dead = redis.Redis(host="127.0.0.1", port=1, socket_connect_timeout=0.2, socket_timeout=0.2)
    g = Guards(dead, settings)
    with pytest.raises(GuardUnavailable):
        g.check_rate("203.0.113.1")
    with pytest.raises(GuardUnavailable):
        g.reserve("c", 0.01)
    assert g.ping() is False
