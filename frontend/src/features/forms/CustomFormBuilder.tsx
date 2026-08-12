import type { ChangeEvent } from "react";

import {
  CHOICE_QUESTION_TYPES,
  CUSTOM_QUESTION_TYPES,
  QUESTION_TYPE_LABELS,
  type CustomFormQuestion,
  type CustomFormSchema,
  type CustomQuestionType,
} from "./customFormTypes";

const QUESTION_TONES = [
  "border-accent bg-accent/15",
  "border-secondary bg-secondary/15",
  "border-success bg-success/15",
  "border-warn bg-warn/15",
] as const;

function questionTone(id: string) {
  const total = [...id].reduce((sum, character) => sum + character.codePointAt(0)!, 0);
  return QUESTION_TONES[total % QUESTION_TONES.length];
}

function questionId() {
  return "q_" + crypto.randomUUID().replace(/-/g, "_");
}

function newQuestion(): CustomFormQuestion {
  return { id: questionId(), label: "", type: "short_text", options: [], required: false };
}

export function CustomFormBuilder({ value, onChange, disabled = false }: {
  value: CustomFormSchema;
  onChange: (schema: CustomFormSchema) => void;
  disabled?: boolean;
}) {
  const questions = value ?? [];
  const replace = (index: number, question: CustomFormQuestion) => {
    onChange(questions.map((item, itemIndex) => itemIndex === index ? question : item));
  };
  const move = (index: number, direction: -1 | 1) => {
    const target = index + direction;
    if (target < 0 || target >= questions.length) return;
    const next = [...questions];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  };

  return (
    <fieldset className="grid gap-3" disabled={disabled}>
      <div>
        <legend className="title-panel">Custom questions</legend>
        <p className="eyebrow mt-1">Answers are visible only to authorized staff.</p>
      </div>
      {questions.map((question, index) => (
        <QuestionEditor
          key={question.id}
          question={question}
          index={index}
          count={questions.length}
          onChange={(next) => replace(index, next)}
          onMove={(direction) => move(index, direction)}
          onRemove={() => onChange(questions.filter((item) => item.id !== question.id))}
        />
      ))}
      {!questions.length ? (
        <p className="rounded-lg border border-dashed border-outline bg-surface p-3 text-sm text-muted">
          No custom questions. The standard contact fields will still be collected.
        </p>
      ) : null}
      <button className="desk-button-ghost w-fit" type="button" disabled={questions.length >= 50} onClick={() => onChange([...questions, newQuestion()])}>
        Add question
      </button>
    </fieldset>
  );
}

function QuestionEditor({ question, index, count, onChange, onMove, onRemove }: {
  question: CustomFormQuestion;
  index: number;
  count: number;
  onChange: (question: CustomFormQuestion) => void;
  onMove: (direction: -1 | 1) => void;
  onRemove: () => void;
}) {
  const choice = CHOICE_QUESTION_TYPES.has(question.type);
  const changeType = (event: ChangeEvent<HTMLSelectElement>) => {
    const type = event.target.value as CustomQuestionType;
    if (choice && !CHOICE_QUESTION_TYPES.has(type) && question.options.length > 0) {
      if (!window.confirm("Changing this type will remove its choices. Continue?")) return;
    }
    onChange({
      ...question,
      type,
      options: CHOICE_QUESTION_TYPES.has(type)
        ? (question.options.length ? question.options : [""])
        : [],
    });
  };

  return (
    <div className={`rounded-xl border ${questionTone(question.id)} p-3`}>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="eyebrow">Question <span className="font-mono">{index + 1}</span></span>
        <div className="ml-auto flex gap-2">
          <button className="desk-button-ghost" type="button" disabled={index === 0} onClick={() => onMove(-1)} aria-label={"Move question " + (index + 1) + " up"}>Up</button>
          <button className="desk-button-ghost" type="button" disabled={index === count - 1} onClick={() => onMove(1)} aria-label={"Move question " + (index + 1) + " down"}>Down</button>
          <button className="desk-button-danger" type="button" onClick={onRemove}>Remove</button>
        </div>
      </div>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_180px]">
        <label className="grid gap-1 text-ink"><span className="eyebrow">Label</span>
          <input className="desk-input" required maxLength={200} value={question.label} onChange={(event) => onChange({ ...question, label: event.target.value })} />
        </label>
        <label className="grid gap-1 text-ink"><span className="eyebrow">Answer type</span>
          <select className="desk-input" value={question.type} onChange={changeType}>
            {CUSTOM_QUESTION_TYPES.map((type) => <option key={type} value={type}>{QUESTION_TYPE_LABELS[type]}</option>)}
          </select>
        </label>
      </div>
      <label className="mt-3 flex items-center gap-2 text-sm text-ink">
        <input type="checkbox" checked={question.required} onChange={(event) => onChange({ ...question, required: event.target.checked })} />
        Required question
      </label>
      {choice ? <OptionsEditor question={question} onChange={onChange} /> : null}
    </div>
  );
}

function OptionsEditor({ question, onChange }: {
  question: CustomFormQuestion;
  onChange: (question: CustomFormQuestion) => void;
}) {
  return (
    <div className="mt-3 grid gap-2">
      <h3 className="title-section">Choices</h3>
      {question.options.map((option, index) => (
        <div className="flex gap-2" key={question.id + "-option-" + index}>
          <input className="desk-input min-w-0 flex-1" aria-label={"Choice " + (index + 1)} required maxLength={200} value={option} onChange={(event) => onChange({ ...question, options: question.options.map((item, itemIndex) => itemIndex === index ? event.target.value : item) })} />
          <button className="desk-button-danger" type="button" disabled={question.options.length === 1} onClick={() => onChange({ ...question, options: question.options.filter((_, itemIndex) => itemIndex !== index) })}>Remove</button>
        </div>
      ))}
      <button className="desk-button-ghost w-fit" type="button" disabled={question.options.length >= 50} onClick={() => onChange({ ...question, options: [...question.options, ""] })}>Add choice</button>
    </div>
  );
}
