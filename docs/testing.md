# Testing

**113 unit tests**, run on every push and pull request.

```bash
.venv/Scripts/python.exe -m pytest backend/tests/unit -m unit -q
```

## Isolation

The suite touches nothing outside the process. No `.env`, no `sales.db`, no
IBM Cloud, no watsonx, no network. That is a deliberate property, not a
convenience:

- `conftest.py` injects stub values for `JWT_SECRET_KEY`, `CSRF_SECRET_KEY` and
  `WEBHOOK_SECRET` via `os.environ.setdefault`, because modules read them at
  import time.
- **Cloud and model variables are deliberately absent.** Any test that
  accidentally reaches a live service fails loudly rather than passing quietly
  against real infrastructure.
- Model calls are mocked at the name they are looked up under.
- SQL-path tests build a small temporary SQLite file rather than using the real
  dataset.
- Most tests assemble a minimal FastAPI app containing only the router under
  test, so the real application's lifespan never runs.

## What is covered

| Area | What is asserted |
|---|---|
| SQL extraction | Multi-line and fenced replies, `WITH`, statement ends outside quoted strings, braces in questions |
| Query guard | Writes, `ATTACH`, `PRAGMA`, internal tables, `load_extension` and second statements refused by SQLite; runaway queries interrupted; row cap |
| Prompts | Role markers become chat messages; a marker in user text cannot start one; single-pass substitution; front matter never sent |
| JWT | Payload, expiry, tampering, wrong signing key |
| CSRF | Generation, validation, tampered tokens |
| Auth routes | `/login` GET and POST, cookie issuance, bad credentials |
| `/ask` | API key handling, both routes, result formatting, DB errors, 100-row truncation |
| `/api/ask` | Missing, malformed, expired and wrongly-signed cookies; **the API key is rejected**; both routes return identical answers |
| Page routes | The app shell stays behind the login wall; retired pages redirect |
| App assembly | Startup, routing, JSON-401-versus-redirect, a full composition check |
| Cost ceiling | Limit enforced, daily reset, thread safety, malformed config fails closed |

Two of those deserve calling out, because they exist to catch a specific
mistake rather than to raise a number:

**`/ask` and `/api/ask` must return identical answers.** Both call one shared
function. The test exists so that if someone ever duplicates the orchestration,
the two paths cannot silently drift apart.

**The cost ceiling fails closed.** A malformed `DEMO_DAILY_QUESTION_LIMIT`
falls back to the default rather than disabling the limit, because failing open
is the expensive direction. It is also tested under concurrent threads, since
the budget is consumed from worker threads.

## What the tests do not catch, and why that matters

This is the honest part, and it is here because the project has the evidence.

**Three user-visible defects shipped past a green suite.** The generated SQL was
rendered correctly and positioned underneath a sticky form where no one could
scroll to it; answers did not scroll into view; every web font 404'd. Every
element was present, correct, and in the DOM. Every test passed. They were
found by driving a real browser.

**A prompt change dropped accuracy from 89.3% to 10.7%** while all 101 tests of
the day passed. Moving prompts from Python into files stripped a trailing
newline, and the model stopped producing SQL. Nothing about the application was
broken in a way a unit test could see - the route still returned 200 and the
answer was still well-formed prose.

So the suite is one of three layers, and it is the cheapest rather than the
most convincing:

| Layer | Catches | Cost |
|---|---|---|
| Unit tests | Logic, auth boundaries, formatting | Free, every push |
| [Evaluation suite](evals.md) | Whether answers are right | Real model calls, run deliberately |
| Driving the browser | Whether a person can use it | Manual, before release |

A test that asserts an element exists cannot tell you a user can reach it.

## CI

Four jobs on every push and pull request:

- **Compile and validate** - syntax, TOML, YAML
- **Unit tests** - the suite above
- **Frontend** - typecheck and production build, Node 20 LTS
- **Docker build** - the image builds from a clean checkout

The evaluation suite is **not** in CI. It makes real model calls and needs live
credentials, which is the wrong thing to attach to every pull request. It is
run deliberately, before and after any change to a prompt or a model.
