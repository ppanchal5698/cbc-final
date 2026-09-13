"""What every module may import, and the only thing they all share.

Kept small on purpose: configuration, the Mongo client and its primitives,
request authentication, logging and telemetry. No business rules and no
collection accessors - a module names its own collections. Nothing here may
import from `cbc.modules`.
"""
