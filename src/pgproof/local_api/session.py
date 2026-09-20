"""The loopback session token.

`docs/ARCHITECTURE.md` section 9: "an unguessable session token delivered in
the opened URL." `secrets.token_urlsafe` draws from the OS CSPRNG, which is
what "unguessable" requires.
"""

from __future__ import annotations

import secrets

SESSION_TOKEN_BYTES = 32


def new_session_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)
