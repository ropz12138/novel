import { beforeEach, expect, it } from "vitest";
import { clearAudiobookPosition, readAudiobookPosition, saveAudiobookPosition } from "./audiobookPosition";

beforeEach(() => localStorage.clear());

it("persists the exact line and separates works and chapters", () => {
  saveAudiobookPosition("work-a", "chapter", 1, "第二行。\n");
  expect(readAudiobookPosition("work-a", "chapter", "第一行。\n第二行。\n第三行。")).toBe(1);
  expect(readAudiobookPosition("work-b", "chapter", "第一行。\n第二行。\n第三行。")).toBe(0);
  expect(readAudiobookPosition("work-a", "other-chapter", "第一行。\n第二行。\n第三行。")).toBe(0);
});

it("invalidates a position when that line is edited or removed", () => {
  saveAudiobookPosition("work", "chapter", 1, "第二行。");
  expect(readAudiobookPosition("work", "chapter", "第一行。\n新的第二行。")).toBe(0);
  expect(readAudiobookPosition("work", "chapter", "第一行。\n第二行。")).toBe(0);
  saveAudiobookPosition("work", "chapter", 2, "第三行。");
  expect(readAudiobookPosition("work", "chapter", "只剩一行。")).toBe(0);
});

it("clears only the completed chapter", () => {
  saveAudiobookPosition("work", "first", 1, "第二行。");
  saveAudiobookPosition("work", "second", 1, "第二行。");
  clearAudiobookPosition("work", "first");
  expect(readAudiobookPosition("work", "first", "第一行。\n第二行。")).toBe(0);
  expect(readAudiobookPosition("work", "second", "第一行。\n第二行。")).toBe(1);
});
