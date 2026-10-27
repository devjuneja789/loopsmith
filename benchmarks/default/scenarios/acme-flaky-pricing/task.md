# Make the pricing suite deterministic

`tests/test_pricing.py` is flaky: it sometimes passes and sometimes fails.
Make the suite deterministic while preserving the documented behaviour
(all prices carry the standard 10% discount).