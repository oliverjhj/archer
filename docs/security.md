# Security

Archer is a public demo where visitors type text that becomes part of a prompt,
and the model's output is SQL that gets executed. A determined visitor can
persuade the model to write a harmful query. The controls below make sure such
a query can't do anything.

## Generated SQL

The prompt offers no protection on its own. User text is substituted in one pass,
after the prompt has been split into chat messages, so a question can't create
a new message or pull another value in. That protects the prompt's structure,
but nothing at the prompt level stops a question asking the model to do
something else.

The controls that protect the data sit after the model, in
`backend/archer/db/query.py`. `run_select()` is the only way generated SQL is
executed, in the application and in the evaluation suite alike.

| Control | Effect |
|---|---|
| Read-only connection | Opened with `mode=ro`, so SQLite refuses any write |
| Authorizer | SQLite's own authorizer allows reading one table, `TABLE_NAME`, and nothing else: no other table or view, no `sqlite_*` internal tables, no `PRAGMA`, `ATTACH` or `load_extension` |
| One statement | Python's `sqlite3` refuses a string containing a second statement |
| SELECT only | Text not starting with `SELECT` or `WITH` is refused before it reaches SQLite |
| Deadline | A progress handler interrupts any query still running after five seconds |
| Row cap | At most 100 rows are returned, with a flag when there were more |
| Synthetic data | There is nothing confidential to take |

The database engine enforces all of these, so nothing depends on reading the
query text. A hostile query that gets past a text check still can't write, attach or read
another table, and a legitimate query with `;` or `--` inside a quoted name
runs normally. `backend/tests/unit/test_query_guard.py` passes hostile queries
straight to `run_select()`, as if every earlier check had missed them.

A model persuaded to write `DROP TABLE` produces a refused query and a log
line.

## Conversation history

Follow-ups work because the browser sends the last few exchanges with each
question. That history comes from the client, so it is treated as untrusted:

- **Bounded.** The request accepts at most six items with capped field
  lengths, and the pipeline keeps the last three: at most ten rows and eight
  columns each, 80 characters a cell and 6,000 characters in total, with
  control characters removed.
- **Context only.** History goes into the user message under a heading that
  marks it as earlier conversation, never into a system message. A role marker
  inside it stays plain text.
- **Never executed.** The planner sees earlier SQL so it can restate a
  follow-up. Only SQL generated for the current question runs.
- **Private to the sender.** Nothing is stored on the server and nothing is
  shared between visitors, so a forged history can only affect the answer its
  own sender sees.
- **Not logged.** The server logs how many history items arrived, not their
  content.

## Authentication

**Browser sessions.** `/login` issues a JWT in an `archer_session` cookie:
HttpOnly, SameSite=Strict, and Secure when the request came over HTTPS. Page
JavaScript can't read it, so an XSS bug can't take the session.

**CSRF.** The login form carries a signed, time-limited token
(`itsdangerous`), verified on POST.

**Credentials** are compared with `secrets.compare_digest`, which takes the
same time wherever the first wrong character is.

**Machine callers.** `/ask` requires an `x-api-key` matching `WEBHOOK_SECRET`.
The browser never holds that secret: `/api/ask` authenticates with the session
cookie and rejects the API key, so there is no reason for the frontend to
carry it. Every value in `.env` has been checked against the built frontend
bundle, and none appears.

## Secrets

Nothing sensitive is in the repository or the image. The container gets its
configuration from a Code Engine secret through `--env-from-secret`, so no
value appears in the image, the application definition or the workflow.

`.env` and `*.db` are gitignored, and neither appears anywhere in the git
history.

## Rate limiting and cost

Per-IP rate limiting (`slowapi`) caps one visitor at 20 questions a minute.

IBM Cloud has no hard spending limit: its spending controls email at
thresholds and stop nothing. The limit is therefore in the application.
`backend/archer/core/usage.py` keeps a daily message budget, claimed before any
model call, set by `DEMO_DAILY_QUESTION_LIMIT` (default 200). A malformed value
falls back to the default instead of turning the limit off.

The counter is per process, and the app runs at most two instances, so the
real ceiling is twice the setting. Making it exact would need a shared store
such as Redis, which isn't worth it at these costs (see
[infrastructure](../infrastructure/README.md#what-it-costs)).

## Transport and headers

Code Engine terminates TLS. Middleware sets `X-Content-Type-Options`,
`X-Frame-Options`, `Referrer-Policy` and a `Content-Security-Policy`.

## Data

The database is generated: 100,000 rows of synthetic UK sales data from a fixed
seed. Company names, addresses, postcodes and identifiers are all made up.
Product names are real IBM product names, which are public. There is no
personal or customer data in the system.

## Limitations

- The login keeps crawlers out and nothing more. The credentials are printed on
  the login page, and the data behind it is synthetic.
- The daily budget is approximate, as described above.
- Prompt injection can still change what the model writes. The query
  controls limit what that query can do.
- Questions are logged at INFO level for debugging, with no retention policy.
- There is one shared demo account, with no per-user accounts or roles.
