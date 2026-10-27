import pytest

from app.auth import AuthError, login, make_token


def test_login_accepts_correct_password():
    assert login("alice", "s3cret") == make_token("alice")
    assert login("bob", "hunter2") == make_token("bob")


def test_login_rejects_bad_password():
    with pytest.raises(AuthError):
        login("alice", "wrong")


def test_login_rejects_unknown_user():
    with pytest.raises(AuthError):
        login("nobody", "x")