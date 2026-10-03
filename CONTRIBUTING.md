# Contributing

Issues and pull requests are welcome. These rules keep the demo safe to run in
public and its accuracy figures honest.

## Rules

- **Never commit `.env` or a database file.** Both are gitignored. If either
  shows up in `git status`, stop and find out why.
- **`WEBHOOK_SECRET` stays on the server.** It must never appear in frontend
  code or in a `VITE_*` variable. The browser authenticates with its session
  cookie through `/api/ask`.
- **Synthetic data only.** The dataset is generated, and the prompts and tests
  use generated company names. No real customer, employer or personal data.
- **Generated SQL runs only through `run_select()`** in
  `backend/archer/db/query.py`. Don't execute model output any other way, and
  don't weaken the controls there without a test that shows why.
- **Don't weaken the cost ceiling** in `backend/archer/core/usage.py`.
- **Run the evaluation suite for any prompt change**, before and after, and add
  the result to [`docs/evals.md`](docs/evals.md). Prompt changes often move
  accuracy in ways the unit tests can't see. See
  [`docs/prompts.md`](docs/prompts.md#changing-a-prompt).
- **Keep changes scoped.** One concern per pull request.

## Before opening a pull request

```bash
.venv/Scripts/python.exe -m pytest backend/tests/unit -m unit -q
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

All three must pass. For any change to the interface, also use it in a browser:
a test that an element exists can't tell you a person can reach it.

## Style

- British English in code, comments, docs and commit messages.
- Regular hyphens, not em dashes. No emojis.
- [Conventional Commits](https://www.conventionalcommits.org/) for commit
  messages.
- Say what something does and what it costs. Leave out the sales pitch.
