# Frontend

The Archer web application: Vite, React 18 and TypeScript, styled with the IBM
Carbon Design System. Dark by default with a light toggle; the choice is shared
with the login page through one `localStorage` key and applied before first
paint, so there is no flash on load.

It is served by the backend as static files from the production build, so a
deployed Archer is one container. In development it runs on its own dev server
with a proxy to the backend.

## What it does

- Ask a question, get the answer, and see the SQL that produced it beside every
  data answer. Tabular results render as real tables.
- Loading, error and empty states. The empty state carries example questions and
  explains the cold start, because the demo scales to zero.
- A schema reference panel built from the live database: row count, date range,
  the columns most answers use, and the fixed-value columns.

## Prerequisites

Node 20 LTS or newer and npm. CI and the Docker build stage use Node 20; local
development on a newer Node is fine.

## Install and run

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173
```

Run the backend alongside it, from the repository root:

```bash
.venv/Scripts/python.exe -m uvicorn main:app --app-dir backend --port 8080
```

`vite.config.ts` proxies API and auth paths to the backend on port 8080, so the
app is developed same-origin and no CORS configuration is needed.

## Type-check and build

```bash
npm run typecheck    # tsc -b, no emit
npm run build        # tsc -b && vite build -> dist/
npm run preview      # serve the production build locally
```

The Docker build runs the same build and copies `dist/` into the image.

## Environment

Copy `.env.example` to `.env.local` for local overrides. The only variable is
`VITE_API_BASE_URL`, which should stay empty to use same-origin paths. **Nothing
secret belongs in a frontend environment file** - the browser never sees the
backend API key, because `/api/ask` is a server-side proxy that injects it.

## Layout

```text
frontend/
  index.html            Vite entry document, applies the saved theme before paint
  vite.config.ts        Vite config and the dev proxy to the backend
  src/
    main.tsx            React root and Carbon styles
    App.tsx             UI shell composition
    components/         AppHeader, AppSideNav, AskInput, AnswerWorkspace,
                        AnswerItem, ExampleQuestions
      pages/            HowToUse, HowItWasBuilt, MakeYourOwn
    api/                client.ts (transport), ask.ts (/api/ask)
    hooks/              useAsk.ts (question state machine), useTheme.ts,
                        useHashRoute.ts (page routing)
    lib/                answer.ts (answer parsing and table detection),
                        examples.ts (example questions)
    types/              api.ts (request and response types)
    styles/             index.scss (Carbon import and layout)
```
