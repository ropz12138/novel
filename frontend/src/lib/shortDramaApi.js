import { API_BASE } from './runtime-config';
import { authFetch, parseResponse } from './authFetch';

export async function sendStoryboardMessage(workId, chapterId, body, signal, onEvent) {
  const response = await authFetch(`${API_BASE}/works/${encodeURIComponent(workId)}/chapters/${encodeURIComponent(chapterId)}/short-drama/chat`, {
    method: 'POST',
    headers: { Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  });
  return consumeStoryboardStream(response, onEvent);
}

export async function resumeStoryboardSession(workId, chapterId, sessionId, signal, onEvent) {
  const response = await authFetch(`${API_BASE}/works/${encodeURIComponent(workId)}/chapters/${encodeURIComponent(chapterId)}/short-drama/sessions/${encodeURIComponent(sessionId)}/stream`, { signal, headers: { Accept: 'text/event-stream' } });
  return consumeStoryboardStream(response, onEvent);
}

async function consumeStoryboardStream(response, onEvent) {
  if (!response.ok) await parseResponse(response, '分镜设计失败');
  if (!response.body) throw new Error('分镜设计失败');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let eventName = '';
  let donePayload = null;
  const consume = (chunk) => {
    buffer += chunk;
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventName = line.slice(7).trim();
      } else if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));
        if (eventName === 'error') throw new Error(data.message || '分镜设计失败');
        if (eventName === 'storyboard_done') donePayload = data;
        else if (eventName) onEvent?.(eventName, data);
        eventName = '';
      } else if (line.trim() === '') {
        eventName = '';
      }
    }
  };
  while (true) {
    const { done, value } = await reader.read();
    if (value) consume(decoder.decode(value, { stream: !done }));
    if (donePayload) {
      await reader.cancel();
      return donePayload;
    }
    if (done) {
      consume(decoder.decode());
      if (buffer.trim()) consume('\n');
      break;
    }
  }
  if (!donePayload) throw new Error('分镜设计未完成');
  return donePayload;
}

export async function dramaJson(workId, chapterId, suffix = '', options = {}) {
  const response = await authFetch(`${API_BASE}/works/${encodeURIComponent(workId)}/chapters/${encodeURIComponent(chapterId)}/short-drama${suffix}`, options);
  return parseResponse(response, '短剧工作台请求失败');
}
export const getDramaWorkspace = (w, c) => dramaJson(w, c);
export const saveDramaWorkspace = (w, c, board) => dramaJson(w, c, '', { method: 'PUT', body: JSON.stringify(board) });
export async function saveDramaPortraits(workId, body) {
  const response = await authFetch(`${API_BASE}/works/${encodeURIComponent(workId)}/short-drama/portraits`, { method: 'PUT', body: JSON.stringify(body) });
  return parseResponse(response, '立绘保存失败');
}
export async function fetchPortraitFile(workId, portraitId) {
  const response = await authFetch(`${API_BASE}/works/${encodeURIComponent(workId)}/short-drama/portraits/${encodeURIComponent(portraitId)}/file`);
  if (!response.ok) await parseResponse(response, '立绘文件不存在');
  return response.blob();
}
export async function listDramaImages(workId) {
  return parseResponse(await authFetch(`${API_BASE}/works/${encodeURIComponent(workId)}/short-drama/image-jobs`), '立绘任务读取失败');
}
export async function generateDramaPortrait(workId, portraitId, body) {
  return parseResponse(await authFetch(`${API_BASE}/works/${encodeURIComponent(workId)}/short-drama/portraits/${encodeURIComponent(portraitId)}/generate`, {
    method: 'POST', body: JSON.stringify(body),
  }), '立绘生成提交失败');
}
async function workSessionJson(workId, options = {}) {
  return parseResponse(await authFetch(`${API_BASE}/works/${encodeURIComponent(workId)}/short-drama/sessions`, options), '短剧会话请求失败');
}
export const listDramaSessions = (w) => workSessionJson(w);
export const createDramaSession = (w, _c, title = '新对话') => workSessionJson(w, { method: 'POST', body: JSON.stringify({ title }) });
export const getDramaSession = (w, c, id) => dramaJson(w, c, `/sessions/${encodeURIComponent(id)}`);
export const listDramaVideos = (w, c) => dramaJson(w, c, '/videos');
export const generateDramaVideos = (w, c, shotIds, quality = 'final') => dramaJson(w, c, '/videos', { method: 'POST', body: JSON.stringify({ shot_ids: shotIds, quality }) });
export const deleteDramaVideo = (w, c, id) => dramaJson(w, c, `/videos/${encodeURIComponent(id)}`, { method: 'DELETE' });
export async function fetchDramaVideo(w, c, id) {
  const response = await authFetch(`${API_BASE}/works/${encodeURIComponent(w)}/chapters/${encodeURIComponent(c)}/short-drama/videos/${encodeURIComponent(id)}/file`);
  if (!response.ok) await parseResponse(response, '视频读取失败');
  return response.blob();
}
export async function fetchDramaPoster(w, c, id) {
  const response = await authFetch(`${API_BASE}/works/${encodeURIComponent(w)}/chapters/${encodeURIComponent(c)}/short-drama/videos/${encodeURIComponent(id)}/poster`);
  if (!response.ok) await parseResponse(response, '视频首帧读取失败');
  return response.blob();
}
