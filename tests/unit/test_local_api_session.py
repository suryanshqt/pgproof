"""The loopback session token: unguessable and non-repeating."""

from pgproof.local_api.session import new_session_token


def test_token_is_reasonably_long() -> None:
    assert len(new_session_token()) >= 32


def test_tokens_are_practically_unique() -> None:
    tokens = {new_session_token() for _ in range(200)}
    assert len(tokens) == 200


def test_token_is_url_safe() -> None:
    token = new_session_token()
    assert all(char.isalnum() or char in "-_" for char in token)
