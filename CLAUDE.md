# CLAUDE.md - archer-text-to-sql

Read this before doing anything in this repository.

## What this is

A natural-language-to-SQL system: ask a question in English, get an answer from
a sales database, alongside the SQL that produced it. FastAPI backend, IBM
watsonx.ai for the model, React and Carbon frontend, deployed on IBM Code
Engine.

It began as a proof-of-concept built at a UK IBM distributor. **It was a demo,
never a system anyone used day to day.** Say "proof-of-concept" in anything
public - claiming it was an adopted internal tool is not true and would not
survive an interview question.

## Hard constraints

- **Never commit `.env` or `sales.db`.** Both are gitignored. If either appears
  in `git status`, stop and say so.
- **`WEBHOOK_SECRET` must never reach browser code**, and never appears in a
  `VITE_*` variable. `/api/ask` exists precisely so the browser never holds it.
- **No employer data, names, branding or configuration.** The dataset is
  generated, the prompts use generated company names, and it stays that way.
- **Do not change prompts without running the evals.** Prompt text changes model
  behaviour, and the change is often invisible to the unit tests. Measure before
  and after: `python evals/run_evals.py`.
- Do not run `pre-commit run --all-files` or broad reformatting unasked.
- Keep changes scoped. No "while we are here" refactors.

## House style

- **British English** everywhere: code, comments, docs, commit messages.
- **Regular hyphens, not em dashes. No emojis** in code, logs, docs or commits.
- **Conventional Commits.**
- Plain framing over hype. Name trade-offs rather than selling them.

## Validation

```powershell
.venv\Scripts\python.exe -m pytest backend/tests/unit -m unit -q   # 150 tests
cd frontend; npm run typecheck; npm run build
```

Both must pass before any commit.

**For anything with a UI, also drive it in a browser.** Three user-visible
defects have already shipped past a green suite in this repository: the
generated SQL rendered correctly but sat unreachable beneath a sticky form,
answers did not scroll into view, and every web font 404'd. A test that asserts
an element exists cannot tell you a user can reach it.

## Architecture notes

- `backend/main.py` is a thin entrypoint; the app is assembled in
  `backend/archer/app.py`.
- One shared `answer_question()` serves both `/ask` (webhook, `x-api-key`) and
  `/api/ask` (browser, `archer_session` cookie). Do not duplicate it - a test
  asserts both routes return identical answers.
- A 401 redirects to `/login` for page routes but returns JSON for `/api/`
  paths. Both halves are pinned by tests.
- Model calls go through `asyncio.to_thread`: the watsonx SDK is synchronous
  and would otherwise block the event loop for the whole round trip.
- Model calls use the watsonx **chat** API (`ChatWatsonx`), built by
  `create_llm(task)` and called through `complete()` in `archer/ai/llm.py`.
  The text-generation API is deprecated by IBM and no longer used.
- Prompts live in `prompts/*.md`, loaded at runtime and sent as chat messages.
  `<!-- role: system|user|assistant -->` markers split a prompt into messages;
  a prompt without markers is one user message. Values are substituted after
  the split, in one pass, so user text cannot create a message. A prompt
  change that alters no words can still move accuracy - it once fell from 89%
  to 11% while every unit test passed - so run the evals regardless.
- `sales.db` is generated at image build time by `scripts/generate_dataset.py`,
  from a fixed seed. Regenerate locally before running anything.
- SQL safety lives in `archer/db/query.py`: `run_select` is the only way
  generated SQL runs - read-only connection, an authorizer permitting reads of
  `sales_data` only, one statement, a deadline, a row cap. It is load-bearing
  and covered by `test_query_guard.py`. Never execute generated SQL any other
  way.

## Cost

The demo runs on a paid watsonx plan, and **IBM Cloud has no hard spending
limit**. The ceiling is `backend/archer/core/usage.py`: a daily question budget
claimed before the model is called. Do not weaken or bypass it. Set
`DEMO_DAILY_QUESTION_LIMIT=0` locally and for eval runs.

A data question costs roughly 2,300 tokens, about 88% of it the SQL generator's
few-shot examples.
