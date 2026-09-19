# Design system

Everything lives in one file: `apps/web/app/globals.css`, 451 lines. **There is
no `tailwind.config.*`** — this is Tailwind v4, so the theme is CSS.
`postcss.config.mjs` loads `@tailwindcss/postcss` and that is the whole build
configuration.

## The file, in order

1. `@import "tailwindcss"`, `"tw-animate-css"`, `"shadcn/tailwind.css"`
2. `@custom-variant dark (&:is([data-theme="dark"] *))`
3. `@theme` — maps Tailwind colour utilities onto CSS variables
4. `:root` — only `--font-manrope` and `--radius`
5. `[data-theme="dark"]` — the palette
6. `[data-theme="light"]` — the palette
7. `@layer base` — global border and ring, 13.5px base, tabular numerals, 6px scrollbars
8. `.app-shell` and its child rules
9. Animations, `.tnum`, terminal log styles

## Theming is an attribute, not a class

```css
@custom-variant dark (&:is([data-theme="dark"] *));
```

Dark mode keys off `[data-theme]` on `<html>`, **not** Tailwind's default
`.dark` class. `app/layout.tsx` ships `data-theme="dark"` in the server HTML and
runs a small inline script before paint that reads `localStorage["opshub-theme"]`
and corrects the attribute — which is why there is no flash on a light-mode
reload.

Writing `dark:` in a component works as normal. Adding a `.dark` class does
nothing.

## Tokens

The `@theme` block is the contract. Two sets:

**shadcn compatibility** — `--color-background`, `--color-foreground`,
`--color-card`, `--color-popover`, `--color-primary`, `--color-secondary`,
`--color-muted`, `--color-accent`, `--color-destructive`, `--color-border`,
`--color-input`, `--color-ring`. These exist so a shadcn primitive drops in
unmodified.

**The actual palette** — what application code should use:

| Group | Tokens |
|---|---|
| Surfaces | `--color-panel`, `--color-panel-muted`, `--color-panel-raised`, `--color-subtle` |
| Text | `--color-tx-primary`, `--color-tx-secondary`, `--color-tx-muted` |
| Brand | `--color-brand-primary`, `--color-brand-soft`, `--color-brand-border` |
| Status | `--color-status-{success,warning,error,info}`, each with `-soft` and `-border` |
| Elevation | `--shadow-1`, `--shadow-2`, `--shadow-3` (from `--sh-1/2/3`) |
| Type | `--font-sans`, `--font-heading` (both Manrope), `--font-mono` |

Radii all derive from `--radius: 0.5rem`.

Both `[data-theme]` blocks define the same names and end with the same shadcn
alias overrides, so the two palettes stay in step by construction:

| | dark | light |
|---|---|---|
| background | `#0a0a12` | `#f6f6fa` |
| panel | `#15151f` | white |
| panel-raised | `#0e0e18` | `#ffffff` |
| hairline | `rgba(255,255,255,.075)` | `#e7e7f0` solid |
| brand | indigo-400 `#818cf8` | indigo-600 `#5b5bd6` |

The dark hairline is translucent and the light one solid on purpose: a solid
dark border reads as a hard line against a near-black panel, a translucent one
reads as an edge.

`@layer base` sets `font-feature-settings: "tnum" 1, "cv11" 1` globally, so
figures line up in every table without a per-cell class. `.tnum` exists for the
few places that need it explicitly.

## The app shell

```css
.app-shell {
  display: grid;
  height: 100vh;
  overflow: hidden;
  grid-template-columns: auto minmax(0, 1fr);
  grid-template-rows: 54px auto minmax(0, 1fr) auto;
}
.app-shell > *           { grid-column: 2; min-width: 0; }
.app-shell > header      { grid-column: 1 / -1; grid-row: 1; }
.app-shell > nav         { grid-column: 1; grid-row: 2 / -1; }
.app-shell > main        { grid-row: 1 / -1; min-height: 0; }
.app-shell > header ~ main { grid-row: 3; }
```

Four rows — topbar, stage bar, content, action bar — of which the two `auto`
rows collapse to nothing when unused.

**Pages plug in by returning a bare fragment.** A page returns its own
`<header>`, an optional stage bar, `<main>` and an optional `<footer>`, with no
wrapper element. `app/(app)/layout.tsx` renders `{children}` directly inside the
`.app-shell` div, so those elements become grid children and the selectors above
place them.

That is the reason for the last rule. A page with no header — the 404, the error
boundary — gets `main` spanning every row and fills the grid. A page with a
header gets `main` in row 3, under it. The stage bar has no rule at all; it
auto-places into the one remaining free cell.

Consequences worth knowing before adding a page:

- Do not wrap your page in a `<div>`. It will land in column 2 as a single
  child and the grid rules will not apply to what is inside it.
- `min-width: 0` on every child and `min-height: 0` on `main` are what let long
  tables scroll instead of pushing the layout wide.
- `overflow: hidden` on the shell means the page never scrolls; `main` does.

## Shell components

`components/shell/`:

| File | Role |
|---|---|
| `rail.tsx` | the `<nav>` — 7 items, 216px ↔ 64px collapse, Ctrl+B, badge counts for stale price books and dead jobs |
| `header.tsx` | the `<header>` — breadcrumbs, command palette, run pill, terminal toggle, theme toggle, review queue, avatar. Exports `Crumb` |
| `page-header.tsx` | a thin **server** wrapper resolving `auth()` and feeding `Header` |
| `stage-bar.tsx` | the four-stage strip (intake → extraction → quote → proposal) with a progress bar |
| `ui-state.tsx` | `UiStateProvider` / `useUiState` |
| `shell-overlays.tsx` | mounts the notes drawer, command palette and terminal drawer once, deriving the bid code from `usePathname()` |

`ui-state.tsx` is worth a look for one detail: persisted preferences
(`opshub-theme`, `opshub-focus`, `opshub-sidebar-collapsed`) are read through
`useSyncExternalStore` with a custom `opshub-local-preference` window event,
rather than `useState` + `useEffect`. That avoids the setState-in-effect cascade
that a `localStorage` read otherwise causes on every mount.

Global keys: Ctrl/Cmd+K palette, Ctrl/Cmd+B sidebar, bare `C` for notes.

## Primitives

`components/ui/` is shadcn style `base-nova` with `cssVariables: true` — but the
primitives are built on **`@base-ui/react`**, not Radix, and icons come from
**`@phosphor-icons/react/dist/ssr`** despite `components.json` declaring
`iconLibrary: "lucide"`.

In practice two hand-written components carry the system:

- **`status-badge.tsx`** — six variants: `action`, `review`, `progress`, `ok`,
  `caution`, `neutral`. This is how state is shown everywhere.
- **`fetch-error.tsx`** — the standard "this panel could not load" surface, used
  in twelve places.

Thirteen of the 22 files in the directory have no importers at all. Reach for
`status-badge`, `fetch-error` and Tailwind utilities over the tokens before
adding another primitive.

## Animation

`fade-in`, `pop-in`, `sweep` and `skeleton-pulse`, all disabled under
`prefers-reduced-motion`. Terminal log styling (`.terminal-log .agent-prose`,
`.tool-card`, `.terminal-code-block`) is separate because it renders
model output rather than application UI.
