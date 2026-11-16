import { describe, expect, it, vi } from "vitest";
import {
  lineIsSpeakable,
  lineSpeechText,
  paragraphAudiobookLines,
  playChapterLines,
  splitAudiobookLines,
} from "./audiobook";

describe("audiobook lines", () => {
  it("splits on newlines and skips blank lines when playing", async () => {
    const text = "第一句。\n\n第二句。";
    const lines = splitAudiobookLines(text);
    expect(lines).toEqual(["第一句。\n", "\n", "第二句。"]);
    expect(lines.join("")).toBe(text);
    expect(lineIsSpeakable(lineSpeechText("……"))).toBe(false);
    expect(lineSpeechText("开场。[[PLOT]]重点[[/PLOT]]后续。")).toBe("开场。重点后续。");

    const spoken = [];
    const active = [];
    await playChapterLines({
      lines,
      fetchLine: async (index) => {
        spoken.push(index);
        return { pcm: new ReadableStream({ start(c) { c.enqueue(new Uint8Array([1, 0])); c.close(); } }), sampleRate: 16000 };
      },
      playPcm: async () => {},
      onLine: (index) => active.push(index),
    });
    expect(spoken).toEqual([0, 2]);
    expect(active).toEqual([0, 2]);
  });

  it("starts at the clicked line and continues through later lines", async () => {
    const lines = splitAudiobookLines("第一句。\n\n第二句。\n\n第三句。");
    expect(paragraphAudiobookLines("第一句。\n\n第二句。\n\n第三句。").map((group) => group.map((line) => line.index))).toEqual([[0], [2], [4]]);
    const spoken = [];
    await playChapterLines({
      lines,
      startIndex: 2,
      fetchLine: async (index) => {
        spoken.push(index);
        return { pcm: new ReadableStream({ start(c) { c.enqueue(new Uint8Array([1, 0])); c.close(); } }), sampleRate: 16000 };
      },
      playPcm: async () => {},
      onLine: () => {},
    });
    expect(spoken).toEqual([2, 4]);
  });
});


function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function audioStream(value = 1) {
  return { pcm: new ReadableStream({ start(c) { c.enqueue(new Uint8Array([value, 0])); c.close(); } }), sampleRate: 24000 };
}

it("prefetches exactly one speakable line, retaining it in memory until playback advances", async () => {
  const gates = [deferred(), deferred(), deferred()];
  const fetched = [];
  const played = [];
  const active = [];
  let bufferedReads = 0;
  const playing = playChapterLines({
    lines: splitAudiobookLines("第一行。\n\n第二行。\n第三行。"),
    fetchLine: async (index) => {
      fetched.push(index);
      if (index === 2) return { pcm: new ReadableStream({
        pull(c) { bufferedReads += 1; c.enqueue(new Uint8Array([2, 0])); c.close(); },
      }, { highWaterMark: 0 }), sampleRate: 24000 };
      return audioStream(index + 1);
    },
    playPcm: async (stream) => {
      const reader = stream.getReader();
      const chunk = (await reader.read()).value;
      played.push(Array.from(chunk));
      while (!(await reader.read()).done) {}
      reader.releaseLock();
      await gates[played.length - 1].promise;
    },
    onLine: (index) => active.push(index),
  });
  await vi.waitFor(() => expect(fetched).toEqual([0, 2]));
  await vi.waitFor(() => expect(bufferedReads).toBe(1));
  expect(active).toEqual([0]);
  expect(played).toEqual([[1, 0]]);
  gates[0].resolve();
  await vi.waitFor(() => expect(fetched).toEqual([0, 2, 3]));
  expect(active).toEqual([0, 2]);
  expect(played).toEqual([[1, 0], [2, 0]]);
  gates[1].resolve();
  await vi.waitFor(() => expect(active).toEqual([0, 2, 3]));
  gates[2].resolve();
  await playing;
  expect(fetched).toEqual([0, 2, 3]);
});

it("cancels the pending request and releases its buffered stream when stopped", async () => {
  const controller = new AbortController();
  const requests = [];
  const cancelled = vi.fn();
  const playing = playChapterLines({
    lines: ["第一行", "第二行", "第三行"], signal: controller.signal,
    fetchLine: async (index, { signal }) => {
      requests.push({ index, signal });
      return index === 0 ? audioStream() : {
        pcm: new ReadableStream({ start(c) { c.enqueue(new Uint8Array([2, 0])); }, cancel: cancelled }), sampleRate: 24000,
      };
    },
    playPcm: () => new Promise(() => {}), onLine: () => {},
  });
  const rejected = expect(playing).rejects.toMatchObject({ name: "AbortError" });
  await vi.waitFor(() => expect(requests).toHaveLength(2));
  controller.abort();
  await rejected;
  expect(requests.every(({ signal }) => signal.aborted)).toBe(true);
  expect(cancelled).toHaveBeenCalledTimes(1);
});

it("lets the current line finish before reporting a failed prefetch without retrying it", async () => {
  const gate = deferred();
  const played = vi.fn(() => gate.promise);
  const fetched = [];
  const playing = playChapterLines({
    lines: ["第一行", "第二行", "第三行"],
    fetchLine: async (index) => { fetched.push(index); if (index === 1) throw new Error("预取失败"); return audioStream(); },
    playPcm: played, onLine: () => {},
  });
  const rejected = expect(playing).rejects.toThrow("预取失败");
  await vi.waitFor(() => expect(fetched).toEqual([0, 1]));
  expect(played).toHaveBeenCalledTimes(1);
  gate.resolve();
  await rejected;
  expect(fetched).toEqual([0, 1]);
});

it("discards a late prefetch response after stop and releases the upstream reader", async () => {
  const controller = new AbortController();
  const response = deferred();
  const cancelled = vi.fn();
  const source = new ReadableStream({ cancel: cancelled });
  const fetchLine = vi.fn(async (index) => index === 0 ? audioStream() : response.promise);
  const playing = playChapterLines({
    lines: ["第一行", "第二行", "第三行"], signal: controller.signal,
    fetchLine, playPcm: () => new Promise(() => {}), onLine: () => {},
  });
  const rejected = expect(playing).rejects.toMatchObject({ name: "AbortError" });
  await vi.waitFor(() => expect(fetchLine).toHaveBeenCalledTimes(2));
  controller.abort();
  await rejected;
  response.resolve({ pcm: source, sampleRate: 24000 });
  await vi.waitFor(() => expect(cancelled).toHaveBeenCalledTimes(1));
  expect(source.locked).toBe(false);
  expect(fetchLine).toHaveBeenCalledTimes(2);
});

it("keeps current audio playing when the prefetched response fails midway", async () => {
  const gate = deferred();
  let upstream;
  const active = [];
  const playing = playChapterLines({
    lines: ["第一行", "第二行", "第三行"],
    fetchLine: async (index) => index === 0 ? audioStream() : {
      pcm: new ReadableStream({ start(c) { upstream = c; c.enqueue(new Uint8Array([2, 0])); } }), sampleRate: 24000,
    },
    playPcm: async (stream) => {
      const reader = stream.getReader();
      while (!(await reader.read()).done) {}
      reader.releaseLock();
      await gate.promise;
    },
    onLine: (index) => active.push(index),
  });
  const rejected = expect(playing).rejects.toThrow("音频下载失败");
  await vi.waitFor(() => expect(upstream).toBeDefined());
  upstream.error(new Error("音频下载失败"));
  expect(active).toEqual([0]);
  gate.resolve();
  await rejected;
});

it("pauses exactly 500 ms when the next line already has playable PCM, without requesting a third line during the pause", async () => {
  vi.useFakeTimers();
  try {
    const gate = deferred();
    const secondGate = deferred();
    const fetchLine = vi.fn(async () => audioStream());
    const playPcm = vi.fn().mockImplementationOnce(() => gate.promise).mockImplementationOnce(() => secondGate.promise).mockResolvedValue(undefined);
    const active = [];
    const playing = playChapterLines({ lines: ["第一行", "第二行", "第三行"], fetchLine, playPcm, onLine: (index) => active.push(index) });
    await vi.advanceTimersByTimeAsync(0);
    expect(playPcm).toHaveBeenCalledTimes(1);
    expect(fetchLine).toHaveBeenCalledTimes(2);
    gate.resolve();
    await vi.advanceTimersByTimeAsync(499);
    expect(playPcm).toHaveBeenCalledTimes(1);
    expect(active).toEqual([0]);
    expect(fetchLine).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(playPcm).toHaveBeenCalledTimes(2);
    secondGate.resolve();
    await vi.advanceTimersByTimeAsync(500);
    await playing;
    expect(active).toEqual([0, 1, 2]);
  } finally { vi.useRealTimers(); }
});

it("adds no pause if the next response arrives only after the current line ends", async () => {
  vi.useFakeTimers();
  try {
    const gate = deferred();
    const response = deferred();
    const playPcm = vi.fn().mockImplementationOnce(() => gate.promise).mockResolvedValue(undefined);
    const playing = playChapterLines({ lines: ["第一行", "第二行"],
      fetchLine: async (index) => index === 0 ? audioStream() : response.promise,
      playPcm, onLine: () => {},
    });
    await vi.advanceTimersByTimeAsync(0);
    gate.resolve();
    await vi.advanceTimersByTimeAsync(0);
    expect(playPcm).toHaveBeenCalledTimes(1);
    response.resolve(audioStream());
    await vi.advanceTimersByTimeAsync(0);
    await playing;
    expect(playPcm).toHaveBeenCalledTimes(2);
  } finally { vi.useRealTimers(); }
});

it("does not treat a response header or half of a PCM sample as ready audio", async () => {
  vi.useFakeTimers();
  try {
    const gate = deferred();
    const playPcm = vi.fn().mockImplementationOnce(() => gate.promise).mockResolvedValue(undefined);
    const playing = playChapterLines({ lines: ["第一行", "第二行"],
      fetchLine: async (index) => index === 0 ? audioStream() : {
        pcm: new ReadableStream({ start(c) { c.enqueue(new Uint8Array([1])); } }), sampleRate: 24000,
      }, playPcm, onLine: () => {},
    });
    await vi.advanceTimersByTimeAsync(0);
    gate.resolve();
    await vi.advanceTimersByTimeAsync(0);
    await playing;
    expect(playPcm).toHaveBeenCalledTimes(2);
  } finally { vi.useRealTimers(); }
});

it("cancels the inter-line pause immediately when stopped", async () => {
  vi.useFakeTimers();
  try {
    const gate = deferred();
    const controller = new AbortController();
    const playPcm = vi.fn(() => gate.promise);
    const playing = playChapterLines({ lines: ["第一行", "第二行"], signal: controller.signal,
      fetchLine: async () => audioStream(), playPcm, onLine: () => {},
    });
    const rejected = expect(playing).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(0);
    gate.resolve();
    await vi.advanceTimersByTimeAsync(200);
    controller.abort();
    await rejected;
    expect(playPcm).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  } finally { vi.useRealTimers(); }
});
