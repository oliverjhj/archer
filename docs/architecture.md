# Architecture

One container on IBM Code Engine, one SQLite file, five prompts and the
watsonx.ai chat API.

```
                    ┌──────────────────────────────┐
   browser ────────▶│  FastAPI (IBM Code Engine)   │
                    │                              │
                    │  /login      Jinja + CSRF    │
                    │  /           React app       │
                    │  /api/ask    cookie auth ────┼──┐
                    │  /api/schema cookie auth     │  │
                    │  /ask        x-api-key   ────┼──┤
                    └──────────────────────────────┘  │
                                                      ▼
                                          ┌────────────────────┐
                                          │  answer_question() │  daily budget
                                          ├────────────────────┤
                                          │  run_turn()        │  pipeline
                                          └─────────┬──────────┘
                                                    │
                    ┌──────────────┬────────────────┼──────────────┐
                    ▼              ▼                ▼              ▼
                 planner     sql_generator      summary          chat
                    │         (+ sql_retry)         │              │
                    └──────────────┴──▶ watsonx.ai ◀┴──────────────┘
                                   │
                                   ▼
                       sales.db (SQLite, read-only)
```

## Request flow

1. A question arrives at `/api/ask` from the browser, with a session cookie,
   or at `/ask` from a machine caller, with an `x-api-key`. Both call the same
   `answer_question()`.
2. `answer_question()` claims one message from the daily budget, then calls
   `run_turn()` in `pipeline.py`. That returns a structured `Turn`: the plan,
   the SQL, the result as display strings, and a status for every outcome. The
   response carries the `Turn` for the React app and a Markdown `answer` for
   `/ask` callers. The evaluation suite calls `run_turn()` directly, so it
   measures what the demo runs.
3. The planner reads the question with the last three exchanges, which the
   browser sends with it. It returns a plan: a data question, conversation
   about the data, a clarifying question, or off-topic, with each part of the
   message restated to stand alone. Off-topic requests get a fixed decline
   with no further model call. With no earlier exchanges the question is used
   as typed.
4. Each data part goes to the SQL generator, which sees only the restated
   question and the live column list read from the database.
5. The SQL runs through `run_select()`: a read-only connection whose SQLite
   authorizer allows reading the one queryable table, one statement, a
   five-second deadline and a 100-row cap. A query that fails, or finds nothing
   where something was expected, gets one corrected attempt, kept only if it
   does better.
6. A ranking or breakdown gets a written summary. Every number in it must
   appear in the result, or it is dropped.
7. Chat parts go to the chat prompt, which answers from the conversation and a
   glossary of the columns, without querying.

The watsonx SDK is synchronous, so model calls run in `asyncio.to_thread` to
keep the event loop free while a call is in progress.

Prompt detail is in [prompts](prompts.md).

## The data

`sales.db` is generated when the image is built, by
[`scripts/generate_dataset.py`](../scripts/generate_dataset.py): 100,000 rows of
synthetic UK sales data across 37 columns in one table, `sales_data`. The seed
is fixed, so the same seed always gives a byte-identical database, and the
evaluation suite can rely on exact results.

The table name is one constant, `TABLE_NAME` in `backend/archer/db/database.py`.
The application opens the database read-only and refuses to start if the file
is missing, empty, not SQLite, or lacks that table.

## Authentication

| Route | Authenticated by | For |
|---|---|---|
| `/api/ask`, `/api/schema` | `archer_session` HttpOnly cookie | The browser |
| `/ask` | `x-api-key` matching `WEBHOOK_SECRET` | Machine callers |

The browser never holds `WEBHOOK_SECRET`. It signs in with the session cookie,
and `/api/ask` rejects the API key outright.

A missing or invalid session is handled by path. Pages redirect to `/login`.
Anything under `/api/` gets a JSON 401, which the React app can show as a
message.

## Serving

One image serves both halves. A `node:20-slim` stage builds the React app, and
Node never reaches the runtime image. FastAPI serves the built files from the
same origin as the API, so the session cookie works without CORS and there is
one thing to deploy.

## Layout

```
backend/archer/
├── app.py                 FastAPI assembly, middleware, lifespan
├── pipeline.py            run_turn(): one message to a structured Turn
├── api/
│   ├── ask.py             answer_question() and both entry points
│   ├── auth_routes.py     /login, CSRF, session cookie
│   ├── page_routes.py     the app shell, behind the login
│   └── schema_routes.py   /api/schema for the in-app guide
├── ai/
│   ├── llm.py             per-step watsonx chat clients
│   ├── prompts.py         loading prompts/*.md into chat messages
│   ├── planner.py         the plan, and the question restated
│   ├── sql_generator.py   SQL generation, extraction, one retry
│   ├── summary.py         result summaries and the check on their figures
│   └── chat.py            conversational replies
├── auth/                  JWT and CSRF
├── core/
│   ├── usage.py           the daily message ceiling
│   ├── limiter.py         per-IP rate limiting
│   ├── logging.py         log format
│   ├── paths.py           paths in the repo and in the container
│   └── security_headers.py
└── db/
    ├── database.py        TABLE_NAME, startup check, columns, date range
    ├── catalogue.py       column descriptions and known values
    └── query.py           run_select(): the only way generated SQL runs
```

The frontend is in `frontend/src`: React 18 with IBM's Carbon design system.

## Design decisions

**Planning is a separate call.** The SQL generator only ever sees a standalone
question, so its accuracy is measured on one kind of input. A combined prompt
would also have to decide when not to write SQL.

**The browser holds the conversation.** History is sent with each question and
stored nowhere. The server stays stateless, "Clear conversation" really clears
it, and history is treated as untrusted input.

**Accuracy is measured by execution.** The suite compares query results. See
[evals](evals.md).

**Minimum scale is zero.** The demo is idle most of the time, so an
always-running instance would cost money for nothing. The price is a cold start
of a few seconds after a quiet period, which the interface mentions.

**The cost ceiling is in the application.** IBM Cloud spending controls send
notifications but stop nothing, so `core/usage.py` refuses messages once the
day's budget is spent.

**It runs on any container host.** A single container listening on `$PORT`,
with no persistent state and no cloud SDK in the request path. watsonx.ai is
the only IBM service the application itself calls.
