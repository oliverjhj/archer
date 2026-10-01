import { useCallback, useEffect, useRef, useState } from 'react';
import { ask } from '../api/ask';
import { ApiError } from '../api/client';
import type { AskError, ConversationEntry, HistoryTurn } from '../types/api';

/**
 * How many earlier exchanges go with each question. The server trims to the
 * same number; sending more would only be thrown away.
 */
const HISTORY_TURNS = 3;

/**
 * Turn any thrown value into a message the user can act on.
 *
 * Unrecognised failures deliberately get a generic message rather than the raw
 * error text: model and server internals are not useful to a user and can leak
 * detail that does not belong on screen.
 */
function toAskError(cause: unknown): AskError {
  if (cause instanceof ApiError) {
    return { kind: cause.kind, message: cause.message };
  }
  return {
    kind: 'unknown',
    message: 'Something went wrong while answering that question.',
  };
}

export interface UseAskResult {
  entries: ConversationEntry[];
  busy: boolean;
  submit: (question: string) => void;
  clear: () => void;
}

export function useAsk(): UseAskResult {
  const [entries, setEntries] = useState<ConversationEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const counter = useRef(0);
  const controllers = useRef(new Set<AbortController>());

  // submit() is created once, so it reads the conversation through a ref
  // rather than a stale closure over the first render's entries.
  const entriesRef = useRef<ConversationEntry[]>([]);
  useEffect(() => {
    entriesRef.current = entries;
  }, [entries]);

  // Abort any request still in flight when the component unmounts, so a
  // resolved promise cannot set state on an unmounted component.
  useEffect(() => {
    const inFlight = controllers.current;
    return () => {
      inFlight.forEach((controller) => controller.abort());
      inFlight.clear();
    };
  }, []);

  const submit = useCallback((question: string) => {
    const trimmed = question.trim();
    if (!trimmed) {
      return;
    }

    // The context for this question: what the server said each recent
    // exchange should contribute, sent back as it was received. Failed
    // exchanges add nothing worth following up on, so they are left out.
    const history: HistoryTurn[] = entriesRef.current
      .filter((entry) => !entry.pending && !entry.error && entry.turn?.memory)
      .filter((entry) => entry.turn?.kind !== 'error' && entry.turn?.kind !== 'budget')
      .map((entry) => entry.turn!.memory!)
      .slice(-HISTORY_TURNS);

    counter.current += 1;
    const id = `turn-${counter.current}`;

    setEntries((prev) => [
      ...prev,
      { id, question: trimmed, answer: null, turn: null, pending: true, error: null },
    ]);
    setBusy(true);

    const controller = new AbortController();
    controllers.current.add(controller);

    const settle = (patch: Partial<ConversationEntry>) => {
      setEntries((prev) =>
        prev.map((entry) =>
          entry.id === id ? { ...entry, pending: false, ...patch } : entry,
        ),
      );
    };

    void ask({ question: trimmed, history }, { signal: controller.signal })
      .then((response) => {
        const answer = response?.answer ?? '';
        const turn = response?.turn ?? null;
        // An empty answer is a distinct outcome from a failed one, and the UI
        // says so rather than showing a blank bubble.
        settle(
          answer.trim().length > 0 || (turn && turn.parts.length > 0)
            ? { answer, turn }
            : { answer: null, error: { kind: 'empty', message: 'No answer was returned.' } },
        );
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === 'AbortError') {
          return;
        }
        settle({ answer: null, error: toAskError(cause) });
      })
      .finally(() => {
        controllers.current.delete(controller);
        setBusy(controllers.current.size > 0);
      });
  }, []);

  // Empty the conversation, and with it the context sent with the next
  // question. Questions still in flight are aborted first, so a late answer
  // cannot reappear in a conversation the user has just cleared. Purely
  // client-side: the conversation lives only here, so the server holds
  // nothing to reset.
  const clear = useCallback(() => {
    controllers.current.forEach((controller) => controller.abort());
    controllers.current.clear();
    setEntries([]);
    setBusy(false);
  }, []);

  return { entries, busy, submit, clear };
}
