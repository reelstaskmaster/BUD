from types import SimpleNamespace

from app.services.memory import FACT_CATEGORIES, FORGET_DISTANCE, NEAR_DUPLICATE_DISTANCE


def test_memory_thresholds_are_ordered() -> None:
    assert 0 < NEAR_DUPLICATE_DISTANCE < FORGET_DISTANCE < 1


def test_fact_categories_are_closed() -> None:
    assert FACT_CATEGORIES == {"person", "interest", "preference", "name", "other"}


def test_forget_distance_is_reasonably_bounded() -> None:
    config = SimpleNamespace(forget_distance=FORGET_DISTANCE)
    assert 0 < config.forget_distance < 1
