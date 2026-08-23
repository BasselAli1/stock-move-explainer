"""Tests for app.trigger.compute_pct_change and app.trigger.is_triggering_drop."""

import pytest

from app.trigger import compute_pct_change, is_triggering_drop


def test_compute_pct_change_for_a_drop():
    """A lower current close than previous close yields a negative percent."""
    assert compute_pct_change(220.00, 205.50) == pytest.approx(-6.5909, abs=1e-3)


def test_compute_pct_change_for_a_rise():
    """A higher current close than previous close yields a positive percent."""
    assert compute_pct_change(100.00, 115.00) == pytest.approx(15.0)


def test_compute_pct_change_no_move():
    """An unchanged close is exactly 0%."""
    assert compute_pct_change(150.00, 150.00) == 0.0


def test_compute_pct_change_rejects_non_positive_prev_close():
    """A zero or negative previous close makes percent change undefined."""
    with pytest.raises(ValueError):
        compute_pct_change(0, 100)
    with pytest.raises(ValueError):
        compute_pct_change(-10, 100)


def test_drop_exactly_at_threshold_triggers():
    """The threshold is inclusive: exactly -5% at a 5% threshold triggers."""
    assert is_triggering_drop(-5.0, 5) is True


def test_drop_just_under_threshold_does_not_trigger():
    """A drop just short of the threshold does not trigger."""
    assert is_triggering_drop(-4.99, 5) is False


def test_large_drop_triggers():
    """A drop well past the threshold triggers."""
    assert is_triggering_drop(-6.59, 5) is True


def test_rise_never_triggers_regardless_of_magnitude():
    """Only drops are triggers — a large rise must not trigger, per the
    project's drops-only design (see SPEC.md's "Decisions made" section:
    Risk Factors text can't plausibly explain an upward move)."""
    assert is_triggering_drop(15.0, 5) is False
    assert is_triggering_drop(50.0, 5) is False


def test_zero_change_does_not_trigger():
    """No move at all is never a trigger."""
    assert is_triggering_drop(0.0, 5) is False
