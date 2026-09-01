import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CustomFormBuilder } from "./CustomFormBuilder";
import { CustomFormFields } from "./CustomFormFields";
import type { CustomFormQuestion } from "./customFormTypes";

const answered: CustomFormQuestion = {
  id: "answered",
  label: "Would you return?",
  type: "yes_no",
  options: [],
  required: true,
};

describe("feedback form controls", () => {
  it("locks answered question content and excludes unsupported date questions", () => {
    render(<CustomFormBuilder
      value={[answered]}
      onChange={vi.fn()}
      allowedTypes={["short_text", "yes_no", "number"]}
      lockedQuestionIds={["answered"]}
      legend="Feedback questions"
    />);

    expect(screen.getByDisplayValue("Would you return?")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove" })).toBeDisabled();
    expect(screen.queryByRole("option", { name: "Date" })).toBeNull();
  });

  it("renders yes/no as a single checkbox on the feedback surface", () => {
    const onChange = vi.fn();
    render(<CustomFormFields
      schema={[answered]}
      answers={{}}
      onChange={onChange}
      yesNoAsCheckbox
    />);

    fireEvent.click(screen.getByRole("checkbox", { name: /Would you return/ }));
    expect(onChange).toHaveBeenCalledWith({ answered: true });
  });
});
