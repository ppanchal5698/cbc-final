"""Reaching a compose MongoDB from outside the compose network.

The single-node replica set advertises its member as `mongo:27017`, the name it
has inside compose. A driver on the host connects to the published port,
discovers that member, and then cannot resolve it: every connection waited out
its server-selection timeout and failed - the reference store fell back to seed
files three seconds a read, the page index could not be read at all. The tests
had worked around it with their own copy of this; the backend's clients did not.

`directConnection` skips discovery and talks to the address it was given. It is
added only for a single loopback host on the `mongodb` scheme; inside compose
(`mongo`), on a multi-host or SRV cluster, or where the URI already decides, the
URI comes back unchanged. Free of `cbc.shared.config` on purpose: the MCP servers
use it in a Claude subprocess that is not handed the root settings.
"""
from __future__ import annotations

from urllib.parse import urlsplit

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})


def reachable_uri(uri: str) -> str:
    parts = urlsplit(uri)
    if parts.scheme != "mongodb" or "directconnection" in parts.query.lower():
        return uri
    if "," in parts.netloc.rpartition("@")[2] or parts.hostname not in LOOPBACK:
        return uri
    if parts.query:
        return f"{uri}&directConnection=true"
    base = uri.rstrip("?")
    return f"{base}{'' if parts.path else '/'}?directConnection=true"
