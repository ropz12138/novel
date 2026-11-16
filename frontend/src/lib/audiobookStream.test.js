import { expect, it, vi } from "vitest";
import { playPcmStream } from "./audiobookPlayback";

function context() {
  const sources = [];
  const buffers = [];
  return {
    currentTime: 0, destination: {}, sources, buffers,
    createBuffer: vi.fn((_channels, frames, rate) => {
      const buffer = { duration: frames / rate, samples: new Float32Array(frames), copyToChannel(data) { this.samples.set(data); } };
      buffers.push(buffer);
      return buffer;
    }),
    createBufferSource: vi.fn(() => {
      const source = { playbackRate: { value: 1 }, connect: vi.fn(), disconnect: vi.fn(), start: vi.fn(), stop: vi.fn(), onended: null };
      sources.push(source);
      return source;
    }),
  };
}

it("starts PCM playback before the HTTP stream has finished and schedules chunks consecutively", async () => {
  let input;
  const stream = new ReadableStream({ start(controller) { input = controller; } });
  const audioContext = context();
  const finished = vi.fn();
  const playing = playPcmStream(stream, 24000, undefined, { audioContext }).then(finished);
  input.enqueue(new Uint8Array([0, 64, 0]));
  await vi.waitFor(() => expect(audioContext.sources).toHaveLength(1));
  expect(audioContext.buffers[0].samples[0]).toBe(0.5);
  expect(audioContext.sources[0].start).toHaveBeenCalled();
  expect(finished).not.toHaveBeenCalled();
  input.enqueue(new Uint8Array([192]));
  await vi.waitFor(() => expect(audioContext.sources).toHaveLength(2));
  expect(audioContext.buffers[1].samples[0]).toBe(-0.5);
  const [first, second] = audioContext.sources;
  expect(second.start.mock.calls[0][0]).toBeCloseTo(first.start.mock.calls[0][0] + 1 / 24000);
  input.close();
  await Promise.resolve();
  first.onended();
  second.onended();
  await playing;
  expect(finished).toHaveBeenCalledTimes(1);
});

it("cancels a blocked network read and stops scheduled audio", async () => {
  let input;
  const cancel = vi.fn();
  const stream = new ReadableStream({ start(controller) { input = controller; }, cancel });
  const audioContext = context();
  const controller = new AbortController();
  const onAudio = vi.fn();
  const playing = playPcmStream(stream, 24000, controller.signal, { audioContext, onAudio });
  const rejection = expect(playing).rejects.toMatchObject({ name: "AbortError" });
  input.enqueue(new Uint8Array([1, 0]));
  await vi.waitFor(() => expect(audioContext.sources).toHaveLength(1));
  controller.abort();
  await rejection;
  expect(cancel).toHaveBeenCalled();
  expect(audioContext.sources[0].stop).toHaveBeenCalled();
  expect(onAudio).toHaveBeenLastCalledWith(null);
});

it("changes speed by rescheduling buffered audio from the current position", async () => {
  let input;
  const stream = new ReadableStream({ start(controller) { input = controller; } });
  const audioContext = context();
  let player;
  const controller = new AbortController();
  const playing = playPcmStream(stream, 24000, controller.signal, {
    audioContext, onAudio: (value) => { if (value) player = value; },
  });
  const rejection = expect(playing).rejects.toMatchObject({ name: "AbortError" });
  input.enqueue(new Uint8Array(48000));
  await vi.waitFor(() => expect(audioContext.sources).toHaveLength(1));
  audioContext.currentTime = 0.52;
  player.playbackRate = 1.5;
  expect(audioContext.sources[0].stop).toHaveBeenCalled();
  expect(audioContext.sources[1].playbackRate.value).toBe(1.5);
  expect(audioContext.sources[1].start.mock.calls[0][1]).toBeCloseTo(0.5);
  controller.abort();
  await rejection;
});

it("rejects PCM ending in an incomplete sample", async () => {
  const stream = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array([1])); controller.close(); } });
  await expect(playPcmStream(stream, 24000, undefined, { audioContext: context() })).rejects.toThrow("PCM");
});

it("reports audible source time across buffering and playback speed changes", async () => {
  let input;
  const stream = new ReadableStream({ start(c) { input = c; } });
  const audioContext = context();
  const controller = new AbortController();
  const progress = vi.fn();
  let player;
  const playing = playPcmStream(stream, 24000, controller.signal, {
    audioContext, onProgress: progress, onAudio: (value) => { if (value) player = value; },
  });
  const rejection = expect(playing).rejects.toMatchObject({ name: 'AbortError' });
  input.enqueue(new Uint8Array(96000));
  await vi.waitFor(() => expect(audioContext.sources).toHaveLength(1));
  audioContext.currentTime = 0.52;
  await vi.waitFor(() => expect(progress).toHaveBeenCalledWith(expect.closeTo(0.5, 2)));
  player.playbackRate = 2;
  audioContext.currentTime = 0.79;
  await vi.waitFor(() => expect(progress).toHaveBeenCalledWith(expect.closeTo(1, 2)));
  controller.abort();
  await rejection;
});
