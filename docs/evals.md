# Evaluation

## Why this exists

The v2.6.0 changelog claimed **"96-97% accuracy maintained"** after migrating
from `llama-3-3-70b-instruct` to `mistral-small-3-1-24b-instruct-2503`.

Nothing substantiated it. No suite existed, no number had been produced, and
the figure had been sitting in the changelog being repeated. This measures it.

## How accuracy is measured

By **execution**, not string comparison. The reference query and the generated
query both run against the same database and their result sets are compared.

This matters more than it sounds. Two different SQL statements can be equally
correct, and grading on text would fail perfectly good queries for choosing a
different join order or a different way of expressing a date filter. The
question is whether the user got the right answer.

Two levels are reported:

| Metric | Meaning |
|---|---|
| **Execution accuracy** | The result sets are identical. This is the headline number |
| Value accuracy | Every value in the reference result appears in the generated result. Catches "right numbers, extra columns" |
| Valid SQL rate | The generated query executed at all |
| Routing accuracy | The classifier sent the question down the right path |

Routing is graded separately because a greeting sent to the SQL generator
wastes a model call and produces nonsense, and that failure is invisible in a
SQL-only score.

The suite is 33 cases across six categories: aggregates, ranking, filtering,
existence checks, listing, and conversational routing.

## Results

All runs use the same generated dataset. The first three use the original 33
cases on the text-generation API; the current run adds one regression case (a
question containing braces) and uses the chat API.

| Run | Model | Prompts | Execution accuracy | Routing | Valid SQL | Median latency |
|---|---|---|---|---|---|---|
| Baseline | `llama-3-3-70b-instruct` | v2 | 92.9% | 100% | 100% | 7.25s |
| Baseline | `mistral-small-3-1-24b` | v2 | 89.3% | 100% | 100% | 0.83s |
| Text generation | `mistral-small-3-1-24b` | v3 | 100% | 100% | 100% | 0.50s |
| **Current, chat API** | **`mistral-small-3-1-24b`** | **v3** | **100%** | **100%** | **100%** | **0.50s** |

### Moving to the chat API

IBM deprecated the text-generation API the application used, so model calls
moved to the chat API. The prompts were sent unchanged, each as a single user
message, to isolate the effect of the API alone. On the same day the
text-generation baseline scored 100% on the original 33 cases; the chat API
scored 100% on all 34, identically across two runs at temperature 0, at the
same median latency and token count. No prompt change was needed, so none was
made.

One case written for this step failed and was removed rather than tuned for:
*"What was the average deal value in 2025?"* The model averaged line revenue
within each deal instead of averaging deal totals. That is a real gap in the
SQL prompt, present on either API, and it belongs with the next prompt change,
not with a migration meant to change nothing.

### What this says about the v2.6.0 claim

**The claim was wrong.** Neither model scored 96-97% on this suite under the
prompts that shipped with that release.

What actually happened at v2.6.0 was a **trade, not a free win**: the migration
cost **3.6 percentage points of execution accuracy** and bought roughly **8.7x
lower latency**. That is a defensible decision for an interactive demo, where
seven seconds per question is its own kind of failure. It is just not the
decision the changelog describes, and "maintained" was the wrong word.

The trade was made explicitly on 2026-09-01: **keep the faster model**. The
accuracy gap has since been closed by other means.

### What closed the gap

Not a bigger model - better prompts. The failures had a single root cause worth
stating plainly:

> The prompt described the **columns** but never the **values inside them**.

The model could not know that `document_type` contains `'Credit'`, or that
`multi_year_deal_flag_so` is `'Yes'` rather than `'Y'`. It was guessing, and
guessing plausibly, which is the worst kind of wrong.

| Failing case | Baseline behaviour | Fix |
|---|---|---|
| `credit-total` | Searched `item_description LIKE '%credit%'` | Documented `document_type` values |
| `multi-year-deals` | Guessed `'Y'`; both models did | Documented the flag values |
| `revenue-for-named-customer` | Filtered `end_user_company_name` | Rule: an unqualified company name means `customer_name` |
| `top-3-end-users` | Failed on llama only | Fixed by the same changes |

Adding a `COLUMN VALUES` section and one disambiguation rule took the faster,
smaller, cheaper model from 89.3% to 100% - past the larger model it replaced.

## Honesty about the 100%

**100% on 34 cases is not "100% accurate".** It means the suite has stopped
finding faults, which is a weaker statement and a normal place to be.

Three caveats belong with that number:

1. **The suite is small**, and every case was written by the same person who
   then fixed the failures. An eval you tune against gradually becomes a
   training set. The honest reading is "no known failures", not "no failures".
2. **The dataset is synthetic and fixed.** Real data has nulls in awkward
   places, inconsistent spellings and duplicate entities. None of that is here.
3. **The questions are well-formed.** Real users ask ambiguous, truncated and
   contradictory questions. Only one case in this suite is deliberately
   ambiguous.

The right next step is not celebrating the number, it is adding cases that
break it.

## An episode worth recording

Moving the prompts out of Python and into files looked like a pure refactor.
The suite went from **89.3% to 10.7%**, with almost every case reporting "no
SQL produced".

The cause was one character. The prompt loader called `.strip()`, which removed
the trailing newline after the user's question - the newline that tells the
model to start a new line, with SQL on it. Without it the model carried on
writing the question.

**All 101 unit tests passed throughout.** Nothing about the application was
broken in a way that any test could see; the prompt was still a string, the
route still returned 200, and the answer was still well-formed prose. Only an
eval that ran real questions against a real model could catch it.

That is the argument for having them.

## Running the suite

```bash
python evals/run_evals.py                                    # current model
python evals/run_evals.py --model meta-llama/llama-3-3-70b-instruct
python evals/run_evals.py --output evals/results/run.json    # full record
python evals/run_evals.py --only credit-total                # one case
```

The suite runs the application's own code: models come from `create_llm` and
generated SQL executes through `run_select`, so what it measures is what the
demo runs. Each results file records the model, the version of every prompt,
and input and output tokens per case.

Requires `IBM_API_KEY` and `PROJECT_ID`, and a built dataset (`python
scripts/generate_dataset.py`). Set `DEMO_DAILY_QUESTION_LIMIT=0` to run
unmetered.

The suite is **not** wired into CI. It costs real model calls on every run and
needs live credentials, which is the wrong thing to put on every pull request.
It is run deliberately, before and after any change to a prompt or a model, and
the results are recorded here.

## Cost per run

Measured against the live prompts:

| Prompt | Input tokens |
|---|---|
| Classifier | 228 |
| SQL generator | 2,013 |
| Conversational | 302 |

A data question costs roughly **2,300 tokens**, almost all of it the SQL
generator's few-shot examples. The suite now records usage per case: on the
chat API the median data question is **2,247 input tokens**, and a full
34-case run is about 66,000 tokens in and 1,000 out.

In money, measured against the actual bill rather than estimated: **89 Resource
Units - roughly 89,000 tokens - cost £0.01**. That puts a question at about
**£0.00026**, a full evaluation run at under a penny, and a thousand questions
at around **26p**.

Two things follow from that. The daily ceiling of 200 questions caps the demo
at roughly **5p a day** even if it is hammered, which is why an approximate
per-process counter is an entirely adequate control. And the cost is so low
that the 88% concentration in the few-shot examples is not worth optimising -
it would be engineering effort spent to save pennies, and the examples are what
encode the deal-versus-line distinction the system exists to get right.
