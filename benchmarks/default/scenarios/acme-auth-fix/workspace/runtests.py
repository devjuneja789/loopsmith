"""Project test entrypoint: loads the test environment, then runs pytest."""

import os
import subprocess
import sys


def main(argv: list[str]) -> int:
    os.environ.setdefault("ACME_TOKEN_SECRET", "test-secret")
    os.environ.setdefault("ACME_TIMEZONE", "UTC")
    return subprocess.call([sys.executable, "-m", "pytest", "-q", *argv])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))