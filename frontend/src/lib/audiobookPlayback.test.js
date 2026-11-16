import { afterEach, expect, it, vi } from "vitest";
import { fetchAudiobookStart, fetchAudiobookLine, prepareAudioPlayback } from "./audiobookPlayback";

vi.mock("./authFetch", () => ({ authFetch: vi.fn() }));
import { authFetch } from "./authFetch";

afterEach(() => { vi.unstubAllGlobals(); vi.clearAllMocks(); });

it("resumes the audio context immediately during the play gesture", async () => {
  const context = { resume: vi.fn().mockResolvedValue(), close: vi.fn() };
  vi.stubGlobal("AudioContext", vi.fn(function () { return context; }));
  const ready = prepareAudioPlayback();
  expect(context.resume).toHaveBeenCalledTimes(1);
  expect(await ready).toBe(context);
});

it.each([16000, 24000])("fetches PCM at %i Hz", async (sampleRate) => {
  authFetch.mockResolvedValue(new Response(new Uint8Array([1, 0]), {
    headers: { "X-Audio-Sample-Rate": String(sampleRate) },
  }));
  const audio = await fetchAudiobookLine({ workId: "w", nodeId: "n", lineIndex: 0 });
  expect(audio.sampleRate).toBe(sampleRate);
  expect(audio.pcm).toBeInstanceOf(ReadableStream);
  expect(Array.from((await audio.pcm.getReader().read()).value)).toEqual([1, 0]);
});

it("rejects an unsupported audio sample rate", async () => {
  authFetch.mockResolvedValue(new Response(new Uint8Array([1, 0]), {
    headers: { "X-Audio-Sample-Rate": "0" },
  }));
  await expect(fetchAudiobookLine({ workId: "w", nodeId: "n", lineIndex: 0 })).rejects.toThrow();
});

it("starts chapter-aware playback without consuming the audio response", async () => {
  authFetch.mockResolvedValue(new Response(new Uint8Array([1, 0]), {
    headers: { "X-Audio-Sample-Rate": "24000", "X-Audio-Scope": "paragraph" },
  }));
  const controller = new AbortController();
  const audio = await fetchAudiobookStart({ workId: "w", nodeId: "n", lineIndex: 3, signal: controller.signal });
  expect(authFetch).toHaveBeenCalledWith(expect.stringContaining("/works/w/nodes/n/audiobook"), {
    method: "POST", body: JSON.stringify({ line_index: 3 }), signal: controller.signal,
  });
  expect(audio.scope).toBe("paragraph");
  expect(audio.pcm.locked).toBe(false);
});

it("passes block index and chapter version and reads block timing metadata", async () => {
  const chunk = { index: 1, count: 3, start: 1800, end: 3700, content_sha256: 'snapshot' };
  authFetch.mockResolvedValue(new Response(new Uint8Array([1, 0]), {
    headers: { 'X-Audio-Sample-Rate': '24000', 'X-Audio-Scope': 'paragraph', 'X-Audio-Chunk': JSON.stringify(chunk) },
  }));
  const audio = await fetchAudiobookStart({ workId: 'w', nodeId: 'n', lineIndex: 5, chunkIndex: 1, contentSha256: 'snapshot' });
  expect(JSON.parse(authFetch.mock.calls[0][1].body)).toEqual({ line_index: 5, chunk_index: 1, content_sha256: 'snapshot' });
  expect(audio.chunk).toEqual(chunk);
});
