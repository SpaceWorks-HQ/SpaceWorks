import type { CustomAnswerSnapshot, CustomAnswerValue } from "./customFormTypes";

const ANSWER_TONES = [
  "border-accent bg-accent/15",
  "border-secondary bg-secondary/15",
  "border-success bg-success/15",
  "border-warn bg-warn/15",
] as const;

function answerTone(id: string) {
  const total = [...id].reduce((sum, character) => sum + character.codePointAt(0)!, 0);
  return ANSWER_TONES[total % ANSWER_TONES.length];
}

function displayValue(value: CustomAnswerValue) {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.join(", ");
  return String(value);
}

export function CustomAnswersView({ snapshot }: { snapshot: CustomAnswerSnapshot | null | undefined }) {
  if (!snapshot?.answers.length) {
    return <p className="text-sm text-muted">No custom answers were submitted.</p>;
  }

  return (
    <dl className="grid gap-3">
      {snapshot.answers.map((answer) => (
        <div key={answer.id} className={`rounded-lg border ${answerTone(answer.id)} p-3`}>
          <dt className="eyebrow">{answer.label}</dt>
          <dd className="mt-1 whitespace-pre-wrap break-words text-sm text-ink">{displayValue(answer.value)}</dd>
        </div>
      ))}
    </dl>
  );
}
