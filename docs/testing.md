# Testing

216 unit tests, run in CI on every push and pull request (see [CI](ci.md)).

```bash
.venv/Scripts/python.exe -m pytest backend/tests/unit -m unit -q
```

## Isolation

The suite touches nothing outside the process: no `.env`, no `sales.db`, no
IBM Cloud, no watsonx and no network.

- `conftest.py` sets stub values for `JWT_SECRET_KEY`, `CSRF_SECRET_KEY` and
  `WEBHOOK_SECRET`, because modules read them at import time.
- Cloud and model variables are left unset, so a test that reaches a live
  service by mistake fails instead of quietly passing.
- Model calls are mocked where they are looked up.
- SQL tests build a small temporary SQLite file instead of using the real
  dataset.
- Most tests build a minimal FastAPI app with only the router under test, so
  the real application's startup never runs.

## What is covered

| Area | What is asserted |
|---|---|
| SQL extraction | Multi-line and fenced replies, `WITH`, statement ends outside quoted strings, braces in questions |
| Query guard | Writes, `ATTACH`, `PRAGMA`, internal tables, other tables and views, `load_extension` and second statements refused by SQLite; CTEs allowed; runaway queries interrupted; row cap |
| Planner and history | Plans parsed from fenced or noisy replies; an unparseable plan falls back to a data question as typed; history trimmed to three exchanges and its size limits, keeping the latest; a role marker in history stays inside the user message; off-topic declined with no second model call; a question restated only when there is history to resolve |
| Self-correction and summaries | A failed or unexpectedly empty query retried once and kept only if better; no retry after a guard refusal or an empty existence check; database errors never reach the browser; summaries with figures not in the result dropped; no summary for single values, name lists or deal lines |
| Multi-part and clarify | Mixed and clarify plans parsed; parts answered in order, and one failure doesn't stop the others; a fourth part noted; a clarifying question runs no query and is overruled for a message with nothing to resolve |
| Pipeline | Scalar, table, empty and refused results as structured parts; a NULL sum shown as empty; a model outage returned as an answer, not a 500 |
| Prompts | Role markers become chat messages; a marker in user text can't start one; single-pass substitution; front matter never sent |
| Schema | The column descriptions match the generated schema, and the SQL prompt's default columns match the guide's |
| JWT and CSRF | Payload, expiry, tampering, wrong signing key |
| Auth routes | `/login` GET and POST, cookie issuance, bad credentials |
| `/ask` and `/api/ask` | API key handling; missing, malformed, expired and wrongly signed cookies; `/api/ask` rejects the API key; both routes return identical answers |
| Pages and app | The app stays behind the login; old paths redirect; JSON 401 for `/api/`, redirect for pages |
| Cost ceiling | Limit enforced, daily reset, thread safety, a malformed setting keeps the default |

Two tests guard against specific mistakes. `/ask` and `/api/ask` must return
identical answers, so the two paths can't drift apart if someone duplicates the
logic. And the cost ceiling must keep its default when the setting is
malformed, because failing open is the expensive direction.

## What the tests can't catch

Unit tests check logic. They can't tell whether the answers are right or
whether a person can use the page. Both have gone wrong here with every test passing:

- Three interface defects reached the live demo: the SQL sat out of reach
  beneath a sticky form, answers didn't scroll into view, and the web fonts
  failed to load. They were found by using the app in a real browser.
- Moving the prompts from Python into files dropped accuracy from 89% to 11%.
  The loader stripped a trailing newline the model relied on, and the route
  still returned well-formed answers. Only the evaluation suite saw it.

So there are three layers:

| Layer | Catches | When |
|---|---|---|
| Unit tests | Logic, auth boundaries, formatting | Every push, in CI |
| [Evaluation suite](evals.md) | Whether the answers are right | Before and after any prompt or model change |
| Using the app in a browser | Whether a person can use it | Before any interface change ships |
