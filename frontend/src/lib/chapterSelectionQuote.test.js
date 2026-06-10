import { describe, expect, it } from "vitest";
import {
  applyChapterSelectionToChatInput,
  formatChapterSelectionQuote,
  getLineNumberAtPosition,
  getSelectionLineRange,
} from "./chapterSelectionQuote";

describe("getLineNumberAtPosition", () => {
  it("returns 1 at start", () => {
    expect(getLineNumberAtPosition("a\nb", 0)).toBe(1);
  });

  it("returns 2 after first newline", () => {
    expect(getLineNumberAtPosition("a\nb", 2)).toBe(2);
  });
});

describe("getSelectionLineRange", () => {
  it("returns null when nothing selected", () => {
    const textarea = {
      value: "第一行\n第二行\n第三行",
      selectionStart: 4,
      selectionEnd: 4,
    };
    expect(getSelectionLineRange(textarea)).toBeNull();
  });

  it("returns line range for single-line selection", () => {
    const textarea = {
      value: "第一行\n第二行\n第三行",
      selectionStart: 4,
      selectionEnd: 7,
    };
    expect(getSelectionLineRange(textarea)).toEqual({
      startLine: 2,
      endLine: 2,
      text: "第二行",
    });
  });

  it("returns line range spanning multiple lines", () => {
    const textarea = {
      value: "第一行\n第二行\n第三行",
      selectionStart: 0,
      selectionEnd: 10,
    };
    expect(getSelectionLineRange(textarea)).toEqual({
      startLine: 1,
      endLine: 3,
      text: "第一行\n第二行\n第三",
    });
  });
});

describe("formatChapterSelectionQuote", () => {
  it("formats quote with fenced block", () => {
    expect(
      formatChapterSelectionQuote({
        chapterNumber: 1,
        startLine: 3,
        endLine: 5,
        text: "选中内容",
      })
    ).toBe("第1章的3行到5行，\n```选中内容```");
  });
});

describe("applyChapterSelectionToChatInput", () => {
  it("appends formatted quote and focuses input", () => {
    const textarea = {
      value: "第一行\n第二行",
      selectionStart: 4,
      selectionEnd: 7,
    };
    const appended = [];
    let focused = false;

    const ok = applyChapterSelectionToChatInput({
      textarea,
      chapterNumber: 2,
      appendToInput: (text) => appended.push(text),
      focusInput: () => {
        focused = true;
      },
    });

    expect(ok).toBe(true);
    expect(appended).toEqual(["第2章的2行到2行，\n```第二行```"]);
    expect(focused).toBe(true);
  });

  it("returns false without selection", () => {
    const textarea = {
      value: "第一行",
      selectionStart: 0,
      selectionEnd: 0,
    };
    expect(
      applyChapterSelectionToChatInput({
        textarea,
        chapterNumber: 1,
        appendToInput: () => {},
      })
    ).toBe(false);
  });
});
