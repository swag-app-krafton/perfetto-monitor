# swagperf dashboard (frontend)

React 19 + TypeScript + Vite. Served by the Python server (`swagperf dashboard`)
from `../web/dist`, which is committed so the dashboard runs without Node.

```bash
npm install
npm run dev        # Vite on :5173, proxying /api to the dashboard on :8787
npm run build      # typecheck + build into ../web/dist (commit the result)
npm test           # vitest
```

Layout:

- `src/api/` – wire types (match `swagperf/server.py` JSON) and React Query hooks
- `src/domain/` – derived logic shared by screens: scope (app / path / range), formatting
- `src/design/` – tokens (dark + light) and the component library; no page knowledge
- `src/app/` – shell: sidebar, top bar, page header, routes, UI store
- `src/features/<screen>/` – one folder per screen

The old dashboard stays at `/legacy/` until every screen is rebuilt here.
