---
description: Extract door, FRP, and Div 10 takeoff
---

Follow the takeoff-engineer agent in `.claude/agents/takeoff-engineer.md`.

Review the door schedule, fill nulls from sheet evidence only, and save
`extracted/line_items.json` via `save_artifact`. If FRP is in scope, also
follow `.claude/agents/frp-specialist.md`. If `div10_in_scope` is true, also
follow `.claude/agents/div10-specialist.md`. Do not match or price.
