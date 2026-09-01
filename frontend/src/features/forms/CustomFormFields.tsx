import { useId } from "react";

import type { CustomAnswers, CustomFormQuestion, CustomFormSchema } from "./customFormTypes";

export function CustomFormFields({ schema, answers, onChange, errors = {}, disabled = false, yesNoAsCheckbox = false }: {
  schema: CustomFormSchema;
  answers: CustomAnswers;
  onChange: (answers: CustomAnswers) => void;
  errors?: Record<string, string>;
  disabled?: boolean;
  yesNoAsCheckbox?: boolean;
}) {
  const prefix = useId();
  if (!schema?.length) return null;

  const setAnswer = (id: string, value: CustomAnswers[string]) => onChange({ ...answers, [id]: value });
  return (
    <fieldset className="grid gap-4" disabled={disabled}>
      <legend className="title-section mb-1">Additional questions</legend>
      {schema.map((question) => (
        <QuestionField
          key={question.id}
          question={question}
          inputId={prefix + "-" + question.id}
          value={answers[question.id]}
          error={errors[question.id]}
          yesNoAsCheckbox={yesNoAsCheckbox}
          onChange={(value) => setAnswer(question.id, value)}
        />
      ))}
    </fieldset>
  );
}

function QuestionField({ question, inputId, value, error, yesNoAsCheckbox, onChange }: {
  question: CustomFormQuestion;
  inputId: string;
  value: CustomAnswers[string];
  error?: string;
  yesNoAsCheckbox: boolean;
  onChange: (value: CustomAnswers[string]) => void;
}) {
  const errorId = inputId + "-error";
  const inputProps = {
    id: inputId,
    required: question.required,
    "aria-invalid": Boolean(error),
    "aria-describedby": error ? errorId : undefined,
  };
  const label = <span className="eyebrow">{question.label}{question.required ? <span className="text-danger"> *</span> : null}</span>;
  const message = error ? <span id={errorId} className="text-xs font-normal text-danger">{error}</span> : null;

  if (question.type === "yes_no" && yesNoAsCheckbox) {
    return <label className="grid gap-1 text-ink"><span className="flex items-center gap-2 text-sm"><input id={inputId} type="checkbox" checked={value === true} required={question.required} aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined} onChange={(event) => onChange(event.target.checked)} />{label}</span>{message}</label>;
  }

  if (question.type === "paragraph") {
    return <label className="grid gap-1 text-ink">{label}<textarea {...inputProps} className="desk-input min-h-24" maxLength={5000} value={typeof value === "string" ? value : ""} onChange={(event) => onChange(event.target.value)} />{message}</label>;
  }
  if (question.type === "dropdown") {
    return <label className="grid gap-1 text-ink">{label}<select {...inputProps} className="desk-input" value={typeof value === "string" ? value : ""} onChange={(event) => onChange(event.target.value)}><option value="">Select an option</option>{question.options.map((option) => <option key={option} value={option}>{option}</option>)}</select>{message}</label>;
  }
  if (question.type === "single_choice" || question.type === "yes_no") {
    const choices: [string, string | boolean][] = question.type === "yes_no"
      ? [["Yes", true], ["No", false]]
      : question.options.map((option) => [option, option]);
    return (
      <fieldset className="grid gap-2" aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined}>
        <legend>{label}</legend>
        <div className="flex flex-wrap gap-4">
          {choices.map(([text, answer]) => <label className="flex items-center gap-2 text-sm text-ink" key={text}><input type="radio" name={inputId} value={text} checked={value === answer} required={question.required} onChange={() => onChange(answer)} />{text}</label>)}
        </div>
        {message}
      </fieldset>
    );
  }
  if (question.type === "multi_choice") {
    const selected = Array.isArray(value) ? value : [];
    return (
      <fieldset className="grid gap-2" aria-invalid={Boolean(error)} aria-describedby={error ? errorId : undefined}>
        <legend>{label}</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {question.options.map((option) => <label className="flex items-center gap-2 text-sm text-ink" key={option}><input type="checkbox" checked={selected.includes(option)} onChange={(event) => onChange(event.target.checked ? [...selected, option] : selected.filter((item) => item !== option))} />{option}</label>)}
        </div>
        {message}
      </fieldset>
    );
  }
  const type = question.type === "number" ? "number" : question.type === "date" ? "date" : "text";
  return <label className="grid gap-1 text-ink">{label}<input {...inputProps} className="desk-input" type={type} maxLength={question.type === "short_text" ? 500 : undefined} value={typeof value === "string" || typeof value === "number" ? value : ""} onChange={(event) => onChange(event.target.value)} />{message}</label>;
}
