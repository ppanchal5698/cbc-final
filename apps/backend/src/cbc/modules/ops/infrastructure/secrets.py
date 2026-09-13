"""Provider credentials at rest, masked in transit, redacted from logs.

Three separate jobs, because a credential leaks in three different ways:

  * stored in Mongo, where a database dump would expose it
  * returned to the browser by the settings screen
  * echoed into a job log, which the UI renders and Mongo keeps

Encryption here protects the first. `mask` protects the second. `redact`
protects the third, and is the one that is easy to forget - `worker/main.py`
stores 8000 characters of Claude's output on every job.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:"

# Anything shaped like a credential, whoever emitted it. Deliberately broad: a
# false positive costs an unreadable log line, a false negative leaks a key.
_PATTERNS = (
    re.compile(r"sk-ant-[A-Za-z0-9\-_]{16,}"),
    re.compile(r"sk-or-[A-Za-z0-9\-_]{16,}"),
    re.compile(r"sk-[A-Za-z0-9\-_]{24,}"),
    re.compile(r"nvapi-[A-Za-z0-9\-_]{16,}"),
    re.compile(r"ABSK[A-Za-z0-9+/=]{16,}"),  # Bedrock API key
    re.compile(r"\bASIA[A-Z0-9]{16}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
)


def _key() -> bytes:
    """Derive a Fernet key from APP_SECRET_KEY.

    Fernet needs 32 url-safe base64 bytes; a human-set secret is neither, so it
    is hashed rather than rejected. The alternative is refusing to start on a
    perfectly reasonable passphrase.
    """
    raw = os.environ.get("APP_SECRET_KEY", "cbc-local-dev-key-change-me")
    return base64.urlsafe_b64encode(hashlib.sha256(raw.encode("utf-8")).digest())


def encrypt(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith(PREFIX):  # already encrypted; do not double-wrap
        return value
    return PREFIX + Fernet(_key()).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str | None) -> str | None:
    """Return the plaintext, or None when it cannot be read.

    A changed APP_SECRET_KEY makes every stored credential undecryptable. That
    is reported as "not configured" rather than raising, so the settings screen
    still loads and the estimator can simply re-enter it.
    """
    if not value:
        return None
    if not value.startswith(PREFIX):
        return value  # written before encryption, or injected from the environment
    try:
        return Fernet(_key()).decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def mask(value: str | None) -> str | None:
    """What the settings screen is allowed to see: enough to recognise, not to use."""
    plain = decrypt(value)
    if not plain:
        return None
    if len(plain) <= 8:
        return "*" * len(plain)
    return f"{plain[:4]}{'*' * 8}{plain[-4:]}"


def redact(text: str, extra: list[str] | None = None) -> str:
    """Strip credentials out of captured output before it is stored or shown.

    `extra` carries the values actually in play for this run, which catches a
    credential shaped like nothing recognisable - a gateway bearer token can be
    any string at all.
    """
    if not text:
        return text
    for secret in extra or []:
        if secret and len(secret) >= 8:
            text = text.replace(secret, "[redacted]")
    for pattern in _PATTERNS:
        text = pattern.sub("[redacted]", text)
    return text
