interface ExampleQuestionsProps {
  questions: string[];
  disabled: boolean;
  onAsk: (question: string) => void;
}

// Example questions as buttons that ask them. Reading an example and retyping
// it is a step most visitors will not take; one click gets them to an answer.
export function ExampleQuestions({ questions, disabled, onAsk }: ExampleQuestionsProps) {
  return (
    <ul className="archer-examples">
      {questions.map((question) => (
        <li key={question}>
          <button
            type="button"
            className="archer-examples__button"
            disabled={disabled}
            onClick={() => onAsk(question)}
          >
            {question}
          </button>
        </li>
      ))}
    </ul>
  );
}
