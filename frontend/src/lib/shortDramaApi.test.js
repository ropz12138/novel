import { beforeEach, describe, expect, it, vi } from 'vitest';
import { authFetch } from './authFetch';
import { sendStoryboardMessage, listDramaSessions, createDramaSession, listDramaImages, generateDramaPortrait, generateDramaVideos, fetchDramaPoster, deleteDramaVideo } from './shortDramaApi';

vi.mock('./authFetch', () => ({ authFetch: vi.fn(), parseResponse: vi.fn() }));

function streamResponse(chunks, { ok = true, status = 200, json } = {}) {
  const encoder = new TextEncoder();
  let index = 0;
  return {
    ok, status,
    headers: new Headers({ 'content-type': ok ? 'text/event-stream' : 'application/json' }),
    json: async () => json,
    body: {
      getReader() {
        return {
          cancel: vi.fn().mockResolvedValue(),
          async read() {
            if (index >= chunks.length) return { done: true, value: undefined };
            return { done: false, value: encoder.encode(chunks[index++]) };
          },
        };
      },
    },
  };
}

describe('short drama agent API', () => {
  beforeEach(() => vi.clearAllMocks());
  it('lists and creates sessions under the work independently of chapters', async () => {
    authFetch.mockResolvedValue({ ok: true });
    await listDramaSessions('work/a', 'chapter-1');
    await listDramaSessions('work/a', 'chapter-2');
    await createDramaSession('work/a', 'chapter-2', '作品对话');
    expect(authFetch.mock.calls.map(([url]) => url)).toEqual(Array(3).fill('/novel/api/works/work%2Fa/short-drama/sessions'));
    expect(JSON.parse(authFetch.mock.calls[2][1].body)).toEqual({ title: '作品对话' });
  });
  it('streams storyboard deltas with fetch and ignores heartbeat comments', async () => {
    const seen = [];
    authFetch.mockResolvedValue(streamResponse([
      ': heartbeat\n\n',
      'event: storyboard_stream\ndata: {"phase":"tool_args","chunk":"{\\"message\\":\\"你',
      '好\\"}"}\n\n',
      'event: storyboard_done\ndata: {"message":"你好","shots":null}\n\n',
    ]));
    const body = { message: '完整要求'.repeat(2000), history: [{ role: 'user', content: '历史完整正文'.repeat(1000) }] };
    const controller = new AbortController();
    const result = await sendStoryboardMessage('work/a', 'chapter b', body, controller.signal, (event, data) => seen.push([event, data]));
    const [url, options] = authFetch.mock.calls[0];
    expect(url).toBe('/novel/api/works/work%2Fa/chapters/chapter%20b/short-drama/chat');
    expect(options.method).toBe('POST');
    expect(options.headers.Accept).toBe('text/event-stream');
    expect(JSON.parse(options.body)).toEqual(body);
    expect(options.signal).toBe(controller.signal);
    expect(seen).toEqual([['storyboard_stream', { phase: 'tool_args', chunk: '{"message":"你好"}' }]]);
    expect(result).toEqual({ message: '你好', shots: null });
  });

  it('finishes on the saved done event without waiting for the HTTP connection to close', async () => {
    const cancel = vi.fn().mockResolvedValue(); let count = 0;
    authFetch.mockResolvedValue({ ok: true, body: { getReader: () => ({ cancel, read: async () => {
      if (count++) return new Promise(() => {});
      return { done: false, value: new TextEncoder().encode('event: storyboard_done\ndata: {"message":"已保存","shots":[]}\n\n') };
    } }) } });
    const result = await sendStoryboardMessage('w', 'c', { message: '设计' });
    expect(result.message).toBe('已保存'); expect(cancel).toHaveBeenCalled();
  });

  it('raises the server error text and does not invent shots', async () => {
    authFetch.mockResolvedValue(streamResponse([
      'event: storyboard_stream\ndata: {"phase":"reasoning","chunk":"先看原文"}\n\n',
      'event: error\ndata: {"message":"模型调用失败"}\n\n',
    ]));
    const seen = [];
    await expect(sendStoryboardMessage('w', 'c', { message: '设计' }, undefined, (event, data) => seen.push(data.chunk))).rejects.toThrow('模型调用失败');
    expect(seen).toEqual(['先看原文']);
  });
});


it('submits portrait parameters to the work-owned SSH image job endpoint', async () => {
  authFetch.mockClear(); authFetch.mockResolvedValue({ ok: true });
  await listDramaImages('work/a');
  await generateDramaPortrait('work/a', 'portrait/b', { width: 768, height: 1024, seed: 42 });
  expect(authFetch.mock.calls[0][0]).toBe('/novel/api/works/work%2Fa/short-drama/image-jobs');
  const [url, options] = authFetch.mock.calls[1];
  expect(url).toBe('/novel/api/works/work%2Fa/short-drama/portraits/portrait%2Fb/generate');
  expect(options.method).toBe('POST');
  expect(JSON.parse(options.body)).toEqual({ width: 768, height: 1024, seed: 42 });
});


it('reads a finished video first frame from the poster endpoint', async () => {
  authFetch.mockClear();
  authFetch.mockResolvedValue({ ok: true, blob: async () => 'frame' });
  await expect(fetchDramaPoster('w/a', 'c/b', 'job/1')).resolves.toBe('frame');
  expect(authFetch.mock.calls[0][0]).toBe('/novel/api/works/w%2Fa/chapters/c%2Fb/short-drama/videos/job%2F1/poster');
});

it('deletes one finished video by its job id', async () => {
  authFetch.mockClear();
  authFetch.mockResolvedValue({ ok: true, status: 204 });
  await deleteDramaVideo('w/a', 'c/b', 'job/1');
  expect(authFetch.mock.calls[0][0]).toBe('/novel/api/works/w%2Fa/chapters/c%2Fb/short-drama/videos/job%2F1');
  expect(authFetch.mock.calls[0][1]).toMatchObject({ method: 'DELETE' });
});

it('sends preview or final video quality explicitly and defaults legacy calls to final', async () => {
  authFetch.mockClear(); authFetch.mockResolvedValue({ ok: true });
  await generateDramaVideos('w', 'c', ['s1'], 'preview');
  await generateDramaVideos('w', 'c', ['s1']);
  expect(authFetch.mock.calls.map(([, options]) => JSON.parse(options.body))).toEqual([
    { shot_ids: ['s1'], quality: 'preview' }, { shot_ids: ['s1'], quality: 'final' },
  ]);
});
