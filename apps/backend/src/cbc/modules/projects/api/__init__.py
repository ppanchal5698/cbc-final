"""projects' public surface - the only part of projects another module may import.

- `lookup.load` - a bid by code, slug or id; raises `ProjectNotFound` on a miss.
- `lookup.project_id`, `lookup.summaries` - what ops' project lookup port is bound to.
"""
