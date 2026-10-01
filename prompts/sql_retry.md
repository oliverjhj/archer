---
name: sql_retry
version: 1
updated: 2026-10-01
task: Ask for one corrected query after the first failed or found nothing.
placeholders: [PROBLEM, DATE_FROM, DATE_TO]
changes: |
  v1 - Added with self-correction. Sent as a follow-up message after the
       original SQL generator prompt and the query that failed, so the model
       sees its own mistake in context.
notes: |
  The hints are the causes of real failures: a column name that does not
  exist, an exact match where a partial one was needed, a date outside the
  data. Naming the date range matters because "last year" can land on a year
  the data does not reach.
---
That query {{PROBLEM}}

Write one corrected SQLite query for the same question. Check that every column name is in the column list, that text filters use LOWER(column) LIKE LOWER('%term%') rather than an exact match, and that any date filter falls within the data, which runs from {{DATE_FROM}} to {{DATE_TO}}. Return only the SQL.
