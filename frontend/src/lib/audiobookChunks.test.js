import { expect, it, vi } from 'vitest';
import { playChapterParagraphs } from './audiobook';

function audio(index, count = 3, line = index) {
  return { scope: 'paragraph', sampleRate: 24000,
    chunk: { index, count, line_index: line, content_sha256: 'snapshot' },
    pcm: new ReadableStream({ start(c) { c.enqueue(new Uint8Array([index, 0])); c.close(); } }),
  };
}

it('serially downloads the rest of the chapter while the first paragraph is playing', async () => {
  let secondInput;
  const second = audio(1);
  second.pcm = new ReadableStream({ start(c) { secondInput = c; c.enqueue(new Uint8Array([1, 0])); } });
  const fetchChunk = vi.fn(async index => index === 1 ? second : audio(index));
  const finishes = [];
  const playPcm = vi.fn(() => new Promise(resolve => finishes.push(resolve)));
  const onLine = vi.fn();
  const playing = playChapterParagraphs({ first: audio(0), fetchChunk, playPcm, onLine, signal: new AbortController().signal });
  await vi.waitFor(() => expect(fetchChunk).toHaveBeenCalledTimes(1));
  expect(fetchChunk.mock.calls[0][0]).toBe(1);
  await new Promise(resolve => setTimeout(resolve, 20));
  expect(fetchChunk).toHaveBeenCalledTimes(1);
  secondInput.close();
  await vi.waitFor(() => expect(fetchChunk).toHaveBeenCalledTimes(2));
  expect(playPcm).toHaveBeenCalledTimes(1);
  expect(onLine).toHaveBeenLastCalledWith(0);
  finishes[0]();
  await vi.waitFor(() => expect(playPcm).toHaveBeenCalledTimes(2));
  expect(onLine).toHaveBeenLastCalledWith(1);
  finishes[1]();
  await vi.waitFor(() => expect(playPcm).toHaveBeenCalledTimes(3));
  expect(onLine).toHaveBeenLastCalledWith(2);
  finishes[2]();
  await playing;
  expect(fetchChunk.mock.calls.map(([i]) => i)).toEqual([1, 2]);
});

it('keeps one paragraph highlighted through multiple parts of a very long paragraph', async () => {
  const onLine = vi.fn();
  await playChapterParagraphs({ first: audio(0, 2, 5), fetchChunk: async () => audio(1, 2, 5),
    playPcm: async () => {}, onLine, signal: new AbortController().signal });
  expect(onLine.mock.calls).toEqual([[5], [5]]);
});

it('cancels the active download and playback on stop', async () => {
  const cancel = vi.fn();
  const next = audio(1, 2);
  next.pcm = new ReadableStream({ start(c) { c.enqueue(new Uint8Array([1, 0])); }, cancel });
  const fetchChunk = vi.fn(async () => next);
  const controller = new AbortController();
  const playing = playChapterParagraphs({ first: audio(0, 2), fetchChunk,
    playPcm: () => new Promise(() => {}), onLine: vi.fn(), signal: controller.signal });
  const rejected = expect(playing).rejects.toMatchObject({ name: 'AbortError' });
  await vi.waitFor(() => expect(fetchChunk).toHaveBeenCalledTimes(1));
  controller.abort();
  await rejected;
  await vi.waitFor(() => expect(cancel).toHaveBeenCalled());
});

it('plays earlier cached paragraphs before reporting a later prefetch failure without retrying', async () => {
  const fetchChunk = vi.fn(async index => { if (index === 2) throw new Error('paragraph failed'); return audio(1); });
  const finishes = [];
  const playPcm = vi.fn(() => new Promise(resolve => finishes.push(resolve)));
  const playing = playChapterParagraphs({ first: audio(0), fetchChunk, playPcm, onLine: vi.fn(), signal: new AbortController().signal });
  const rejected = expect(playing).rejects.toThrow('paragraph failed');
  await vi.waitFor(() => expect(fetchChunk).toHaveBeenCalledTimes(2));
  finishes[0]();
  await vi.waitFor(() => expect(playPcm).toHaveBeenCalledTimes(2));
  finishes[1]();
  await rejected;
  expect(fetchChunk).toHaveBeenCalledTimes(2);
});
