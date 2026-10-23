from conftest import FakeClock

from whatsapp_attendant.metrics import Metrics, percentile
from whatsapp_attendant.store import MessageLedger, TTLStore


def test_get_or_create_reuses_until_ttl():
    clock = FakeClock()
    store: TTLStore[list] = TTLStore(10, 100, clock)
    first, created = store.get_or_create("a", list)
    assert created
    again, created = store.get_or_create("a", list)
    assert again is first and not created
    clock.advance(11)
    fresh, created = store.get_or_create("a", list)
    assert created and fresh is not first


def test_least_recently_used_entries_are_dropped_beyond_capacity():
    store: TTLStore[int] = TTLStore(100, 2, FakeClock())
    store.get_or_create("a", lambda: 1)
    store.get_or_create("b", lambda: 2)
    store.get_or_create("a", lambda: 9)  # touch a
    store.get_or_create("c", lambda: 3)
    assert len(store) == 2 and sorted(store.values()) == [1, 3]


def test_get_and_set_respect_the_ttl_without_reordering():
    clock = FakeClock()
    store: TTLStore[int] = TTLStore(60, 100, clock)
    store.set("a", 1)
    clock.advance(30)
    store.set("b", 2)
    assert store.get("a") == 1  # a read does not refresh or move the entry
    clock.advance(31)
    assert store.get("a") is None and store.get("b") == 2
    store.set("c", 3)  # the write evicts the expired entry at the front
    assert len(store) == 2 and sorted(store.values()) == [2, 3]


def test_ca_16_ledger_claims_once_and_marks_after_success():
    ledger = MessageLedger(60, 100, max_attempts=3, clock=FakeClock())
    assert ledger.claim("wamid.1") is True
    assert ledger.claim("wamid.1") is False  # in flight: a redelivery is a duplicate
    ledger.complete("wamid.1")
    assert ledger.claim("wamid.1") is False  # done


def test_ca_16_ledger_releases_failures_and_dead_letters_at_the_limit():
    clock = FakeClock()
    ledger = MessageLedger(60, 100, max_attempts=2, clock=clock)
    assert ledger.claim("w") and ledger.fail("w") is False
    assert ledger.claim("w") is True  # released: the redelivery runs again
    assert ledger.fail("w") is True  # second failure: dead letter
    assert ledger.claim("w") is False
    clock.advance(61)
    assert ledger.claim("w") is True and len(ledger) == 1


def test_ca_16_duplicate_claims_keep_the_eviction_order():
    clock = FakeClock()
    ledger = MessageLedger(60, 100, max_attempts=3, clock=clock)
    ledger.claim("old")
    ledger.complete("old")
    clock.advance(30)
    ledger.claim("new")
    ledger.claim("old")  # duplicate: must not move "old" behind "new"
    clock.advance(31)
    ledger.claim("newest")  # evicts the expired "old" from the front
    assert len(ledger) == 2


def test_metrics_counters_and_percentiles():
    m = Metrics()
    m.inc("received", 3)
    for ms in (1.0, 2.0, 3.0, 4.0):
        m.observe_latency(ms)
    snap = m.snapshot()
    assert snap["received"] == 3 and snap["latency_p50_ms"] == 2.0 and snap["latency_p95_ms"] == 4.0
    assert percentile([], 95) == 0.0
    try:
        m.inc("unknown")
    except KeyError:
        pass
    else:  # pragma: no cover
        raise AssertionError("unknown counter accepted")
