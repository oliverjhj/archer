import { useEffect, useState } from 'react';
import {
  Accordion,
  AccordionItem,
  InlineLoading,
  InlineNotification,
  Modal,
} from '@carbon/react';
import { apiUrl } from '../api/client';
import { EXAMPLE_QUESTIONS } from '../lib/examples';
import { ExampleQuestions } from './ExampleQuestions';

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

interface GuidePanelProps {
  open: boolean;
  busy: boolean;
  onClose: () => void;
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

function ColumnList({ columns }: { columns: SchemaColumn[] }) {
  return (
    <dl className="archer-guide__columns">
      {columns.map((column) => (
        <div key={column.name}>
          <dt>{column.name}</dt>
          <dd>{column.description}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * How to use Archer: what to ask, what comes back, and what the data holds.
 *
 * Without this, a visitor is guessing at column names, and the questions
 * people invent while guessing are the ones that come back empty. The values
 * section exists for the same reason the prompt has one: someone who has to
 * guess whether a flag is 'Yes' or 'Y' will guess wrong, exactly as the model
 * did before it was told.
 */
export function GuidePanel({ open, busy, onClose, onAsk }: GuidePanelProps) {
  const [schema, setSchema] = useState<Schema | null>(null);
  const [failed, setFailed] = useState(false);

  // Fetched on first open rather than on mount: most visitors ask a question
  // without ever opening this, and there is no reason to spend a request on
  // them.
  useEffect(() => {
    if (!open || schema || failed) {
      return;
    }

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
  }, [open, schema, failed]);

  const common = schema?.columns.filter((column) => column.common) ?? [];
  const rest = schema?.columns.filter((column) => !column.common) ?? [];

  const askAndClose = (question: string) => {
    onAsk(question);
    onClose();
  };

  return (
    <Modal
      open={open}
      onRequestClose={onClose}
      modalHeading="How to use Archer"
      modalLabel="Guide"
      passiveModal
      size="md"
    >
      <div className="archer-guide">
        <p className="archer-guide__intro">
          Ask a question about the sales data in plain English. Archer writes the
          SQL, runs it, and shows you the answer alongside the query it used.
        </p>

        <h4 className="archer-guide__heading">Try a question</h4>
        <ExampleQuestions questions={EXAMPLE_QUESTIONS} disabled={busy} onAsk={askAndClose} />

        <h4 className="archer-guide__heading">Words Archer understands</h4>
        <dl className="archer-guide__columns">
          {VOCABULARY.map(([words, meaning]) => (
            <div key={words}>
              <dt>{words}</dt>
              <dd>{meaning}</dd>
            </div>
          ))}
        </dl>

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
            <h4 className="archer-guide__heading">The data</h4>
            <p className="archer-guide__text">
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

            <h4 className="archer-guide__heading">
              What you get by default ({common.length} columns)
            </h4>
            <p className="archer-guide__text">
              When you ask to see sales lines or deals rather than a total or a
              count, each row shows these columns:
            </p>
            <ColumnList columns={common} />

            <h4 className="archer-guide__heading">Asking for more ({rest.length} columns)</h4>
            <p className="archer-guide__text">
              Name any of these in your question to include it, for example{' '}
              <em>"Show the last 5 deals with their vendor name and contract end date"</em>.
            </p>
            <Accordion className="archer-guide__more">
              <AccordionItem title={`Show all ${rest.length} columns`}>
                <ColumnList columns={rest} />
              </AccordionItem>
            </Accordion>

            {Object.keys(schema.known_values).length > 0 && (
              <>
                <h4 className="archer-guide__heading">Fixed values</h4>
                <p className="archer-guide__text">
                  These columns only ever hold the values listed.
                </p>
                <dl className="archer-guide__columns">
                  {Object.entries(schema.known_values).map(([column, values]) => (
                    <div key={column}>
                      <dt>{column}</dt>
                      <dd>{values.join(' · ')}</dd>
                    </div>
                  ))}
                </dl>
              </>
            )}

            <p className="archer-guide__note">
              A deal can span several lines, so counting deals is not the same as
              counting lines. Ask for whichever you mean.
            </p>
          </>
        )}
      </div>
    </Modal>
  );
}
