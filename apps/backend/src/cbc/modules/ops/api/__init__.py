"""ops' public surface - the only part of ops another module may import.

- `audit.record` - append to the audit trail (NFR-3).
- `identity.role_of` - what role a signed-in person has.
- `freshness` - the live review and discard windows for prices (`load`, `load_sync`).
- `pipeline.autopilot_default` - whether a new bid starts on autopilot.
- `jobs` - the queue: enqueue, the one-session-per-bid rule, and what a bid has running.
- `provider` - which model provider serves Claude Code, and the environment it needs.
- `runmetrics.record` - the cost and provenance of one Claude run, read from its recording.
- `cost_budget` - the USD spend caps checked before a worker claims a job.
- `alerts.notify` - tell operators a job was dead-lettered or blocked.
- `worker` - what a job runner calls while it holds a claimed job, and `bind` for the runner.
- `project_lookup` - a port ops needs and the composition root supplies.
"""
