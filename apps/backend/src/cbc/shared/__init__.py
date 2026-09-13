"""What every module may import, and the only thing they all share.

Kept small on purpose: configuration, the Mongo client and its primitives,
request authentication, logging and telemetry - and the project file tree:
storage, its S3 backend, the upload malware scan, the JSON a pass writes and the
manifests beside it. No business rules and no
collection accessors - a module names its own collections. Nothing here may
import from `cbc.modules`.
"""
