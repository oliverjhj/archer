// Parsing for the Markdown-ish answers the backend returns.
//
// The backend produces a small, known set of shapes rather than arbitrary
// Markdown, so this is a deliberately narrow parser for those shapes rather
// than a general Markdown implementation:
//
//   "Based on the data, the answer is: **1,240**\n\n*(SQL used: SELECT ...)*"
//   "Here is the data you requested:\n\n| a | b |\n|---|---|\n| 1 | 2 |\n
//    *(Note: Displaying the maximum of 100 rows...)*\n*(SQL used: SELECT ...)*"
//   "I couldn't find any data matching that request.\n\n*(Query attempted: ...)*"
//   plain conversational text, which may include "- item" lists
//
// Everything it produces is plain data rendered as React elements. Nothing
// here emits HTML, and no caller uses dangerouslySetInnerHTML, so a hostile
// string in the model output cannot become markup.

export interface TextSpan {
  text: string;
  bold: boolean;
}

export type AnswerBlock =
  | { kind: 'text'; spans: TextSpan[] }
  | { kind: 'list'; items: TextSpan[][] }
  | { kind: 'table'; headers: string[]; rows: string[][] };

export interface ParsedAnswer {
  blocks: AnswerBlock[];
  /** The SQL transparency footnote, shown separately from the prose. */
  sql: { label: string; query: string } | null;
  /** The row-truncation notice, when the backend applied its 100-row cap. */
  note: string | null;
}

const SQL_FOOTNOTE = /\*\(\s*(SQL used|Query attempted):\s*([\s\S]*?)\s*\)\*/;
const NOTE_FOOTNOTE = /\*\(\s*Note:\s*([\s\S]*?)\s*\)\*/;
const BOLD = /\*\*([\s\S]+?)\*\*/g;
const LIST_ITEM = /^\s*(?:[-*]|\d+[.)])\s+/;

/** Split a line into bold and plain spans. */
function parseSpans(line: string): TextSpan[] {
  const spans: TextSpan[] = [];
  let lastIndex = 0;

  BOLD.lastIndex = 0;
  let match = BOLD.exec(line);
  while (match !== null) {
    if (match.index > lastIndex) {
      spans.push({ text: line.slice(lastIndex, match.index), bold: false });
    }
    spans.push({ text: match[1], bold: true });
    lastIndex = match.index + match[0].length;
    match = BOLD.exec(line);
  }

  if (lastIndex < line.length) {
    spans.push({ text: line.slice(lastIndex), bold: false });
  }

  return spans.length > 0 ? spans : [{ text: line, bold: false }];
}

/** True for a Markdown table separator row such as |---|---|. */
function isSeparatorRow(line: string): boolean {
  return /^\|[\s:|-]+\|$/.test(line.trim());
}

/** Split a Markdown table row into trimmed cells. */
function parseRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '');
  return trimmed.split('|').map((cell) => cell.trim());
}

/**
 * Parse a backend answer into renderable blocks.
 *
 * Never throws: anything unrecognised falls through as plain text, because a
 * parser failure must not cost the user their answer.
 */
export function parseAnswer(answer: string): ParsedAnswer {
  let working = answer;
  let sql: ParsedAnswer['sql'] = null;
  let note: string | null = null;

  const sqlMatch = working.match(SQL_FOOTNOTE);
  if (sqlMatch) {
    sql = { label: sqlMatch[1], query: sqlMatch[2].trim() };
    working = working.replace(SQL_FOOTNOTE, '');
  }

  const noteMatch = working.match(NOTE_FOOTNOTE);
  if (noteMatch) {
    note = noteMatch[1].trim();
    working = working.replace(NOTE_FOOTNOTE, '');
  }

  const lines = working.split('\n');
  const blocks: AnswerBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (line.trim().startsWith('|')) {
      const tableLines: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith('|')) {
        tableLines.push(lines[index]);
        index += 1;
      }

      const dataLines = tableLines.filter((row) => !isSeparatorRow(row));
      if (dataLines.length > 0) {
        const [headerLine, ...rowLines] = dataLines;
        blocks.push({
          kind: 'table',
          headers: parseRow(headerLine),
          rows: rowLines.map(parseRow),
        });
      }
      continue;
    }

    // Consecutive "- item", "* item" or "1. item" lines are one list. The
    // chat replies use them when explaining a query step by step.
    if (LIST_ITEM.test(line)) {
      const items: TextSpan[][] = [];
      while (index < lines.length && LIST_ITEM.test(lines[index])) {
        items.push(parseSpans(lines[index].replace(LIST_ITEM, '').trim()));
        index += 1;
      }
      blocks.push({ kind: 'list', items });
      continue;
    }

    if (line.trim().length > 0) {
      blocks.push({ kind: 'text', spans: parseSpans(line.trim()) });
    }
    index += 1;
  }

  return { blocks, sql, note };
}
