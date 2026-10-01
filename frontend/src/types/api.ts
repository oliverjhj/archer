// Shared types describing the contract with the backend ask endpoint.
//
//   request:  { "question": string,        (the backend also accepts string[])
//               "history"?: HistoryTurn[] }   recent exchanges, for follow-ups
//   response: { "answer": string,           Markdown, unchanged for /ask callers
//               "turn": Turn }              the structured record this app renders
//
// The structured turn is the source of truth for rendering. The Markdown answer
// is kept for webhook callers and as a fallback, parsed by lib/answer.ts.

export interface AskRequest {
  question: string;
  /** Recent exchanges for context: each turn's `memory`, sent back unchanged. */
  history?: HistoryTurn[];
}

/** One earlier exchange as carried forward for context. Built by the server. */
export interface HistoryTurn {
  question: string;
  interpreted: string | null;
  sql: string | null;
  columns: string[];
  rows: unknown[][];
  answer: string | null;
}

export type PartStatus =
  | 'ok'
  | 'empty'
  | 'no_sql'
  | 'blocked'
  | 'sql_error'
  | 'unavailable'
  | 'model_error';

/** One answer within a turn: a data result or a piece of text. */
export interface Part {
  type: 'data' | 'chat' | 'decline' | 'clarify';
  question: string;
  status: PartStatus;
  /** The sentence a person reads first. Always present for a finished part. */
  text: string | null;
  sql: string | null;
  columns: string[];
  /** Display strings, already formatted (pounds, thousands separators). */
  rows: string[][];
  row_count: number;
  truncated: boolean;
  /** Set when the result is a single value. */
  value: string | null;
  summary: string | null;
  corrected: boolean;
  /** For a clarifying question: answers the user can send with one click. */
  options: string[];
}

export interface Turn {
  version: number;
  kind: 'data' | 'chat' | 'mixed' | 'decline' | 'clarify' | 'error' | 'budget';
  interpreted_as: string | null;
  parts: Part[];
  /** A note about the whole answer, such as questions left unanswered. */
  notice: string | null;
  memory: HistoryTurn | null;
}

export interface AskResponse {
  answer: string;
  turn?: Turn;
}

export type AskErrorKind =
  | 'network'
  | 'unauthorised'
  | 'rate_limited'
  | 'server'
  | 'empty'
  | 'unknown';

export interface AskError {
  kind: AskErrorKind;
  message: string;
}

/** A single question/answer exchange rendered in the workspace. */
export interface ConversationEntry {
  id: string;
  question: string;
  answer: string | null;
  /** The structured answer, when the backend sent one. */
  turn: Turn | null;
  pending: boolean;
  error: AskError | null;
}
