import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import TtsConfigDialog from "./TtsConfigDialog";
import { getTtsSettings, putTtsSettings } from "../lib/ttsApi";

vi.mock("../lib/ttsApi", () => ({ getTtsSettings: vi.fn(), putTtsSettings: vi.fn() }));

beforeEach(() => {
  vi.clearAllMocks();
  getTtsSettings.mockResolvedValue({ mimo_tts: { style: "原风格" }, mimo_voicedesign: { voice_description: "原音色" } });
  putTtsSettings.mockResolvedValue({});
});

it("does not fetch settings while closed", () => {
  const { container } = render(<TtsConfigDialog open={false} onClose={vi.fn()} />);
  expect(container.innerHTML).toBe("");
  expect(getTtsSettings).not.toHaveBeenCalled();
});

it("loads both prompts and saves the full edited strings", async () => {
  const onClose = vi.fn();
  render(<TtsConfigDialog open onClose={onClose} />);
  const style = await screen.findByLabelText("普通 TTS 朗读风格");
  const description = screen.getByLabelText("VoiceDesign 音色描述");
  expect(style.value).toBe("原风格");
  expect(description.value).toBe("原音色");
  const fullStyle = "  温柔自然。\n".repeat(3000);
  const fullDescription = "清澈女声。\n".repeat(3000);
  fireEvent.change(style, { target: { value: fullStyle } });
  fireEvent.change(description, { target: { value: fullDescription } });
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(putTtsSettings).toHaveBeenCalledWith({
    mimo_tts: { style: fullStyle }, mimo_voicedesign: { voice_description: fullDescription },
  }));
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("shows a loading failure and prevents saving stale fields", async () => {
  getTtsSettings.mockRejectedValue(new Error("仅管理员可访问"));
  render(<TtsConfigDialog open onClose={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "仅管理员可访问");
  expect(screen.getByRole("button", { name: "保存" }).disabled).toBe(true);
});

it("keeps edited fields open when saving fails", async () => {
  putTtsSettings.mockRejectedValue(new Error("保存失败"));
  const onClose = vi.fn();
  render(<TtsConfigDialog open onClose={onClose} />);
  const style = await screen.findByLabelText("普通 TTS 朗读风格");
  fireEvent.change(style, { target: { value: "修改后的风格" } });
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", "保存失败");
  expect(style.value).toBe("修改后的风格");
  expect(onClose).not.toHaveBeenCalled();
});

it("requires a nonblank voice description and does not save on cancel", async () => {
  const onClose = vi.fn();
  render(<TtsConfigDialog open onClose={onClose} />);
  const description = await screen.findByLabelText("VoiceDesign 音色描述");
  fireEvent.change(description, { target: { value: " \n " } });
  expect(screen.getByRole("button", { name: "保存" }).disabled).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(putTtsSettings).not.toHaveBeenCalled();
  expect(onClose).toHaveBeenCalledTimes(1);
});
