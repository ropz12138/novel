const PLOT_START = "[[PLOT]]";
const PLOT_END = "[[/PLOT]]";

export function splitAudiobookLines(text) {
  if (text === "") return [];
  const parts = [];
  let start = 0;
  for (let index = 0; index < text.length; index += 1) {
    if (text[index] === "\n") {
      parts.push(text.slice(start, index + 1));
      start = index + 1;
    }
  }
  if (start < text.length) parts.push(text.slice(start));
  if (parts.join("") !== text) throw new Error("split changed text");
  return parts;
}

export function lineSpeechText(line) {
  return line.split("[[PLOT]]").join("").split("[[/PLOT]]").join("").trim();
}

export function lineIsSpeakable(speech) {
  for (const char of speech) {
    if (char.charCodeAt(0) < 128 && /[0-9A-Za-z]/.test(char)) return true;
    const code = char.codePointAt(0);
    if (code >= 0x4e00 && code <= 0x9fff) return true;
  }
  return false;
}

function abortError() {
  const error = new Error("aborted");
  error.name = "AbortError";
  return error;
}

export function paragraphAudiobookLines(content) {
  const text = content || "";
  if (text === "") return [];
  const paragraphs = text.split("\n\n");
  const all = splitAudiobookLines(text);
  let cursor = 0;
  return paragraphs.map((paragraph, paragraphIndex) => {
    const mapped = splitAudiobookLines(paragraph).map((raw) => {
      const display = raw.endsWith("\n") ? raw.slice(0, -1) : raw;
      const item = { index: cursor, raw: all[cursor], display };
      cursor += 1;
      return item;
    });
    if (paragraphIndex < paragraphs.length - 1) cursor += 1;
    return mapped;
  });
}

export async function playChapterLines({ lines, fetchLine, playPcm, onLine, signal, startIndex = 0 }) {
  if (!Number.isInteger(startIndex) || startIndex < 0 || startIndex > lines.length) throw new Error("line index out of range");
  if (signal?.aborted) throw abortError();
  const nextSpeakable = (start) => {
    for (let index = start; index < lines.length; index += 1) {
      if (lineIsSpeakable(lineSpeechText(lines[index]))) return index;
    }
    return lines.length;
  };
  let index = nextSpeakable(startIndex);
  if (index === lines.length) throw new Error("没有可朗读的正文");
  const requests = new AbortController();
  const stop = () => requests.abort();
  signal?.addEventListener("abort", stop, { once: true });
  const requestLine = (lineIndex) => {
    const request = { audio: null };
    request.result = Promise.resolve()
      .then(() => fetchLine(lineIndex, { signal: requests.signal }))
      .then((audio) => ({ ...audio, ...bufferPcmStream(audio.pcm, requests.signal) }))
      .then((audio) => { request.audio = audio; return { audio }; }, (error) => ({ error }));
    return request;
  };
  let pending = requestLine(index);
  try {
    while (index < lines.length) {
      const result = await untilAborted(pending.result, requests.signal);
      if ("error" in result) throw result.error;
      const audio = result.audio;
      let pause = false;
      try {
        onLine(index);
        const playing = playPcm(audio.pcm, audio.sampleRate);
        const next = nextSpeakable(index + 1);
        pending = next < lines.length ? requestLine(next) : null;
        await untilAborted(playing, requests.signal);
        pause = pending?.audio?.hasAudio() === true;
        index = next;
      } finally {
        audio.dispose();
      }
      if (pause) await pauseBetweenLines(requests.signal);
    }
  } finally {
    requests.abort();
    signal?.removeEventListener("abort", stop);
  }
}

async function pauseBetweenLines(signal) {
  let timer;
  try {
    await untilAborted(new Promise((resolve) => { timer = setTimeout(resolve, 500); }), signal);
  } finally {
    clearTimeout(timer);
  }
}

function untilAborted(promise, signal) {
  return new Promise((resolve, reject) => {
    const stop = () => reject(abortError());
    signal.addEventListener("abort", stop, { once: true });
    Promise.resolve(promise).then(resolve, reject).finally(() => signal.removeEventListener("abort", stop));
    if (signal.aborted) stop();
  });
}

function bufferPcmStream(source, signal) {
  const reader = source.getReader();
  let target;
  let sourceDone = false;
  let received = 0;
  let failed = false;
  let finishBuffer;
  let failure;
  const finished = new Promise(resolve => { finishBuffer = resolve; });
  const dispose = () => {
    failed = true;
    signal.removeEventListener("abort", dispose);
    target.error(abortError());
    if (!sourceDone) void reader.cancel().catch(() => {});
  };
  const pcm = new ReadableStream({
    start(controller) {
      target = controller;
      signal.addEventListener("abort", dispose, { once: true });
      if (signal.aborted) dispose();
      void (async () => {
        try {
          while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            received += value.byteLength;
            controller.enqueue(value);
          }
          controller.close();
        } catch (error) {
          failed = true;
          failure = error;
          controller.error(error);
        } finally {
          sourceDone = true;
          reader.releaseLock();
          finishBuffer({ error: failure });
        }
      })();
    },
    cancel() {
      signal.removeEventListener("abort", dispose);
      if (!sourceDone) return reader.cancel();
    },
  });
  return { pcm, dispose, finished, hasAudio: () => received >= 2 && !failed };
}

// Download one paragraph at a time through EOF, independently of playback.
// Unplayed PCM may cover the rest of the chapter; consumed paragraphs are released.
export async function playChapterParagraphs({ first, fetchChunk, playPcm, onLine, signal }) {
  const requests = new AbortController();
  const stop = () => requests.abort();
  signal.addEventListener("abort", stop, { once: true });
  if (signal.aborted) requests.abort();
  const entries = Array.from({ length: first.chunk.count }, () => {
    const entry = {};
    entry.ready = new Promise(resolve => { entry.resolve = result => { entry.result = result; resolve(result); }; });
    return entry;
  });
  const cached = new Set();
  const download = async () => {
    for (let index = first.chunk.index; index < first.chunk.count; index += 1) {
      try {
        const fetched = index === first.chunk.index ? first : await fetchChunk(index, { signal: requests.signal });
        if (requests.signal.aborted) {
          await fetched.pcm.cancel();
          throw abortError();
        }
        const audio = { ...fetched, ...bufferPcmStream(fetched.pcm, requests.signal) };
        cached.add(audio);
        entries[index].resolve({ audio });
        const result = await untilAborted(audio.finished, requests.signal);
        if (result.error) return;
      } catch (error) {
        entries[index]?.resolve({ error });
        return;
      }
    }
  };
  void download();
  try {
    for (let index = first.chunk.index; index < first.chunk.count; index += 1) {
      const result = await untilAborted(entries[index].ready, requests.signal);
      if (result.error) throw result.error;
      const audio = result.audio;
      try {
        onLine(audio.chunk.line_index);
        await untilAborted(playPcm(audio.pcm, audio.sampleRate), requests.signal);
        const next = entries[index + 1]?.result?.audio;
        if (next?.hasAudio() && next.chunk.line_index !== audio.chunk.line_index) {
          await pauseBetweenLines(requests.signal);
        }
      } finally {
        cached.delete(audio);
        audio.dispose();
        entries[index] = null;
      }
    }
  } finally {
    requests.abort();
    signal.removeEventListener("abort", stop);
    for (const audio of cached) audio.dispose();
    cached.clear();
    entries.length = 0;
  }
}
