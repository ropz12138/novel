import React from "react";
import { vi } from "vitest";

vi.mock("@uiw/react-codemirror", () => ({
  default: function MockCodeMirror({ value, onChange, editable }) {
    return React.createElement("textarea", {
      "aria-label": "requirements-codemirror",
      value: value ?? "",
      readOnly: editable === false,
      onChange: (e) => onChange?.(e.target.value),
    });
  },
}));
