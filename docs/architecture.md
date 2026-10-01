# Architecture

One container, one database file, three prompts, and a model call.

```
                    ┌──────────────────────────────┐
   browser ────────▶│  FastAPI (IBM Code Engine)   │
                    │                              │
                    │  /login      Jinja + CSRF    │
                    │  /           React SPA       │
                    │  /api/ask    cookie auth ────┼──┐
                    │  /ask        x-api-key   ────┼──┤
                    └──────────────────────────────┘  │
                                                      ▼
                                          ┌────────────────────┐
                                          │  answer_question() │  budget
                                          ├────────────────────┤
                                          │  run_turn()        │  pipeline
                                          └─────────┬──────────┘
                                                    │
                        ┌───────────────────────────┼──────────────┐
                        ▼                           ▼              ▼
                   planner prompt           sql_generator      chat prompt
                        │                           │              │
                        └──────▶ watsonx.ai ◀───────┴──────────────┘
                                                    │
                                                    ▼
                                        sales.db (SQLite, read-only)
```

## Request flow

1. A question arrives at `/api/ask` (browser, session cookie) or `/ask`
   (webhook, `x-api-key`). Both call the same `answer_question()`; nothing is
   duplicated between them.
2. The **daily budget** is claimed before anything expensive happens, then
   `run_turn()` in `pipeline.py` does the rest. It returns a structured
   `Turn`: what was decided, the SQL, the result as display strings, and a
   status for every outcome. The response carries that turn for the React app
   and the Markdown `answer` that `/ask` callers have always received. The
   evaluation suite calls `run_turn()` directly, so it measures exactly what
   the demo runs.
3. The **planner** reads the question with the last three exchanges, which
   the browser sends along with it, and returns a small JSON plan: is this a
   data question, data-related conversation, or off-topic - and what is the
   question once any reference to the conversation ("the second one", "and
   for 2024?") is resolved? Off-topic requests get a fixed decline with no
   further model call. Without earlier exchanges the question is used exactly
   as typed.
4. Data questions go to the **SQL generator** - the restated question,
   never the conversation - which is given the live schema
   read from the database rather than a hardcoded list.
5. The generated SQL is executed through `run_select`: a read-only connection
   whose SQLite authorizer permits reading `sales_data` and nothing else, one
   statement, a deadline and a 100-row cap. The result is formatted as
   Markdown.
6. Conversational questions go to the **chat prompt** and never see the schema.

Model calls are dispatched with `asyncio.to_thread`. The watsonx SDK is
synchronous, and calling it directly from an async handler would block the
event loop for the whole round trip - seconds during which nothing else on the
process is served.

## The data

`sales.db` is **generated at image build time** by
[`scripts/generate_dataset.py`](../scripts/generate_dataset.py): 100,000 rows
of synthetic UK sales data across 37 columns, from a fixed seed, so the same
seed always produces a byte-identical database.

It was previously downloaded from IBM Cloud Object Storage at startup. That was
removed: the dataset is static and about 47MB, so fetching it on every cold
start paid a download and a set of credentials for nothing, and the deployment
scales to zero, which makes cold-start cost real. Generating it also means the
evaluation suite can rely on fixed rows.

The database is opened **read-only** and the application refuses to start if it
is missing or invalid. Failing loudly at deploy time is better than serving
errors on every question.

## Authentication

Two surfaces, deliberately:

| Route | Authenticated by | For |
|---|---|---|
| `/api/ask` | `archer_session` HttpOnly cookie | The browser |
| `/ask` | `x-api-key` matching `WEBHOOK_SECRET` | Machine callers |

The browser never holds `WEBHOOK_SECRET`. That is the entire reason `/api/ask`
exists: the frontend authenticates with a session cookie, and the server
supplies the secret on its behalf.

A 401 is handled differently by path. Page routes redirect to `/login`, which
is right for a browser. Anything under `/api/` gets a JSON 401, because a
`fetch()` call cannot do anything useful with a 303 to an HTML login page and
would otherwise receive a login page where it expected data.

## Serving

One image serves both halves. A `node:20-slim` build stage compiles the React
application; Node never reaches the runtime image. FastAPI serves the built
bundle from the same origin as the API, which keeps the session cookie working
without CORS and means one thing to deploy rather than two.

## Layout

```
backend/archer/
├── app.py                 FastAPI assembly, middleware, lifespan
├── pipeline.py            run_turn(): one message to a structured Turn
├── api/
│   ├── ask.py             answer_question() and both entry points
│   ├── auth_routes.py     /login, CSRF, cookie issuance
│   └── page_routes.py     app shell and legacy redirects
├── ai/
│   ├── llm.py             per-task watsonx chat clients
│   ├── prompts.py         prompt loading from prompts/*.md
│   ├── planner.py         kind of reply, and the question restated
│   ├── sql_generator.py   SQL generation and extraction
│   └── chat.py            conversational replies
├── auth/                  JWT and CSRF
├── core/
│   ├── usage.py           the daily cost ceiling
│   ├── limiter.py         per-IP rate limiting
│   ├── paths.py           path resolution for both layouts
│   └── security_headers.py
└── db/
    ├── database.py        dataset verification, schema and date range
    └── query.py           run_select: the only way generated SQL runs
```

Prompts live in [`prompts/`](../prompts) as versioned Markdown, not as string
literals. See [`prompts.md`](prompts.md).

## Design decisions worth defending

**Planning is a separate call.** A combined prompt would have to decide and
produce SQL in one pass, and a model shown fifteen SQL examples will write SQL
for "hello". The planner also restates follow-ups, so the SQL generator only
ever sees a standalone question - the kind its 100% was measured on.

**The browser holds the conversation.** History goes from the browser to the
server with each question and is stored nowhere. That keeps the server
stateless, means "Clear conversation" really does clear it, and makes the
history untrusted input by construction - which is how it is treated.

**Execution-based evaluation.** Accuracy is measured by running both the
reference and the generated query and comparing results, not by comparing SQL
text. Two different queries can be equally correct. See [`evals.md`](evals.md).

**Minimum scale zero.** The demo is idle almost all the time, so an always-warm
instance would be paying for nothing. The cost is a cold start on the first
question after a quiet period, which the interface says out loud. This is why
image size and startup work are treated as they are.

**A cost ceiling in the application.** IBM Cloud has no hard spending limit -
its spending controls are notifications, which arrive after the money is spent.
So the ceiling is `core/usage.py`, where it can actually refuse.

**Not IBM-locked.** A single container listening on `$PORT`, no persistent
state, no cloud SDK in the runtime path. It runs unchanged on any container
host. The only real IBM dependency is watsonx.ai, which is the point of the
project rather than an accident of hosting.
