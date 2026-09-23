# swagperf dashboard (frontend)

React 19 + TypeScript + Vite. Served by the Python server (`swagperf dashboard`)
from `../web/dist`, which is committed so the dashboard runs without Node.

```bash
npm install
npm run dev        # Vite on :5173, proxying /api to the dashboard on :8787
npm run build      # typecheck + build into ../web/dist (commit the result)
npm test           # vitest
npm run lint       # oxlint
```

## Layout

- `src/design/` – the design system. Everything on screen is built from it,
  imported only as `@/design`. It knows nothing about runs, apps or the API.
  - `foundations/` – tokens (colour per theme, radii, layers, motion) and the
    global stylesheet
  - `primitives/` – `Stack` / `Row` / `Spacer` for layout, `Text` for all text
    (a role from the type scale plus a tone), `Swatch`, `Kbd`, and the spacing
    scale (`gap` only takes values from it)
  - `components/` – controls, status, containers, overlays (`Popover`, `Menu`),
    the docked panel, conversation parts
  - `charts/` – `LineChart`, `StackedBars`, `BandedTimeline`, `BarSeries`,
    `MiniBars`, `Sparkline`
  - `hooks/` – behaviour components share (`useSort`, `useListNav`)
- `src/api/` – wire types (match `swagperf/server.py` JSON) and React Query hooks
- `src/domain/` – derived logic shared by screens: scope (app / path / range),
  metrics, step baselines, statistics, formatting
- `src/app/` – shell: sidebar, top bar, page header, routes, UI store
- `src/features/<screen>/` – one folder per screen, composed from the design
  system; page-specific layout goes in a CSS module beside the page
- `src/lib/` – small framework helpers (media queries, deep-link highlight,
  server-sent events)

The living reference for the design system is **`/design-system`** (the
"Tokens" link in the top bar). Add a component there when you add it to the
library.

### Rules of thumb

- No static `style={{…}}` in features. Layout is `Stack`/`Row`/`Grid`/`Card`,
  text is `Text`. Inline style is for values computed from data (chart
  geometry, a series colour).
- A visual pattern needed twice becomes a generic component in `src/design/`,
  taking data and callbacks as props.
- Status is never colour alone: pair it with a glyph (`StatusPill`,
  `StatusSquare`, `DiffTag`) or a label.

## Copilot

`src/features/copilot/` is the floating Copilot panel (⌘K / Ctrl+K). It
streams answers from `POST /api/copilot/ask` as server-sent events
(`thread`, `step`, `block`, `done`, `error`, `saved`) and renders the answer
blocks (`verdict`, `heading`, `para`, `table`, `bars`, `code`, `cites`).
Citations carry their own route and highlight target, so clicking one opens
that screen and rings the element.

Answers currently come from `swagperf/copilot.py`, which computes them from
the run history by rule. A model-backed engine can replace `answer()` there
without the panel changing. Threads, feedback and answers pinned as findings
are stored in `history.db` (`copilot_threads`, `copilot_messages`,
`copilot_pins`).
