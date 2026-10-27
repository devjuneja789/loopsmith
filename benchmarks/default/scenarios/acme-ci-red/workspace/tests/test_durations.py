import pytest

from app.durations import parse_duration


def test_minutes_are_converted():
    assert parse_duration("90m") == 5400


def test_hours_are_converted():
    assert parse_duration("2h") == 7200


def test_seconds_pass_through():
    assert parse_duration("45s") == 45


def test_invalid_unit_is_rejected():
    with pytest.raises(ValueError):
        parse_duration("10x")