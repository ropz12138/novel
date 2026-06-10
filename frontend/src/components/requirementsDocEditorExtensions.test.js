import { describe, expect, it } from "vitest";
import {
  REQUIREMENTS_DOC_PLACEHOLDER,
  buildRequirementsDocExtensions,
} from "./requirementsDocEditorExtensions";

describe("buildRequirementsDocExtensions", () => {
  it("returns a non-empty CodeMirror extension array", () => {
    const extensions = buildRequirementsDocExtensions();
    expect(Array.isArray(extensions)).toBe(true);
    expect(extensions.length).toBeGreaterThan(0);
  });
});

describe("REQUIREMENTS_DOC_PLACEHOLDER", () => {
  it("documents narrative constraints for authors", () => {
    expect(REQUIREMENTS_DOC_PLACEHOLDER).toContain("叙事视角");
    expect(REQUIREMENTS_DOC_PLACEHOLDER).toContain("风格");
  });
});
