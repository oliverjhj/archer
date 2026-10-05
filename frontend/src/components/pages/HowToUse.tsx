import { useEffect, useState } from 'react';
import {
  Accordion,
  AccordionItem,
  InlineLoading,
  InlineNotification,
} from '@carbon/react';
import { apiUrl } from '../../api/client';
import { EXAMPLE_QUESTIONS } from '../../lib/examples';
import { ExampleQuestions } from '../ExampleQuestions';

interface SchemaColumn {
  name: string;
  type: string;
  common: boolean;
  description: string;
}

interface Schema {
  table: string;
  row_count: number;
  date_from: string | null;
  date_to: string | null;
  columns: SchemaColumn[];
  known_values: Record<string, string[]>;
}

interface HowToUseProps {
  busy: boolean;
  onAsk: (question: string) => void;
}

// Words the SQL prompt maps to particular columns or values (rule 2 of
// prompts/sql_generator.md). Telling a visitor up front saves them finding
// out by asking a question that misses.
const VOCABULARY: [string, string][] = [
  ['partner, customer', 'the company that placed the order (customer_name)'],
  ['end user', 'the organisation the partner sold on to (end_user_company_name)'],
  ['deal', 'one invoice or credit, which can have several lines (document_number)'],
  ['software, services, hardware', 'IBM SOFT, IBM SERV and IBM CCHW'],
  ['our, total, overall', 'across the whole dataset, not one company'],
];

function NameList({ items }: { items: [string, string][] }) {
  return (
    <dl className="archer-guide__columns">
      {items.map(([name, meaning]) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{meaning}</dd>
        </div>
      ))}
    </dl>
  );
}

const describe = (columns: SchemaColumn[]): [string, string][] =>
  columns.map((column) => [column.name, column.description]);

/**
 * How to use Archer: what to ask, what comes back, and what the data holds.
 *
 * Without this, a visitor is guessing at column names, and the questions
 * people invent while guessing are the ones that come back empty. The values
 * section exists for the same reason the prompt has one: someone who has to
 * guess whether a flag is 'Yes' or 'Y' will guess wrong, exactly as the model
 * did before it was told.
 *
 * Asking is the first half, read by everyone; the data is the second, used as
 * reference. The two longest lists sit in expanders so the page stays short
 * for someone reading it to get started.
 */
export function HowToUse({ busy, onAsk }: HowToUseProps) {
  const [schema, setSchema] = useState<Schema | null>(null);
  const [failed, setFailed] = useState(false);

  // Fetched when the page opens rather than with the app: most visitors ask
  // a question without ever reading this, and there is no reason to spend a
  // request on them.
  useEffect(() => {
    let cancelled = false;
    fetch(apiUrl('/api/schema'), { credentials: 'include' })
      .then((response) => {
        if (!response.ok) {
          throw new Error(String(response.status));
        }
        return response.json();
      })
      .then((body: Schema) => {
        if (!cancelled) setSchema(body);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const common = schema?.columns.filter((column) => column.common) ?? [];
  const rest = schema?.columns.filter((column) => !column.common) ?? [];
  const knownValues = Object.entries(schema?.known_values ?? {}).map(
    ([column, values]): [string, string] => [column, values.join(' · ')],
  );

  return (
    <article className="archer-page__body">
      <p className="archer-page__eyebrow">Guide</p>
      <h1 className="archer-page__title">How to use Archer</h1>
      <p className="archer-page__lead">
        Ask a question about the sales data in plain English. Archer writes the
        SQL, runs it, and shows you the answer alongside the query it used.
      </p>

      <section className="archer-page__section">
        <h2 className="archer-page__heading">Asking questions</h2>

        <h3 className="archer-guide__heading">Try a question</h3>
        <ExampleQuestions questions={EXAMPLE_QUESTIONS} disabled={busy} onAsk={onAsk} />

        <h3 className="archer-guide__heading">Follow up</h3>
        <p>
          Archer remembers your last three exchanges, so you can build on an
          answer: <em>"how many deals did the second one do?"</em>,{' '}
          <em>"and for 2024?"</em> or <em>"explain that query"</em>. When it
          restates your question to answer it, it shows you how under{' '}
          <strong>Interpreted as</strong>. Clearing the conversation or
          refreshing the page starts afresh; nothing is saved.
        </p>

        <h3 className="archer-guide__heading">More than one question</h3>
        <p>
          You can ask up to three things at once - <em>"revenue in 2023, and
          what does IBM SOFT mean?"</em> - and each is answered in turn. If a
          question cannot be answered without guessing, Archer asks what you
          meant and offers answers you can click.
        </p>

        <h3 className="archer-guide__heading">What it won't answer</h3>
        <p>
          It answers questions about this data and the answers it has given.
          Anything else - general knowledge, writing, other topics - it will
          politely decline.
        </p>

        <h3 className="archer-guide__heading">Words Archer understands</h3>
        <NameList items={VOCABULARY} />
        <p className="archer-guide__after-list">
          A deal can span several lines, so counting deals is not the same as
          counting lines. Ask for whichever you mean.
        </p>
      </section>

      <section className="archer-page__section">
        <h2 className="archer-page__heading">The data</h2>

        {!schema && !failed && (
          <InlineLoading description="Loading the dataset description..." status="active" />
        )}

        {failed && (
          <InlineNotification
            kind="error"
            lowContrast
            hideCloseButton
            title="Could not load the dataset description"
            subtitle="You can still ask questions."
          />
        )}

        {schema && (
          <>
            <p>
              One table, <code>{schema.table}</code>, with{' '}
              <strong>{schema.row_count.toLocaleString()}</strong> sales lines
              {schema.date_from && schema.date_to && (
                <>
                  {' '}
                  from <strong>{schema.date_from}</strong> to <strong>{schema.date_to}</strong>
                </>
              )}
              . Every company and figure in it is synthetic.
            </p>

            <h3 className="archer-guide__heading">
              What you get by default ({common.length} columns)
            </h3>
            <p>
              When you ask to see sales lines or deals rather than a total or a
              count, each row shows these columns:
            </p>
            <NameList items={describe(common)} />

            <h3 className="archer-guide__heading">Asking for more ({rest.length} columns)</h3>
            <p>
              Name any of these in your question to include it, for example{' '}
              <em>"Show the last 5 deals with their vendor name and contract end date"</em>.
              To see every column at once, ask for all of them, for example{' '}
              <em>"Show the last 3 deals with all columns"</em>.
            </p>
            <Accordion className="archer-guide__more">
              <AccordionItem title={`List the ${rest.length} other columns`}>
                <NameList items={describe(rest)} />
              </AccordionItem>
            </Accordion>

            {knownValues.length > 0 && (
              <>
                <h3 className="archer-guide__heading">Fixed values</h3>
                <p>
                  Some columns only ever hold a few set values. Archer already
                  knows them; the list is here if you want to filter on one.
                </p>
                <Accordion className="archer-guide__more">
                  <AccordionItem title={`List the values for ${knownValues.length} columns`}>
                    <NameList items={knownValues} />
                  </AccordionItem>
                </Accordion>
              </>
            )}
          </>
        )}
      </section>
    </article>
  );
}
