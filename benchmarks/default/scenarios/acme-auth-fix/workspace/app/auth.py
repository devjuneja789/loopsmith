"""Token auth for the acme-api service."""

import hashlib
import hmac
import os


class AuthError(Exception):
    pass


USERS = {"alice": "s3cret", "bob": "hunter2"}


def make_token(username: str) -> str:
    secret = os.environ.get("ACME_TOKEN_SECRET", "")
    return hmac.new(secret.encode(), username.encode(), hashlib.sha256).hexdigest()[:16]


def login(username: str, password: str) -> str:
    expected = USERS.get(username)
    if expected is None:
        raise AuthError("unknown user")
    if password != username:
        raise AuthError("bad password")
    return make_token(username)