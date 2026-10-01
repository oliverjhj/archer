import {
  CodeSnippet,
  InlineLoading,
  InlineNotification,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  Tag,
} from '@carbon/react';
import { parseAnswer } from '../lib/answer';
import type { AnswerBlock } from '../lib/answer';
import type { ConversationEntry, Part } from '../types/api';

interface AnswerItemProps {
  entry: ConversationEntry;
}

function ResultTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    // Result tables can be far wider than the column, so they scroll
    // independently rather than forcing the page to scroll sideways.
    <div className="archer-answer__table">
      <Table size="sm" useZebraStyles>
        <TableHead>
          <TableRow>
            {headers.map((header, index) => (
              <TableHeader key={`h-${index}`}>{header}</TableHeader>
            ))}
          </TableRow>
        </TableHead>
        <TableBody>
          {rows.map((row, rowIndex) => (
            <TableRow key={`r-${rowIndex}`}>
              {row.map((cell, cellIndex) => (
                <TableCell key={`r-${rowIndex}-c-${cellIndex}`}>{cell}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

function SqlBlock({ label, query }: { label: string; query: string }) {
  return (
    // Showing the generated SQL is a deliberate transparency feature, not
    // debug output: the user can see exactly what ran.
    <div className="archer-answer__sql">
      <p className="archer-answer__sql-label">{label}</p>
      <CodeSnippet type="multi" feedback="Copied" wrapText>
        {query}
      </CodeSnippet>
    </div>
  );
}

function renderBlock(block: AnswerBlock, key: number) {
  if (block.kind === 'table') {
    return <ResultTable key={key} headers={block.headers} rows={block.rows} />;
  }

  return (
    <p className="archer-answer__text" key={key}>
      {block.spans.map((span, index) =>
        span.bold ? (
          <strong key={`${key}-s-${index}`}>{span.text}</strong>
        ) : (
          <span key={`${key}-s-${index}`}>{span.text}</span>
        ),
      )}
    </p>
  );
}

/** Prose from the model: paragraphs and **bold**, nothing else. */
function Prose({ text }: { text: string }) {
  return <>{parseAnswer(text).blocks.map(renderBlock)}</>;
}

/** One part of a structured answer. */
function PartView({ part }: { part: Part }) {
  if (part.type === 'chat' || !['ok', 'empty'].includes(part.status)) {
    return <Prose text={part.text ?? ''} />;
  }

  if (part.status === 'empty') {
    return (
      <>
        <p className="archer-answer__text">{part.text}</p>
        {part.sql && <SqlBlock label="Query attempted" query={part.sql} />}
      </>
    );
  }

  return (
    <>
      <p className="archer-answer__text">
        {part.text}
        {part.value !== null && (
          <>
            {' '}
            <strong>{part.value}</strong>
          </>
        )}
      </p>
      {part.value === null && <ResultTable headers={part.columns} rows={part.rows} />}
      {part.truncated && (
        <p className="archer-answer__note">
          Displaying the maximum of 100 rows to maintain performance.
        </p>
      )}
      {part.sql && <SqlBlock label="SQL used" query={part.sql} />}
    </>
  );
}

/** An answer from a backend that sent only the Markdown string. */
function LegacyAnswer({ answer }: { answer: string }) {
  const parsed = parseAnswer(answer);
  return (
    <>
      {parsed.blocks.map(renderBlock)}
      {parsed.note && <p className="archer-answer__note">{parsed.note}</p>}
      {parsed.sql && <SqlBlock label={parsed.sql.label} query={parsed.sql.query} />}
    </>
  );
}

/**
 * A single question/answer exchange, covering the loading, error, empty and
 * answered states.
 *
 * Everything is rendered as React elements from structured data or parsed
 * text. Nothing is injected as HTML, so model output cannot become markup.
 */
export function AnswerItem({ entry }: AnswerItemProps) {
  return (
    <article className="archer-turn">
      <div className="archer-turn__question">
        <Tag type="cool-gray" size="sm">
          You
        </Tag>
        <p>{entry.question}</p>
      </div>
      <div className="archer-turn__answer">
        <Tag type="blue" size="sm">
          Archer
        </Tag>

        {entry.pending && (
          <InlineLoading description="Generating answer..." status="active" />
        )}

        {!entry.pending && entry.error && (
          <InlineNotification
            kind={entry.error.kind === 'unauthorised' ? 'warning' : 'error'}
            lowContrast
            hideCloseButton
            title={
              entry.error.kind === 'unauthorised'
                ? 'Session expired'
                : 'Something went wrong'
            }
            subtitle={entry.error.message}
          />
        )}

        {!entry.pending && !entry.error && entry.turn &&
          entry.turn.parts.map((part, index) => <PartView key={index} part={part} />)}

        {!entry.pending && !entry.error && !entry.turn && entry.answer && (
          <LegacyAnswer answer={entry.answer} />
        )}
      </div>
    </article>
  );
}
