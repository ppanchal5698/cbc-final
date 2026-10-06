---
description: Extract door, FRP, and Div 10 takeoff
---

Follow the takeoff-engineer agent in `.claude/agents/takeoff-engineer.md`.

Review the door schedule and fill nulls from sheet evidence only. The schedule
is seeded, so correct `extracted/line_items.json` with `propose_patch`, one
field at a time - a whole-file `save_artifact` over the seed is refused. If FRP is in scope, also
follow `.claude/agents/frp-specialist.md`. If `div10_in_scope` is true, also
follow `.claude/agents/div10-specialist.md`. Do not match or price.
