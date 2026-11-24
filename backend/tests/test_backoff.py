import pytest

from minicop.ingest import Backoff


def test_doubles_up_to_cap_without_jitter():
    b = Backoff(base=1, cap=60, rand=lambda: 1.0)  # rand=1 -> 100% of nominal
    assert [b.next() for _ in range(8)] == [1, 2, 4, 8, 16, 32, 60, 60]


def test_jitter_stays_between_half_and_full():
    low = Backoff(base=1, cap=60, rand=lambda: 0.0)
    assert [low.next() for _ in range(3)] == [0.5, 1, 2]


def test_reset_starts_again():
    b = Backoff(base=1, cap=60, rand=lambda: 1.0)
    b.next(); b.next(); b.next()
    b.reset()
    assert b.next() == 1


@pytest.mark.parametrize("seed", range(20))
def test_random_delays_in_range(seed):
    import random
    rng = random.Random(seed)
    b = Backoff(base=1, cap=60, rand=rng.random)
    for attempt in range(10):
        nominal = min(60, 2**attempt)
        assert nominal / 2 <= b.next() <= nominal
