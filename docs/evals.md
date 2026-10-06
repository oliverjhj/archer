# Evaluation

The suite in [`evals/`](../evals) measures whether Archer gives the right
answer. It runs real questions through the application's own pipeline against
the live model, and records the result of every case.

## How accuracy is measured

The reference query and the generated query both run against the same
database, and their result sets are compared. Two different queries can be
equally correct, so the SQL text is never compared.

| Metric | Meaning |
|---|---|
| Execution accuracy | The result sets are identical. The headline number for data questions |
| Value accuracy | Every value in the reference result appears in the generated one, which catches the right numbers with extra columns |
| Valid SQL rate | The generated query ran at all |
| Routing accuracy | The planner chose the right kind of reply: data, chat or decline |
| Interpretation | A follow-up was restated correctly. Graded separately, so a failure shows whether the planner or the SQL went wrong |
| Hold-out | Cases written once and never tuned against |

Overall accuracy counts a data case as passed on execution accuracy, a chat
case when the reply contains what it must, and a decline case when the request
is declined.

## The cases

61 cases in [`evals/cases.yaml`](../evals/cases.yaml), each stating what the
pipeline should do:

| Category | Cases | What it tests |
|---|---|---|
| aggregate | 12 | Totals, counts and averages, including deal values |
| filter | 7 | Questions narrowed by partner, period, product or flag, and breakdowns |
| ranking | 5 | Top-N questions, including deals ranked by total value |
| existence | 5 | "Is there a partner called...", answered with matching names |
| listing | 3 | Distinct values of a column |
| followup | 6 | Questions that only make sense after an earlier exchange |
| conversation | 3 | Greetings, thanks and "what can you do", answered without a query |
| chat | 4 | Explanations of answers, SQL and terms |
| decline | 4 | Off-topic requests |
| multipart | 2 | Two questions in one message, graded part by part |
| clarify | 2 | Messages that must be met with a clarifying question |
| holdout | 8 | Written once, run, never tuned against |

Conversation cases carry a scripted earlier exchange, so a follow-up case tests
the follow-up rather than a re-run of the first answer. Every case that should
be answered directly also counts as a must-not-clarify case: a clear question
met with a question fails.

## Current result

`mistral-small-3-1-24b-instruct-2503` for every step, with planner v2, SQL
generator v4, chat v3, retry v1 and summary v1:

| Metric | Result |
|---|---|
| Overall | 98.4% (60 of 61) |
| Execution accuracy, data questions | 97.6% |
| First attempt only, before the retry | 95.1% |
| Routing | 100% |
| Interpretation | 100% |
| Valid SQL | 100% |
| Hold-out | 87.5% (7 of 8) |
| Median latency | 0.95s |

The one failure is a hold-out. Asked *"Which partner had the most credit notes
in 2023?"*, the model counts lines instead of distinct documents. It stays
unfixed so the hold-outs remain a fair measure. A fix would need new hold-out
cases written first.

## What the score means

A high score on a suite means it has stopped finding faults. It does not mean
Archer is accurate on any question. Three limits apply:

1. The same person wrote the cases and fixed the failures, and a suite you
   tune against gradually becomes a training set. The hold-outs are the
   check on that.
2. The dataset is synthetic and clean. Real data has nulls, inconsistent
   spellings and duplicate entities.
3. Most questions are well formed. Real users ask ambiguous and truncated ones.

## Choosing the model

Earlier in the project the model moved from `llama-3-3-70b-instruct` to the
smaller `mistral-small-3-1-24b-instruct-2503`, and a changelog said accuracy
was maintained at 96-97%. No suite existed then, and when one was built
neither model reached that figure:

| Model | SQL prompt | Execution accuracy | Median latency |
|---|---|---|---|
| `llama-3-3-70b-instruct` | v2 | 92.9% | 7.25s |
| `mistral-small-3-1-24b` | v2 | 89.3% | 0.83s |
| `mistral-small-3-1-24b` | v3 | 100% | 0.50s |

The move had traded 3.6 points of accuracy for about 8.7 times lower latency.
For an interactive demo that was the right trade, and Mistral Small was kept.

The gap closed through the prompt. It described the columns but not the values
inside them, so the model could not know that `document_type` holds `'Credit'`
or that a flag is `'Yes'` and not `'Y'`. Both models made the same `'Y'`
mistake, which pointed at the prompt rather than the model:

| Failing case | Behaviour | Fix |
|---|---|---|
| `credit-total` | Searched `item_description LIKE '%credit%'` | Listed the `document_type` values |
| `multi-year-deals` | Used `'Y'` | Listed the flag values |
| `revenue-for-named-customer` | Filtered `end_user_company_name` | Rule: an unqualified company name means `customer_name` |
| `top-3-end-users` | Failed on Llama only | Fixed by the same changes |

Each step can use a different model through `WATSONX_MODEL_ID_<STEP>`. Mistral
Small stays on every step until a larger model fixes at least two cases with no
regressions.

## Results history

Each row is a full run on the same generated dataset. The suite grew as
features were added.

| Change | Cases | Overall | Hold-out | Median latency |
|---|---|---|---|---|
| Column values in the SQL prompt (v3) | 33 | 100% | - | 0.50s |
| Chat API | 34 | 100% | - | 0.56s |
| Planner for follow-ups, chat and declines | 52 | 100% | 6 of 6 | 0.89s |
| Self-correction and summaries | 55 | 98.2% | 5 of 6 | 0.95s |
| Multi-part messages and clarifying questions | 61 | 98.4% | 7 of 8 | 0.95s |

The JSON record of each run is in [`evals/results/`](../evals/results), with
the model, every prompt version, and tokens per case.

## Running the suite

```bash
python evals/run_evals.py                                    # current model
python evals/run_evals.py --model meta-llama/llama-3-3-70b-instruct
python evals/run_evals.py --output evals/results/run.json    # keep the full record
python evals/run_evals.py --only credit-total                # one case
python evals/run_evals.py --no-retry --no-summaries          # measure what each adds
```

It needs `IBM_API_KEY` and `PROJECT_ID` in `.env` and a built dataset
(`python scripts/generate_dataset.py`). The daily ceiling doesn't apply: the
suite calls the pipeline directly, not through the web routes.

The suite calls the same `run_turn()` and `run_select()` as the application, so
it measures what the demo runs. It is not in CI because it makes real model
calls and needs live credentials. Run it before and after any change to a
prompt or a model.

A full run is about 230,000 input tokens, roughly 3p. What each kind of
message costs is in [infrastructure](../infrastructure/README.md#what-it-costs).
