import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import NodeDetailDrawer from "./NodeDetailDrawer";

vi.mock("../../lib/audiobookPlayback", () => ({
  fetchAudiobookStart: vi.fn(),
  prepareAudioPlayback: vi.fn(async () => ({ close: vi.fn() })),
  fetchAudiobookLine: vi.fn(async () => ({ pcm: new ReadableStream({ start(c) { c.enqueue(new Uint8Array([1, 0])); c.close(); } }), sampleRate: 16000 })),
  playPcmStream: vi.fn(() => new Promise(() => {})),
}));

import { fetchAudiobookStart, fetchAudiobookLine, playPcmStream } from "../../lib/audiobookPlayback";

describe("chapter audiobook", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fetchAudiobookStart.mockImplementation((options) => fetchAudiobookLine(options));
    localStorage.clear();
  });

  it.each([false, true])("keeps unchanged paragraphs playable during chapter review (appMode=%s)", async (appMode) => {
    const original = "开场旧。\n\n重复段。\n段内第二行。\n\n重复段。\n段内第二行。";
    const content = "开场新。\n增加一行。\n\n重复段。\n段内第二行。\n\n重复段。\n段内第二行。";
    render(<NodeDetailDrawer appMode={appMode} workId="work-1"
      node={{ id: "pending", type: "chapter", label: "章节", content, extra_data: {} }}
      contentDiff={{ original_content: original, hunks: [{ type: "replace", paragraph_index: 1, old_text: "开场旧。", new_text: "开场新。\n增加一行。" }] }}
      onUpdate={vi.fn()} onClose={vi.fn()} />);
    const paragraphs = screen.getAllByRole("button", { name: "编辑段落" });
    expect(paragraphs).toHaveLength(2);
    expect(within(paragraphs[0]).getByRole("button", { name: "播放第4行" })).toBeTruthy();
    const play = within(paragraphs[1]).getByRole("button", { name: "播放第8行" });
    if (appMode) expect(play.className).not.toContain("opacity-0");
    else expect(play.closest(".group")).toBe(paragraphs[1].parentElement);
    fireEvent.click(play);
    await waitFor(() => expect(fetchAudiobookLine).toHaveBeenCalledWith(expect.objectContaining({ nodeId: "pending", lineIndex: 7 })));
    expect(screen.queryByRole("textbox", { name: "编辑段落内容" })).toBeNull();
    expect(document.querySelector('[data-audiobook-line="7"]').getAttribute("data-audiobook-active")).toBe("true");
    expect(screen.getAllByRole("button", { name: "保留修改" }).length).toBeGreaterThan(0);
  });

  it("highlights the spoken line inside a pending diff paragraph", async () => {
    const original = "开场旧。\n\n后面的正文。";
    const content = "开场新。\n增加一行。\n\n后面的正文。";
    render(<NodeDetailDrawer workId="work-1"
      node={{ id: "diff-reading", type: "chapter", label: "章节", content, extra_data: {} }}
      contentDiff={{ original_content: original, hunks: [{ type: "replace", paragraph_index: 1, old_text: "开场旧。", new_text: "开场新。\n增加一行。" }] }}
      onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    const line = await waitFor(() => {
      const active = document.querySelector('[data-audiobook-line="0"]');
      expect(active?.getAttribute("data-audiobook-active")).toBe("true");
      return active;
    });
    expect(line.className).toContain("bg-amber-200/80");
    expect(line.textContent).toContain("开场新。");
    expect(document.querySelector('[data-audiobook-line="1"]').getAttribute("data-audiobook-active")).toBe("false");
  });

  it("keeps line indexes after a pending deleted paragraph", () => {
    render(<NodeDetailDrawer appMode workId="work-1"
      node={{ id: "deleted", type: "chapter", label: "章节", content: "留下的正文。", extra_data: {} }}
      contentDiff={{ grouping: "agent_replacements", original_content: "删除的正文。\n\n留下的正文。", current_content: "留下的正文。",
        hunks: [{ type: "delete", start_offset: 0, old_text: "删除的正文。\n\n", new_text: "" }] }}
      onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: "播放第1行" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "播放第3行" })).toBeNull();
  });

  it("resumes the interrupted line after stopping playback", async () => {
    render(<NodeDetailDrawer workId="work-1" node={{ id: "resume", type: "chapter", label: "章节", content: "第一句。\n第二句。", extra_data: {} }} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "播放第2行" }));
    await waitFor(() => expect(playPcmStream).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "停止" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "播放" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    await waitFor(() => expect(fetchAudiobookStart).toHaveBeenCalledTimes(2));
    expect(fetchAudiobookStart.mock.calls[1][0].lineIndex).toBe(1);
  });

  it("starts from the first line after the chapter finishes", async () => {
    playPcmStream.mockResolvedValueOnce(undefined);
    render(<NodeDetailDrawer workId="work-1" node={{ id: "finished", type: "chapter", label: "章节", content: "第一句。\n第二句。", extra_data: {} }} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "播放第2行" }));
    await waitFor(() => expect(playPcmStream).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("button", { name: "播放" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    await waitFor(() => expect(fetchAudiobookLine).toHaveBeenCalledTimes(3));
    expect(fetchAudiobookLine.mock.calls[1][0].lineIndex).toBe(0);
    expect(fetchAudiobookLine.mock.calls[2][0].lineIndex).toBe(1);
  });

  it("keeps a separate listening position for each chapter", async () => {
    const chapter = (id) => ({ id, type: "chapter", label: id, content: "第一句。\n第二句。", extra_data: {} });
    const props = { workId: "work-1", onClose: vi.fn() };
    const view = render(<NodeDetailDrawer {...props} node={chapter("a")} />);
    fireEvent.click(screen.getByRole("button", { name: "播放第2行" }));
    await waitFor(() => expect(playPcmStream).toHaveBeenCalledTimes(1));
    view.rerender(<NodeDetailDrawer {...props} node={chapter("b")} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "播放" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    await waitFor(() => expect(fetchAudiobookLine).toHaveBeenCalledTimes(3));
    expect(fetchAudiobookLine.mock.calls[1][0]).toMatchObject({ nodeId: "b", lineIndex: 0 });
    expect(fetchAudiobookLine.mock.calls[2][0]).toMatchObject({ nodeId: "b", lineIndex: 1 });
    view.rerender(<NodeDetailDrawer {...props} node={chapter("a")} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "播放" })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    await waitFor(() => expect(fetchAudiobookLine).toHaveBeenCalledTimes(4));
    expect(fetchAudiobookLine.mock.calls[3][0]).toMatchObject({ nodeId: "a", lineIndex: 1 });
    expect(fetchAudiobookLine.mock.calls.slice(0, 3).every(([request]) => request.signal.aborted)).toBe(true);
  });

  it("restores the listening position after closing and reopening the reader", async () => {
    const props = { workId: "work-1", node: { id: "persisted", type: "chapter", label: "章节", content: "第一句。\n第二句。", extra_data: {} }, onClose: vi.fn() };
    const first = render(<NodeDetailDrawer {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "播放第2行" }));
    await waitFor(() => expect(playPcmStream).toHaveBeenCalledTimes(1));
    first.unmount();
    render(<NodeDetailDrawer {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    await waitFor(() => expect(fetchAudiobookStart).toHaveBeenCalledTimes(2));
    expect(fetchAudiobookStart.mock.calls[1][0]).toMatchObject({ nodeId: "persisted", lineIndex: 1 });
  });

  it("starts over when the interrupted line has been edited", async () => {
    const props = { workId: "work-1", onClose: vi.fn() };
    const node = { id: "edited-position", type: "chapter", label: "章节", content: "第一句。\n第二句。", extra_data: {} };
    const first = render(<NodeDetailDrawer {...props} node={node} />);
    fireEvent.click(screen.getByRole("button", { name: "播放第2行" }));
    await waitFor(() => expect(playPcmStream).toHaveBeenCalledTimes(1));
    first.unmount();
    render(<NodeDetailDrawer {...props} node={{ ...node, content: "新开头。\n改写后的第二句。" }} />);
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    await waitFor(() => expect(fetchAudiobookStart).toHaveBeenCalledTimes(2));
    expect(fetchAudiobookStart.mock.calls[1][0].lineIndex).toBe(0);
  });

  it("retains the listening position when audio playback fails", async () => {
    playPcmStream.mockRejectedValueOnce(new Error("音频连接中断"));
    render(<NodeDetailDrawer workId="work-1" node={{ id: "interrupted", type: "chapter", label: "章节", content: "第一句。\n第二句。", extra_data: {} }} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "播放第2行" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toBe("音频连接中断"));
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    await waitFor(() => expect(fetchAudiobookStart).toHaveBeenCalledTimes(2));
    expect(fetchAudiobookStart.mock.calls[1][0].lineIndex).toBe(1);
  });

  it("changes the active audio immediately and carries the rate to the next line", async () => {
    const audio = { playbackRate: 1 };
    let finishLine;
    playPcmStream.mockImplementationOnce((_pcm, _sampleRate, _signal, options) => {
      audio.playbackRate = options.playbackRate;
      options.onAudio(audio);
      return new Promise((resolve) => { finishLine = resolve; });
    });
    render(<NodeDetailDrawer workId="work-1" node={{ id: "chapter-rate", type: "chapter", label: "章节", content: "第一句。\n第二句。", extra_data: {} }} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    await waitFor(() => expect(playPcmStream).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByRole("combobox", { name: "朗读倍速" }), { target: { value: "1.5" } });
    expect(audio.playbackRate).toBe(1.5);
    expect(localStorage.getItem("novel:audiobookRate")).toBe("1.5");
    finishLine();
    await waitFor(() => expect(playPcmStream).toHaveBeenCalledTimes(2));
    expect(playPcmStream.mock.calls[1][3].playbackRate).toBe(1.5);
  });

  it("restores the saved playback rate", () => {
    localStorage.setItem("novel:audiobookRate", "1.75");
    render(<NodeDetailDrawer workId="work-1" node={{ id: "chapter-saved", type: "chapter", label: "章节", content: "正文。", extra_data: {} }} onClose={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "朗读倍速" }).value).toBe("1.75");
  });
  it("highlights the spoken line and requests only speakable lines", async () => {
    render(
      <NodeDetailDrawer
        workId="work-1"
        node={{ id: "chapter-1", type: "chapter", label: "第一章", content: "第一句。\n\n第二句。", extra_data: {} }}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    await waitFor(() => {
      expect(document.querySelector('[data-audiobook-line="0"]')?.getAttribute("data-audiobook-active")).toBe("true");
    });
    expect(fetchAudiobookLine).toHaveBeenCalledWith({
      workId: "work-1",
      nodeId: "chapter-1",
      lineIndex: 0,
      signal: expect.any(AbortSignal),
    });
    expect(screen.getByRole("button", { name: "停止" })).toBeTruthy();
  });

  it("plays from the clicked line and keeps going", async () => {
    render(
      <NodeDetailDrawer
        workId="work-1"
        node={{ id: "chapter-1", type: "chapter", label: "第一章", content: "第一句。\n\n第二句。", extra_data: {} }}
        onClose={vi.fn()}
      />,
    );
    const lineButton = screen.getByRole("button", { name: "播放第3行" });
    expect(lineButton.className).toContain("opacity-0");
    expect(lineButton.className).toContain("group-hover:opacity-100");
    expect(lineButton.closest(".group")).toBeTruthy();
    fireEvent.click(lineButton);
    await waitFor(() => {
      expect(document.querySelector('[data-audiobook-line="2"]')?.getAttribute("data-audiobook-active")).toBe("true");
    });
    expect(fetchAudiobookLine).toHaveBeenCalledWith({
      workId: "work-1",
      nodeId: "chapter-1",
      lineIndex: 2,
      signal: expect.any(AbortSignal),
    });
    expect(screen.queryByRole("button", { name: "播放第2行" })).toBeNull();
  });

  it("keeps line playback buttons visible and usable in app mode", async () => {
    render(<NodeDetailDrawer appMode workId="work-1" node={{ id: "mobile", type: "chapter", label: "章节", content: "第一句。\n第二句。", extra_data: {} }} onClose={vi.fn()} />);
    const lineButton = screen.getByRole("button", { name: "播放第2行" });
    expect(lineButton.className).not.toContain("opacity-0");
    fireEvent.click(lineButton);
    await waitFor(() => expect(fetchAudiobookLine).toHaveBeenCalledWith(expect.objectContaining({ lineIndex: 1 })));
  });

  it("opens and plays the next chapter after the current chapter finishes", async () => {
    const first = { id: "first", type: "chapter", label: "第一章", content: "第一章正文。", extra_data: {} };
    const second = { id: "second", type: "chapter", label: "第二章", content: "第二章正文。", extra_data: {} };
    const navigate = vi.fn();
    playPcmStream.mockResolvedValueOnce(undefined);
    const props = { workId: "work-1", chapterNodes: [first, second], onChapterNavigate: navigate, onClose: vi.fn() };
    const view = render(<NodeDetailDrawer {...props} node={first} />);
    fireEvent.click(screen.getByRole("button", { name: "播放" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith(second));
    view.rerender(<NodeDetailDrawer {...props} node={second} />);
    await waitFor(() => expect(fetchAudiobookLine).toHaveBeenCalledWith(expect.objectContaining({ nodeId: "second", lineIndex: 0 })));
  });
});

it("keeps the actual playing paragraph highlighted until its audio finishes", async () => {
  vi.clearAllMocks();
  fetchAudiobookStart.mockResolvedValueOnce({ scope: "paragraph", sampleRate: 24000,
    chunk: { index: 0, count: 1, line_index: 1, content_sha256: "test" },
    pcm: new ReadableStream({ start(c) { c.enqueue(new Uint8Array([1, 0])); c.close(); } }),
  });
  playPcmStream.mockImplementationOnce(() => new Promise(() => {}));
  render(<NodeDetailDrawer workId="w" node={{ id: "whole", type: "chapter", label: "章", content: "前文。\n第一句。\n第二句。", extra_data: {} }} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "播放第2行" }));
  await waitFor(() => expect(playPcmStream).toHaveBeenCalledTimes(1));
  expect(fetchAudiobookStart).toHaveBeenLastCalledWith(expect.objectContaining({ lineIndex: 1 }));
  expect(document.querySelector('[data-audiobook-line="1"]').getAttribute('data-audiobook-active')).toBe('true');
  expect(fetchAudiobookLine).not.toHaveBeenCalled();
});

it("chapter play resumes an interrupted paragraph", async () => {
  vi.clearAllMocks();
  fetchAudiobookStart.mockImplementation(async () => ({ scope: "paragraph", sampleRate: 24000,
    chunk: { index: 0, count: 1, line_index: 1, content_sha256: "test" },
    pcm: new ReadableStream({ start(c) { c.enqueue(new Uint8Array([1, 0])); c.close(); } }),
  }));
  playPcmStream.mockImplementation(() => new Promise(() => {}));
  render(<NodeDetailDrawer workId="w" node={{ id: "restart", type: "chapter", label: "章", content: "开头。\n中间。\n结尾。", extra_data: {} }} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "播放第2行" }));
  await waitFor(() => expect(playPcmStream).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "停止" }));
  fireEvent.click(screen.getByRole("button", { name: "播放" }));
  await waitFor(() => expect(fetchAudiobookStart).toHaveBeenCalledTimes(2));
  expect(fetchAudiobookStart.mock.calls.map(([request]) => request.lineIndex)).toEqual([1, 1]);
});

it("resumes the playing paragraph instead of a prefetched paragraph after interruption", async () => {
  vi.clearAllMocks();
  localStorage.clear();
  const audio = (index) => ({ scope: "paragraph", sampleRate: 24000,
    chunk: { index, count: 3, line_index: index, content_sha256: "snapshot" },
    pcm: new ReadableStream({ start(c) { c.enqueue(new Uint8Array([1, 0])); c.close(); } }),
  });
  fetchAudiobookStart.mockImplementation(async ({ chunkIndex, lineIndex }) => audio(chunkIndex ?? lineIndex));
  playPcmStream.mockImplementation(() => new Promise(() => {}));
  const props = { workId: "work", node: { id: "prefetched-position", type: "chapter", label: "章", content: "开头。\n正在播放。\n仅预取。", extra_data: {} }, onClose: vi.fn() };
  const first = render(<NodeDetailDrawer {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "播放第2行" }));
  await waitFor(() => expect(fetchAudiobookStart).toHaveBeenCalledTimes(2));
  expect(playPcmStream).toHaveBeenCalledTimes(1);
  first.unmount();
  render(<NodeDetailDrawer {...props} />);
  fireEvent.click(screen.getByRole("button", { name: "播放" }));
  await waitFor(() => expect(fetchAudiobookStart).toHaveBeenCalledTimes(4));
  expect(fetchAudiobookStart.mock.calls[2][0].lineIndex).toBe(1);
  expect(fetchAudiobookStart.mock.calls[2][0]).not.toHaveProperty("chunkIndex");
});

it("prefetches the next paragraph with the same selected start and snapshot", async () => {
  vi.clearAllMocks();
  const audio = (index) => ({ scope: 'paragraph', sampleRate: 24000,
    chunk: { index, count: 2, line_index: index + 1, content_sha256: 'snapshot' },
    pcm: new ReadableStream({ start(c) { c.enqueue(new Uint8Array([1, 0])); c.close(); } }),
  });
  fetchAudiobookStart.mockResolvedValueOnce(audio(0)).mockResolvedValueOnce(audio(1));
  let finish;
  playPcmStream.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  render(<NodeDetailDrawer workId="w" node={{ id: "chunks", type: "chapter", label: "章", content: "前文。\n甲乙丙\n丁戊己\n", extra_data: {} }} onClose={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: '播放第2行' }));
  await waitFor(() => expect(fetchAudiobookStart).toHaveBeenCalledTimes(2));
  expect(fetchAudiobookStart.mock.calls[1][0]).toMatchObject({ lineIndex: 1, chunkIndex: 1, contentSha256: 'snapshot' });
  expect(document.querySelector('[data-audiobook-line="1"]').getAttribute('data-audiobook-active')).toBe('true');
  const { act } = await import('@testing-library/react');
  await act(async () => { finish(); });
  await waitFor(() => expect(document.querySelector('[data-audiobook-line="2"]').getAttribute('data-audiobook-active')).toBe('true'));
  expect(fetchAudiobookStart).toHaveBeenCalledTimes(2);
  expect(fetchAudiobookLine).not.toHaveBeenCalled();
});
