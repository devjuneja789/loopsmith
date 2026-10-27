import pytest

from app.auth import AuthError, login, make_token


def test_valid_login_returns_verifiable_token():
    token = login("alice", "s3cret")
    assert token == make_token("alice")


def test_wrong_password_is_rejected():
    with pytest.raises(AuthError):
        login("alice", "nope")


def test_unknown_user_is_rejected():
    with pytest.raises(AuthError):
        login("mallory", "x")