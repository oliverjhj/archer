# Security

A public demo that lets strangers put text into a prompt that generates SQL,
which is then executed. The interesting question is not whether the model can
be talked into writing something dangerous - it can - but what happens when it
does.

## The threat that matters

**The prompt is not a security boundary and is not treated as one.**

User text is placed into a prompt in a single substitution pass, after the
prompt has been split into its chat messages, so a question cannot create a
new message or pull another value into the prompt. That keeps the prompt's
structure intact. It does not stop a question from asking the model to do
something else, and nothing at the prompt level can.

Earlier versions doubled braces in the question as an "escape". It protected
nothing, and it broke every question containing a brace, because the renderer
then mistook the user's text for an unfilled placeholder.

Everything that actually protects the database is downstream of the model, in
`backend/archer/db/query.py`, which is the only way generated SQL is executed:

| Control | Effect |
|---|---|
| **Read-only connection** | Opened with `file:...?mode=ro`; SQLite refuses writes at the driver |
| **Authorizer** | SQLite's own authorizer permits reading and nothing else: no `PRAGMA`, `ATTACH`, `load_extension`, writes, or reads of its internal `sqlite_*` tables - which leaves `sales_data` as the only table there is |
| **One statement** | Python's `sqlite3` refuses a string containing a second statement |
| **SELECT-only gate** | Text not starting with `SELECT` or `WITH` is refused before it reaches SQLite |
| **Deadline** | A progress handler interrupts any query still running after 5 seconds |
| **Row cap** | At most 100 rows are returned, with a flag when there were more |
| **Synthetic data** | There is nothing confidential to exfiltrate |

These are enforced by the database engine rather than by inspecting the query
text, which matters in both directions. A query that slips past a text check
still cannot write, attach or read outside the table; and a legitimate query
containing `;` or `--` inside a quoted name is no longer cut in half by a
regex. `backend/tests/unit/test_query_guard.py` hands `run_select` hostile
queries directly, as if every earlier check had missed them.

An injection that persuades the model to emit `DROP TABLE` produces a refused
query and a log line. The defence is layered because the first layer is the
one made of natural language.

## Authentication

**Browser sessions.** `/login` issues a JWT in an `archer_session` cookie:
HttpOnly, SameSite=Strict, and Secure whenever the request arrived over HTTPS.
HttpOnly means page JavaScript cannot read it, so an XSS bug cannot walk off
with the session.

**CSRF.** The login form carries a signed, time-limited token
(`itsdangerous`), verified on POST. Tokens are compared by replacing the
signature segment rather than by flipping characters, because a naive
comparison is not deterministic across encodings.

**Credentials** are compared with `secrets.compare_digest`, which takes the
same time whether the first character is wrong or the last.

**Machine callers.** `/ask` requires `x-api-key` matching `WEBHOOK_SECRET`.

**The browser never holds `WEBHOOK_SECRET`.** That is why `/api/ask` exists:
the frontend authenticates with its session cookie and the server supplies the
secret. Verified rather than assumed - every value in `.env` is checked against
the built frontend bundle, and none appears.

`/api/ask` explicitly **rejects** the API key. If it accepted both, a browser
would have a reason to hold the secret, which is the exact thing the route
exists to prevent.

## Secrets

Nothing sensitive is in the repository or the image. The container receives its
configuration from a Code Engine secret via `--env-from-secret`, so no value
appears in the image, the deployment definition, or the workflow.

`.env` and `*.db` are gitignored, and neither has ever been committed - checked
across the full history, not just the current tree.

## Rate limiting and cost

Per-IP rate limiting (`slowapi`) caps a single visitor at 20 questions a
minute. That stops one person hammering the service; it does nothing about a
thousand people asking one question each.

**IBM Cloud has no hard spending limit.** Its spending controls are
notifications - they email at 80%, 90% and 100% of a threshold and stop
nothing. For a public demo in front of a paid model, that is a warning that
money has already gone.

So the ceiling is in the application: a daily question budget, claimed before
the model is called, in `backend/archer/core/usage.py`. The counter is
per-process and the app scales to two instances, so the true ceiling is twice
the configured limit. That approximation is deliberate - making it exact would
mean running Redis to bound a demo's cost - and it is stated rather than
hidden.

## Transport and headers

TLS is terminated by Code Engine. A security-headers middleware sets
`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and a
`Content-Security-Policy`.

## Data

The database is generated, not extracted: 100,000 rows of synthetic UK sales
data from a fixed seed. Company names, addresses, postcodes and identifiers are
all fabricated. Product names are genuine IBM product names, which are public.

There is no personal data in this system and no real customer data has ever
been in it.

## Honest limitations

Worth stating, because a demo that claims to be hardened invites the question:

- **The login wall is a speed bump, not a control.** The credentials are
  printed on the login page. It exists to keep crawlers out, and the data
  behind it is synthetic.
- **The daily budget is approximate**, as described above.
- **Prompt injection is mitigated, not solved.** The structural controls are
  what hold.
- **No audit logging of questions.** Questions are logged at INFO for
  debugging, with no retention policy, because this is a demo rather than a
  system of record.
- **Single shared demo account.** No per-user accounts, no authorisation model,
  no roles. There is one thing to see and everyone sees the same thing.
