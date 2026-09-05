"""Code that both the API and the worker need, and neither should own.

`api` holds the business rules and the database; `worker` runs Claude Code. Both
need to invoke the CLI and to keep credentials out of what gets logged - and when
those lived in `worker`, the API's settings screen imported them, while the
worker imported the API's services. That is a package cycle, held apart only by
import statements hidden inside function bodies.

Nothing here imports from `api` or from `worker`. The dependencies point one way:

    api    ─┐
            ├─▶ cbc_core
    worker ─┘   (and worker ─▶ api, which is fine: one direction)
"""
