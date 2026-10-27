import os

REQUIRED = ("ACME_TOKEN_SECRET",)

missing = [key for key in REQUIRED if not os.environ.get(key)]
if missing:
    raise RuntimeError("missing test environment: " + ", ".join(missing))