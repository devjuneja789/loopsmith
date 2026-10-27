from app.pricing import price_for


def test_ten_percent_discount():
    assert price_for(100) == 90


def test_small_amount():
    assert price_for(50) == 45