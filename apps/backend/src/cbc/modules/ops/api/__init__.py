"""ops' public surface - the only part of ops another module may import.

- `audit.record` - append to the audit trail (NFR-3).
- `identity.role_of` - what role a signed-in person has.
- `freshness` - the live review and discard windows for prices (`load`, `load_sync`).
- `pipeline.autopilot_default` - whether a new bid starts on autopilot.
- `project_lookup` - a port ops needs and the composition root supplies.
"""
