import pytest

from app.durations import parse_duration


def test_units_convert_to_seconds():
    assert parse_duration("90m") == 5400
    assert parse_duration("2h") == 7200
    assert parse_duration("45s") == 45
    assert parse_duration("0s") == 0


@pytest.mark.parametrize("bad", ["10x", "", "abc", "m"])
def test_invalid_inputs_raise(bad):
    with pytest.raises(ValueError):
        parse_duration(bad)