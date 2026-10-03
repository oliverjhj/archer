# Prompts

The prompts live in [`prompts/`](../prompts) as Markdown files. They are the part of the system most likely to change and most
likely to change behaviour when they do, so they are kept where they can be
read, reviewed and diffed, and every change is measured with the
[evaluation suite](evals.md).

Each file starts with front matter: name, version, purpose, placeholders and a
changelog. The loader strips it before the model sees anything.

## The five prompts

| File | Version | Job |
|---|---|---|
| `planner.md` | 2 | Decide what kind of reply a message needs, and restate follow-ups so they stand alone |
| `sql_generator.md` | 4 | Write one SQLite query for a standalone question |
| `sql_retry.md` | 1 | Ask for one corrected query when the first fails or finds nothing |
| `summary.md` | 1 | Describe a result table in a sentence or two |
| `chat.md` | 3 | Explain answers, SQL and terms, without querying |

```
question + last 3 exchanges ──▶ planner ──┬── data ──────▶ sql_generator ──▶ SQLite ──▶ summary
                                          │                     │ fails or finds nothing
                                          │                     └──▶ sql_retry (once)
                                          ├── chat ──────▶ chat
                                          ├── clarify ───▶ a question with options (no further call)
                                          └── off_topic ─▶ fixed decline (no further call)
```

Planning is a separate call from SQL generation. A combined prompt would have
to decide and write SQL in one pass, and a model shown fifteen SQL examples
writes SQL for "hello". With them separate, the SQL generator only ever sees a
standalone question and never the conversation.

## The planner

The planner returns a JSON plan: the kind of reply, and for each part of the
message the question restated so it stands on its own.

```json
{"kind": "data", "parts": [{"kind": "data", "question": "How many deals did Helix Bridge Holdings Ltd do?"}]}
```

It sees the last three exchanges: each question, the SQL that answered it and
up to ten rows of its result. That lets it read "the third one" off the
previous table and borrow the rest of a previous question for "and for 2024?".
The restated question is shown to the user as *Interpreted as*, so a wrong
reading is visible straight away.

The rules that matter most:

1. A standalone question is copied exactly. The code enforces this too: with
   no earlier exchange there is nothing to resolve, so the question is used as
   typed whatever the planner returns.
2. Anything about the sales data is a data question, whatever period it names.
   An off-topic example containing a year once taught the model to decline
   *"How many deals were there in 2024?"*.
3. End users are named as end users. "The second one" from a list of end users
   becomes *"end user Orbit Vertex Data PLC"*, because the SQL generator reads
   an unqualified company name as a partner.
4. A message can ask up to three things. *"Revenue in 2023, and what does IBM
   SOFT mean?"* becomes a data part and a chat part, answered in order. A
   question that only reads like two, such as *"the top partner and how many
   deals they did"*, stays one and is answered with a subquery. A fourth part
   is dropped, and the answer says so.
5. It asks only when it would otherwise have to guess: a message that points
   at something the conversation doesn't contain, or names nothing at all. The
   reply is a short question with two or three options, each a complete
   question the user can send with one click.

The code also limits clarifying questions. One is accepted only when the
message contains a word that points at something (*one, it, they, that,
those...*). Anything else is answered as typed, because the prompt alone
didn't stop the model asking about clear questions.

The reply format uses the chat API's JSON mode. If the reply still can't be
parsed, the message is treated as a single data question, as typed.

Off-topic requests get a fixed decline written in the code: one model call
instead of two, the same reply every time, and no generated text for a
jailbreak to work on.

## The SQL generator

The largest prompt, at about 2,000 input tokens, most of it fifteen worked
examples. It is told:

1. **Default columns.** Unless the question aggregates, return a fixed set of
   eight readable columns instead of all 37. The same list drives the
   column highlights in the in-app guide (`backend/archer/db/catalogue.py`),
   and a test keeps the two in step.
2. **Vocabulary.** "Partner" is `customer_name`, "hardware" is
   `item_group = 'IBM CCHW'`, and a deal is a `document_number`, not a row.
3. **Column values.** The enumerable values, listed verbatim: `document_type`
   holds `'Credit'`, the multi-year flag is `'Yes'` or `'No'`, and so on.
   Without this the model guesses plausible values that match nothing.
4. **Deal counting.** "How many deals" is `COUNT(DISTINCT document_number)`. A
   deal spans about 2.2 lines on average, so counting rows over-reports, and
   the wrong answer looks plausible.
5. **Deal values.** For the average, smallest or largest deal, total each deal
   first and then aggregate. The rule is worded to apply only to deal values:
   a broader version led the model to rank "most licences" by revenue.
6. **Top-N deals need a subquery.** "The three biggest deals" ranks deals by
   summed revenue and returns all their lines. `ORDER BY revenue LIMIT 3`
   would return three lines.
7. **Existence checks return names.** "Is there a partner called X?" returns
   the matching names, not a count. Ask for "Galexy" and you see "Galaxy Crest
   Global PLC", which shows the near-miss.
8. **A company name without "end user" means `customer_name`.** Without this
   default the model picked between two plausible columns.
9. **At most 100 rows.**

The column list itself is read from the database at runtime.

Tried and rejected:

- Dropping the examples to save tokens. They are what teach the deal-versus-line
  distinction and the top-N subquery, and prose descriptions of those didn't
  work.
- Letting the model choose its own columns. Every answer came back a different
  shape.
- Sending the conversation to the SQL generator. Restating the question first
  keeps the SQL prompt the same for every question.

## The retry

`sql_retry.md` is sent as a follow-up message in the same exchange. The SQL
generator's messages are sent again, then the failed query as the model's own
reply, then this: what went wrong, and a check that every column exists, that
text filters match partially, and that any date falls inside the data. Those
are the causes of the failures actually seen.

The retry runs once, only after an error or an unexpectedly empty result, and
its query is kept only if it does better. It never runs after the query guard
refuses a query, or after an existence check finds nothing, where "no such
partner" is the right answer.

## The summary

`summary.md` asks for one or two sentences about a result table, quoting only
figures in it and never calculating new ones. The reply is checked: every
number must appear in the result, or the summary is dropped and the table is
shown alone. Summaries are written only for rankings and breakdowns, not for
single values, lists of names or deal lines.

## The chat prompt

`chat.md` answers conversation about the data: what an earlier answer or its
SQL means, what a column, value or IBM product is, and what Archer can do. It
gets the conversation and a glossary built from the same column descriptions
the in-app guide shows, and is told to use only those. Asked for new figures,
it tells the user to ask a question so a query can run.

The answer to "what can you do" is fixed text in the prompt, so the most
common first question always gets the same reply. The dataset's date range is
filled in from the database at runtime.

## How a prompt becomes chat messages

The application uses the watsonx chat API, which takes a list of messages with
roles. A prompt file marks where each message starts with an HTML comment,
which keeps it readable as Markdown:

```markdown
<!-- role: system -->
You are Archer, a sales data assistant...

<!-- role: user -->
{{CONVERSATION}}
```

`planner.md`, `chat.md` and `summary.md` use these markers. `sql_generator.md`
and `sql_retry.md` have none and are sent as a single user message.

The prompt is split into messages before any value is substituted, and
substitution is one pass that never re-reads what it inserted. So text in a
question can't start a new message or pull another value into the prompt. That
protects the prompt's structure and nothing more: a question can still ask the
model to do something else. What protects the database is the read-only,
single-table query connection described in [security](security.md).

## Changing a prompt

1. Edit the file in `prompts/` and bump its `version`.
2. Record what changed, and why, in the front matter.
3. Run the evaluation suite before and after: `python evals/run_evals.py`.
4. Add the result to [evals](evals.md).

Run the suite even for a change that looks cosmetic. Moving the prompts out of
Python once dropped accuracy from 89% to 11% while every unit test passed: the
loader stripped a trailing newline the model relied on.
