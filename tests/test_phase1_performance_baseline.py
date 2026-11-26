import pytest

from scripts.run_phase1_performance_baseline import (
    DEFAULT_SCALES,
    _percentile,
    _validate_database_target,
)


def test_default_performance_scales_cover_acceptance_matrix() -> None:
    assert DEFAULT_SCALES == (1, 3, 5, 10, 20)


@pytest.mark.parametrize(
    ("values", "percentile", "expected"),
    [([1.0], 0.95, 1.0), ([1.0, 2.0, 3.0], 0.50, 2.0)],
)
def test_percentile(values: list[float], percentile: float, expected: float) -> None:
    assert _percentile(values, percentile) == expected


def test_database_guard_requires_test_name_and_explicit_confirmation() -> None:
    production = "postgresql+psycopg://user:secret@localhost/crypto_lab_local"
    test_database = "postgresql+psycopg://user:secret@localhost/crypto_lab_test"
    with pytest.raises(ValueError, match="does not contain 'test'"):
        _validate_database_target(production, True)
    with pytest.raises(ValueError, match="confirm-reset-test-database"):
        _validate_database_target(test_database, False)
    assert _validate_database_target(test_database, True) == test_database
