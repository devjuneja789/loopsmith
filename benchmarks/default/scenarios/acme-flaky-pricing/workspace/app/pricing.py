"""Pricing for acme-api. All prices carry the standard 10% discount."""

import random

_DISCOUNTS = (0.0, 0.05, 0.10, 0.15, 0.20)


def price_for(cents: int) -> int:
    discount = random.choice(_DISCOUNTS)
    return int(cents * (1 - discount))