# Prompts

The prompts live in [`prompts/`](../prompts) as versioned Markdown files rather
than as string literals in Python. They are the part of this system most likely
to change, most likely to change behaviour when they do, and least readable
buried in a source file. As files they can be reviewed and diffed like anything
else, and [`docs/evals.md`](evals.md) can attribute a change in accuracy to a
change in a prompt.

Each file carries front matter recording its version, purpose, placeholders and
what changed. The loader strips it before the model sees it.

## The pipeline

Three prompts, with a plan deciding which runs:

```
question + last 3 exchanges ──▶ planner ──┬── data ──────▶ sql_generator ──▶ SQLite ──▶ formatter
                                          ├── chat ──────▶ chat
                                          └── off_topic ─▶ fixed decline (no model call)
```

Splitting planning from generation is the most consequential design decision
here. A combined prompt would have to decide *and* produce SQL in one pass, and
a model that has just been shown fifteen SQL examples will write SQL for
"hello". Separating them means the SQL path never has to consider small talk,
and never sees the conversation either: it receives one standalone question.

## The planner

**One job: return a JSON plan.** The kind of reply, and the question restated
so it stands on its own:

```json
{"kind": "data", "parts": [{"kind": "data", "question": "How many deals did Helix Bridge Holdings Ltd do?"}]}
```

It sees the last three exchanges - each question, the SQL that answered it,
and up to ten rows of its result - so "the third one" can be read off the
previous result and "and for 2024?" can borrow the rest of the previous
question. The restated question is shown to the user as **Interpreted as**,
which makes a wrong reading obvious at once rather than leaving it buried in
the SQL.

Three rules carry most of the weight:

1. **Copy a standalone question exactly.** Single questions then reach the SQL
   generator unchanged, which is what kept the original suite at 100%. The code
   enforces it as well: with no earlier exchange there is nothing to resolve,
   so the question is used as typed whatever the planner returns.
2. **Anything about the sales data is data, whatever the period.** The first
   version had one off-topic example, *"Who won the World Cup in 2018?"*, and
   the model learned that a question with a year in it might be off-topic: it
   declined *"How many deals were there in 2024?"*. The eval suite caught four
   such declines; the example was replaced and the rule written down.
3. **Name end users as end users.** "The second one" from a list of end users
   must become *"end user Orbit Vertex Data PLC"*, because the SQL generator
   reads an unqualified company name as a partner.

The reply format is enforced with the chat API's JSON mode. A reply that still
cannot be parsed falls back to the behaviour before the planner existed: the
message is treated as a data question, as typed.

**Off-topic requests are declined with a fixed message**, not a generated one:
one model call instead of two, the same reply every time, and no free text for
a jailbreak to work on.

## The SQL generator

The large one, and the one that costs money: **2,013 input tokens on every
question**, almost all of it few-shot examples.

### What it is told

1. **Default columns.** Unless asked to aggregate, return a fixed set of eight
   columns rather than `SELECT *`. Someone asking to "see the deals" wants a
   readable table, not 37 columns of postcodes and contract numbers.
2. **Vocabulary mapping.** Domain words to columns: "partner" is
   `customer_name`, "hardware" is `item_group = 'IBM CCHW'`, and a "deal" is a
   `document_number` rather than a row.
3. **Column values.** Added in v3 - see below.
4. **Deal counting.** "How many deals" is `COUNT(DISTINCT document_number)`,
   because a deal spans several lines. Without this the model counts rows and
   over-reports by roughly 2.2x. It is the most dangerous error the system can
   make, because the answer looks entirely plausible.
5. **Subqueries for top-N.** "The three biggest deals" cannot be `ORDER BY
   revenue LIMIT 3` - that returns three *lines*. It needs a subquery that
   ranks deals by summed revenue and then returns all of their lines.
6. **Existence checks return names, not counts.** See below.
7. **A row cap** of 100.

### The two changes that mattered

**Existence checks (v2).** The model used to answer "is there a partner called
X?" with `SELECT COUNT(*)`. A count of zero cannot distinguish "no such
partner" from "the query was wrong", and it gives the user nothing to correct.
Returning matching names makes a near-miss visible: ask for "Galexy" and you
get back "Galaxy Crest Global PLC" and immediately understand what happened.

**Column values (v3).** The prompt described the columns but never the values
inside them. The model could not know that `document_type` holds `'Credit'`, or
that a flag is `'Yes'` and not `'Y'`, so it guessed - plausibly, and wrongly.
Three of the four baseline failures came from this, and **both models made the
same `'Y'` mistake independently**, which is what identified it as a gap in the
prompt rather than a weakness in the model.

The fix is a section listing the enumerable values verbatim. It is unglamorous,
and it took the suite from 89.3% to 100%.

**One disambiguation rule (v3).** A company name mentioned without the words
"end user" means `customer_name`. Previously the model chose between two
plausible columns with nothing to go on, and about half the time chose the one
the user did not mean. Ambiguity in the question needs a documented default in
the prompt, not a coin toss.

### Deal values (v4)

Rule 4b: for the average, smallest or largest *deal* value, total each
deal first, then aggregate. Without it the model averaged line revenue within
each deal. Its first wording said only what a deal's value is, and the model
generalised: "the end user who bought the most licences" started being ranked
by revenue. The rule now says it applies only to questions about deal values,
and nothing else.

### What was tried and rejected

- **Dropping the few-shot examples** to cut the 2,013-token cost. The examples
  are what encode the deal-versus-line distinction and the top-N subquery
  pattern; describing those in prose did not survive contact with the model.
  The cost stands until there is a measured reason to change it.
- **Letting the model choose its own columns.** Produces a different shape for
  every question and makes the frontend's table rendering unpredictable.
- **A combined plan-and-generate prompt.** Fewer calls, but it writes SQL
  for greetings.
- **Sending the conversation to the SQL generator.** It would let the model
  resolve follow-ups itself, at the cost of changing the prompt the suite had
  measured at 100%, on every question. Restating the question first keeps the
  SQL prompt exactly as it was.

## The retry

`sql_retry.md` is not a prompt on its own: it is a follow-up message. The SQL
generator's messages are sent again, then the failed query as the model's own
previous reply, then this - what went wrong, and three things to check: that
every column exists, that text filters match partially rather than exactly,
and that any date falls inside the data. Those are the causes of the failures
actually seen.

## The summary

`summary.md` asks for one or two sentences about a result table, using only
figures in it, quoted exactly, and never calculating new ones. The rule is
there because the reply is checked: a percentage the model worked out cannot
be traced to the result, so it would be dropped anyway. A second rule - no
"all are above X" - came from the first eval run, where the fifth of five was
exactly X.

## The conversational prompt

Answers data-related conversation: explaining an earlier answer or its SQL,
what a column, value or IBM product means, and what Archer can do. It receives
the conversation and a glossary built from the same column descriptions the
guide in the app shows (`backend/archer/db/catalogue.py`), and is told to use
only those - never to invent a figure. Asked for new numbers, it says to ask
for them as a question.

The capability reply is a fixed string, deliberately. It answers "what can you
do", which is the first thing most people ask, and it is the one response that
should never drift.

Its dataset date range is **injected at runtime** from the database. It used to
be hardcoded, alongside "Current year: 2026" - the kind of detail that is
correct on the day it is written and quietly wrong from 1 January onwards.

## Prompt injection

A prompt is split into its chat messages before any value is substituted,
and substitution is a single pass that never re-reads what it inserted. So a
question cannot start a new message - a role marker typed into a question is
just text - and cannot pull another value into the prompt.

That keeps the prompt's structure intact, and no more. The real defences are
downstream and structural, enforced by SQLite on the only connection that runs
generated SQL (see [`security.md`](security.md)):

- the connection is opened **read-only**
- an authorizer permits reading `sales_data` and nothing else - no `PRAGMA`,
  `ATTACH`, `load_extension` or internal tables
- only one statement can run, and it must start with `SELECT` or `WITH`
- a deadline interrupts runaway queries, and results are capped at 100 rows

An injection that persuades the model to write `DROP TABLE` produces a refused
query and a log line, not a dropped table. **The prompt is not a security
boundary and is not treated as one.**

## Changing a prompt

1. Edit the file in `prompts/` and bump its `version`.
2. Record what changed, and why, in the front matter.
3. Run the evals before and after: `python evals/run_evals.py`.
4. Put the numbers in [`docs/evals.md`](evals.md).

Step 3 is not a formality. Moving these prompts from Python into files - a
change that altered no words at all - dropped accuracy from 89.3% to 10.7%,
because the loader stripped a trailing newline that told the model to start
writing on a new line. Every one of the unit tests passed. Only the evals saw
it.

## How a prompt becomes chat messages

The application uses the watsonx **chat** API, which takes a list of messages
with roles rather than one block of text. A prompt file marks where each
message starts with an HTML comment, which keeps the file readable as
Markdown:

```markdown
<!-- role: system -->
You are a SQLite expert...

<!-- role: user -->
{{USER_QUERY}}
```

A prompt with no markers is sent as a single user message. The three current
prompts have none: they were written for the text-generation API, and sent
unchanged as one message they score the same 100% (see
[`evals.md`](evals.md)), so restructuring them would have been change without
a measured reason. The trailing-newline fragility above belonged to the
text-generation API; the chat API wraps each message in the model's own
template, so it no longer applies.
