# Archer

**Ask a sales database a question in English. Get the answer, and the SQL that produced it.**

[![CI](https://github.com/oliverjhj/archer-text-to-sql/actions/workflows/ci.yml/badge.svg)](https://github.com/oliverjhj/archer-text-to-sql/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-113%20passing-brightgreen)](docs/testing.md)
[![Execution accuracy](https://img.shields.io/badge/execution%20accuracy-100%25%20on%2033%20cases-blue)](docs/evals.md)
[![Python](https://img.shields.io/badge/python-3.12-blue)](backend/pyproject.toml)
[![Licence](https://img.shields.io/badge/licence-Apache%202.0-blue)](LICENSE)

[**Live demo**](https://archer.2e8toyh6lcs9.eu-gb.codeengine.appdomain.cloud) &nbsp;·&nbsp; sign in with `demo` / `archer-demo-2026`

Built on IBM watsonx.ai, FastAPI and React. Deployed on IBM Code Engine.

![Archer answering two questions, each with the SQL it generated](docs/images/demo.png)

---

> **Note on the demo.** It runs on synthetic data and scales to zero when idle,
> so the first question may take a few seconds while a container starts. That
> is a deliberate cost decision, not a fault.

## What it does

```
"How many deals were there in 2024?"

  7,103
  SELECT COUNT(DISTINCT document_number) FROM sales_data
  WHERE STRFTIME('%Y', document_date) = '2024'
```

The generated SQL is shown beside every answer. A text-to-SQL system that hides
its query is asking to be trusted without giving you any way to check it, and
`COUNT(*)` versus `COUNT(DISTINCT document_number)` is the difference between
7,103 and 15,847 on this dataset.

## What this demonstrates

- **Measured AI accuracy, not claimed.** A 33-case evaluation suite grades by
  executing the generated SQL and comparing results, and the numbers are
  published - including the ones that were unflattering.
- **Prompt engineering treated as engineering.** Prompts are versioned files
  with changelogs, and every change is measured before and after.
- **Security designed around the model being untrustworthy.** The prompt is not
  a boundary; SELECT-only enforcement and a read-only connection are.
- **Cost control that actually refuses.** IBM Cloud has no hard spending limit,
  so the ceiling is in the application.
- **Production practices**: 116 tests, four CI jobs, automated deployment,
  non-root multi-stage container, scale-to-zero hosting.

## The number that matters

The changelog for an earlier release claimed *"96-97% accuracy maintained"*
after a model migration. Nothing substantiated it, so it got measured:

| Model | Prompts | Execution accuracy | Median latency |
|---|---|---|---|
| `llama-3-3-70b-instruct` | v2 | 92.9% | 7.25s |
| `mistral-small-3-1-24b` | v2 | 89.3% | 0.83s |
| **`mistral-small-3-1-24b`** | **v3** | **100%** | **0.50s** |

**The claim was wrong.** The migration was a trade - 3.6 points of accuracy for
roughly 8.7x lower latency - not the free win it was described as.

What closed the gap was not a bigger model. The prompt described the *columns*
but never the *values inside them*, so the model could not know that
`document_type` holds `'Credit'`, or that a flag is `'Yes'` and not `'Y'`. It
guessed, plausibly and wrongly. **Both models made the same mistake
independently**, which is what identified it as a prompt gap rather than a model
weakness.

100% on 33 cases means *no known failures*, not *no failures* - see
[`docs/evals.md`](docs/evals.md), which says so at more length.

## Architecture

![How a question becomes an answer: FastAPI claims a daily budget, a classifier routes the question, and either the SQL generator queries a read-only SQLite database or a conversational prompt answers it](docs/images/architecture.svg)

Classification is a separate model call. A combined prompt would have to decide
*and* produce SQL in one pass, and a model shown fifteen SQL examples will write
SQL for "hello".

The dataset is **generated at build time** from a seeded script - 100,000 rows,
37 columns, byte-identical for a given seed. It was previously downloaded from
object storage at startup; removing that dropped a cloud service, a credential,
a class of startup failure, and a 47MB download from every cold start.

Full detail in [`docs/architecture.md`](docs/architecture.md).

## Running it

```bash
# Backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e "backend[test]"
python scripts/generate_dataset.py          # builds sales.db
cp .env.example .env                        # then fill it in

# Frontend
npm --prefix frontend install
npm --prefix frontend run build

# Serve
.venv/Scripts/python.exe -m uvicorn main:app --app-dir backend --port 8080
```

Or build the image, which does all of it:

```bash
docker build -f backend/Dockerfile -t archer .
```

Requires an IBM Cloud API key and a watsonx.ai project. See
[`.env.example`](.env.example).

## Testing and evaluation

```bash
.venv/Scripts/python.exe -m pytest backend/tests/unit -m unit -q   # 116 tests
python evals/run_evals.py                                          # accuracy
```

The evaluation suite is deliberately **not** in CI: it makes real model calls
and needs live credentials.

## Documentation

| | |
|---|---|
| [Architecture](docs/architecture.md) | How a question becomes an answer |
| [Prompts](docs/prompts.md) | What each prompt does, what was tried and rejected |
| [Evaluation](docs/evals.md) | How accuracy is measured, and the results |
| [Security](docs/security.md) | Threat model, controls, and honest limitations |
| [Testing](docs/testing.md) | What the tests cover - and what they missed |
| [CI and automation](docs/ci.md) | What runs on every push, and how deployment works |
| [Infrastructure](infrastructure/README.md) | Deployment, scaling and cost |

## Background

Archer began as a proof-of-concept built at a UK IBM distributor to show what
natural-language querying over sales data could look like. It was a demo rather
than a system anyone used day to day.

This repository is a rebuild of that idea as a public portfolio project on my
own infrastructure, with synthetic data throughout. No employer data, code or
configuration is present, and the original deployment has been retired.

## Licence

[Apache 2.0](LICENSE).
