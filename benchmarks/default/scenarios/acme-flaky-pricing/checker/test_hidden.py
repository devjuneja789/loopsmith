from app.pricing import price_for


def test_prices_are_deterministic():
    assert {price_for(100) for _ in range(5)} == {90}


def test_small_amounts_are_deterministic():
    assert {price_for(50) for _ in range(5)} == {45}