import { authFetch } from "./authFetch";
import { API_BASE } from "./runtime-config";

export function fetchAudiobookStart(options) {
  return fetchAudiobookLine({ ...options, endpoint: "audiobook" });
}

export async function fetchAudiobookLine({ workId, nodeId, lineIndex, signal, endpoint = "audiobook-line", chunkIndex, contentSha256 }) {
  const response = await authFetch(`${API_BASE}/works/${workId}/nodes/${nodeId}/${endpoint}`, {
    method: "POST",
    body: JSON.stringify({ line_index: lineIndex, chunk_index: chunkIndex, content_sha256: contentSha256 }),
    signal,
  });
  if (!response.ok) {
    const body = await response.json();
    if (typeof body.detail !== "string") throw new Error("朗读失败");
    throw new Error(body.detail);
  }
  const sampleRate = Number(response.headers.get("X-Audio-Sample-Rate"));
  if (![16000, 24000].includes(sampleRate)) throw new Error("响应采样率必须为 16000 或 24000");
  const chunk = response.headers.get("X-Audio-Chunk");
  return { pcm: response.body, sampleRate, scope: response.headers.get("X-Audio-Scope"), chunk: chunk ? JSON.parse(chunk) : null };
}

export async function prepareAudioPlayback() {
  const context = new AudioContext();
  try {
    await context.resume();
    return context;
  } catch (error) {
    await context.close();
    throw error;
  }
}

export async function playPcmStream(stream, sampleRate, signal, { playbackRate = 1, onAudio, audioContext, onProgress } = {}) {
  const reader = stream.getReader();
  const tracks = [];
  let rate = playbackRate;
  let completedSeconds = 0;
  const reportProgress = () => {
    const track = tracks[0];
    const elapsed = track ? Math.min(track.buffer.duration, track.offset + Math.max(0, audioContext.currentTime - track.startAt) * rate) : 0;
    onProgress?.(completedSeconds + elapsed);
  };
  const progressTimer = onProgress ? setInterval(reportProgress, 100) : null;
  let tail = 0;
  let carry = new Uint8Array();
  let received = 0;
  let finished = false;
  let resolvePlayback;
  let rejectPlayback;
  const playback = new Promise((resolve, reject) => { resolvePlayback = resolve; rejectPlayback = reject; });
  const abortError = () => Object.assign(new Error("aborted"), { name: "AbortError" });
  const checkFinished = () => { if (finished && tracks.length === 0) resolvePlayback(); };
  const schedule = (track) => {
    const source = audioContext.createBufferSource();
    source.buffer = track.buffer;
    source.playbackRate.value = rate;
    source.connect(audioContext.destination);
    track.source = source;
    track.startAt = Math.max(audioContext.currentTime + 0.02, tail);
    source.onended = () => {
      source.disconnect();
      completedSeconds += track.buffer.duration;
      tracks.splice(tracks.indexOf(track), 1);
      reportProgress();
      checkFinished();
    };
    source.start(track.startAt, track.offset);
    tail = track.startAt + (track.buffer.duration - track.offset) / rate;
  };
  const player = {
    get playbackRate() { return rate; },
    set playbackRate(value) {
      const now = audioContext.currentTime;
      for (const track of tracks) {
        track.offset += Math.max(0, now - track.startAt) * rate;
        track.source.onended = null;
        track.source.stop();
        track.source.disconnect();
      }
      rate = value;
      tail = now;
      for (let index = tracks.length - 1; index >= 0; index -= 1) {
        if (tracks[index].offset >= tracks[index].buffer.duration) {
          completedSeconds += tracks[index].buffer.duration;
          tracks.splice(index, 1);
        }
      }
      for (const track of tracks) schedule(track);
      checkFinished();
    },
  };
  const stop = () => {
    rejectPlayback(abortError());
    void reader.cancel().catch(() => {});
  };
  const pump = async () => {
    if (signal?.aborted) throw abortError();
    while (true) {
      const { value, done } = await reader.read();
      if (signal?.aborted) throw abortError();
      if (done) break;
      const bytes = new Uint8Array(carry.length + value.length);
      bytes.set(carry);
      bytes.set(value, carry.length);
      const byteLength = bytes.length - bytes.length % 2;
      carry = bytes.slice(byteLength);
      if (byteLength === 0) continue;
      const samples = new Float32Array(byteLength / 2);
      const view = new DataView(bytes.buffer);
      for (let index = 0; index < samples.length; index += 1) samples[index] = view.getInt16(index * 2, true) / 32768;
      const buffer = audioContext.createBuffer(1, samples.length, sampleRate);
      buffer.copyToChannel(samples, 0);
      received += byteLength;
      const track = { buffer, offset: 0 };
      tracks.push(track);
      schedule(track);
    }
    if (carry.length || received === 0) throw new Error("PCM 音频为空或采样不完整");
    finished = true;
    checkFinished();
  };
  signal?.addEventListener("abort", stop, { once: true });
  onAudio?.(player);
  try {
    await Promise.all([pump(), playback]);
  } finally {
    clearInterval(progressTimer);
    signal?.removeEventListener("abort", stop);
    for (const track of tracks) {
      track.source.onended = null;
      track.source.stop();
      track.source.disconnect();
    }
    await reader.cancel().catch(() => {});
    reader.releaseLock();
    onAudio?.(null);
  }
}
