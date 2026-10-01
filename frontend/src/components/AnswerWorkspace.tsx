import { useEffect, useRef } from 'react';
import { EXAMPLE_QUESTIONS } from '../lib/examples';
import type { ConversationEntry } from '../types/api';
import { AnswerItem } from './AnswerItem';
import { ExampleQuestions } from './ExampleQuestions';

interface AnswerWorkspaceProps {
  entries: ConversationEntry[];
  busy: boolean;
  onAsk: (question: string) => void;
}

// Scrollable list of question/answer exchanges, with an empty state.
export function AnswerWorkspace({ entries, busy, onAsk }: AnswerWorkspaceProps) {
  const endRef = useRef<HTMLDivElement>(null);

  // Keep the newest exchange in view. An answer is often taller than the
  // panel - a results table plus the generated SQL usually is - so without
  // this the user is left looking at the top of their own question while the
  // answer sits below the fold.
  //
  // Keyed on length and on the pending flags rather than on `entries`: the
  // answer arriving is a change of content, not of list length, and that is
  // the moment the view most needs to move.
  const signature = entries.map((entry) => `${entry.id}:${entry.pending}`).join(',');

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [signature]);

  if (entries.length === 0) {
    return (
      <section
        className="archer-answers archer-answers--empty"
        aria-live="polite"
      >
        <div className="archer-empty">
          <h2 className="archer-empty__title">Ask Archer a question</h2>
          <p className="archer-empty__body">
            Enter a natural-language question below to explore the dataset.
            Answers appear here alongside the SQL that produced them, and you
            can ask follow-up questions about them.
          </p>
          <ExampleQuestions
            questions={EXAMPLE_QUESTIONS.slice(0, 3)}
            disabled={busy}
            onAsk={onAsk}
          />
          {/*
            Said up front rather than left to be discovered. The deployment
            runs at minimum scale zero, so the first question after a quiet
            period waits for a container to start. Unexplained, that reads as
            a broken demo; explained, it reads as a deliberate cost decision -
            which is what it is.
          */}
          <p className="archer-empty__note">
            This demo runs on synthetic data and scales to zero when idle, so
            the first question may take a few seconds.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="archer-answers" aria-live="polite">
      {entries.map((entry) => (
        <AnswerItem key={entry.id} entry={entry} busy={busy} onAsk={onAsk} />
      ))}
      {/* Scroll anchor for keeping the newest exchange in view. */}
      <div ref={endRef} aria-hidden="true" />
    </section>
  );
}
