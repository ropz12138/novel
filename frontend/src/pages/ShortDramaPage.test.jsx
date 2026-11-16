import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { fetchNodes } from '../lib/canvasApi';
import * as api from '../lib/shortDramaApi';
import { ShortDramaPage } from './ShortDramaPage';
const backNavigationMocks = vi.hoisted(() => ({ listener: null }));
vi.mock('../lib/appBackNavigation', () => ({
  subscribeAppBack: vi.fn(async (listener) => {
    backNavigationMocks.listener = listener;
    return vi.fn();
  }),
}));
vi.mock('../lib/canvasApi', () => ({ fetchNodes: vi.fn() }));
vi.mock('../lib/shortDramaApi', () => ({ sendStoryboardMessage: vi.fn(), resumeStoryboardSession: vi.fn(), getDramaWorkspace: vi.fn(), saveDramaWorkspace: vi.fn(), saveDramaPortraits: vi.fn(), fetchPortraitFile: vi.fn(), listDramaImages: vi.fn(), generateDramaPortrait: vi.fn(), listDramaSessions: vi.fn(), createDramaSession: vi.fn(), getDramaSession: vi.fn(), listDramaVideos: vi.fn(), generateDramaVideos: vi.fn(), deleteDramaVideo: vi.fn(), fetchDramaVideo: vi.fn(), fetchDramaPoster: vi.fn() }));
const mediaListeners = new Set();
const nativeMatchMedia = window.matchMedia;
let mobile = false;
function installMatchMedia() {
  mobile = false;
  mediaListeners.clear();
  window.matchMedia = (query) => ({
    media: query,
    get matches() { return mobile; },
    addEventListener(type, listener) { if (type === 'change') mediaListeners.add(listener); },
    removeEventListener(type, listener) { if (type === 'change') mediaListeners.delete(listener); },
  });
}
function setMobile(next) {
  mobile = next;
  act(() => { mediaListeners.forEach((listener) => listener()); });
}
const chapter = { id: 'chapter-1', type: 'chapter', title: '第一章 雨夜', content: '雨水打在门上。\n\n林雨推门而入。' };
const copy = value => structuredClone(value);
const shot = (id = 's1', duration = 5) => ({ id, title: '推门', prompt: '完整视频提示词', duration, seed: 42, mode: 'turbo', inputMode: 'text', roles: [], sourceQuote: '林雨推门而入。', referencePaths: '', firstFrame: '', lastFrame: '', sourceStartLine: 3, sourceEndLine: 3 });
let board, sessions, histories;
function open() { return render(<MemoryRouter initialEntries={['/short-drama/work-1/chapter-1']}><Routes><Route path='/short-drama/:workId/:chapterId' element={<ShortDramaPage />} /></Routes></MemoryRouter>); }
async function ready() { await screen.findByText('第一章 雨夜'); }
function chooseShot(index) { fireEvent.click(screen.getByRole('button', { name: `选择镜头 ${index}` })); }
function send(message = '设计分镜') { fireEvent.change(screen.getByLabelText('对话输入'), { target: { value: message } }); fireEvent.click(screen.getByRole('button', { name: '发送给 Agent' })); }
function complete(message = '已生成分镜', generated = [shot()], sessionId = 'session-1') {
  board = { ...board, shots: generated, revision: board.revision + 1, activeSessionId: null };
  histories[sessionId] = [...histories[sessionId], { id: crypto.randomUUID(), role: 'user', content: '设计分镜' }, { id: crypto.randomUUID(), role: 'assistant', content: message, reasoning: '完整思考' }];
  return { message, shots: generated, workspace: copy(board), messages: copy(histories[sessionId]) };
}

function stored(id, role, content = '', extra = {}) {
  return { id, role, content, reasoning: '', arguments: '', status: 'done', sort_order: 0, ...extra };
}

beforeEach(() => {
  installMatchMedia();
  localStorage.clear(); localStorage.setItem('novel_user', 'author');
  Object.values(api).forEach(fn => fn.mockReset()); fetchNodes.mockReset();
  board = { sourceContent: chapter.content, width: 960, height: 544, style: '', revision: 0, portraitRevision: 0, activeSessionId: null, shots: [], portraits: [] };
  sessions = [{ id: 'session-1', title: '对话 1', running: false }]; histories = { 'session-1': [] };
  fetchNodes.mockResolvedValue({ nodes: [chapter, { id: 'role-1', type: 'character', title: '林雨', content: '黑色长发，蓝色棉布上衣。' }] });
  api.getDramaWorkspace.mockImplementation(async () => copy(board)); api.listDramaSessions.mockImplementation(async () => copy(sessions));
  api.createDramaSession.mockImplementation(async () => { const row = { id: `session-${sessions.length + 1}`, title: `对话 ${sessions.length + 1}`, running: false }; sessions.push(row); histories[row.id] = []; return copy(row); });
  api.getDramaSession.mockImplementation(async (_w, _c, id) => ({ ...copy(sessions.find(s => s.id === id)), messages: copy(histories[id]), workspace: copy(board) }));
  api.saveDramaWorkspace.mockImplementation(async (_w, _c, value) => { if (value.revision !== board.revision) throw new Error('分镜已更新'); board = { ...board, ...copy(value), revision: value.revision + 1, activeSessionId: null }; return copy(board); });
  api.saveDramaPortraits.mockImplementation(async (_w, value) => { if (value.revision !== board.portraitRevision) throw new Error('立绘已更新'); board = { ...board, portraits: copy(value.portraits), portraitRevision: value.revision + 1 }; return { portraitRevision: board.portraitRevision, portraits: copy(board.portraits) }; });
  api.listDramaImages.mockResolvedValue([]);
  api.generateDramaPortrait.mockResolvedValue({ id: 'image-1', portrait_id: 'p1', status: 'queued' });
  api.fetchPortraitFile.mockResolvedValue(new Blob(['png'], { type: 'image/png' }));
  api.listDramaVideos.mockResolvedValue([]); api.generateDramaVideos.mockResolvedValue([]);
  api.fetchDramaPoster.mockResolvedValue(new Blob(['frame'], { type: 'image/jpeg' }));
});
afterEach(() => { cleanup(); mediaListeners.clear(); window.matchMedia = nativeMatchMedia; vi.restoreAllMocks(); });

describe('persisted short drama workbench', () => {
  it('keeps the work area focused and moves frame controls into chapter settings', async () => {
    board.shots = [shot()];
    open(); await ready();
    expect(screen.queryByLabelText('画面宽度')).toBeNull();
    expect(screen.getByLabelText('全章分镜总时长').textContent).toBe('共 1 镜 · 总时长 5 秒');
    expect(screen.queryByText(/预计成片|已保存到服务器|远端临时参考图|STORYBOARD/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '本章生成设置' }));
    const settings = screen.getByRole('dialog', { name: '本章生成设置' });
    expect(within(settings).getByLabelText('画面宽度').value).toBe('960');
    fireEvent.click(within(settings).getByRole('button', { name: '544×960' }));
    await waitFor(() => expect(board.width).toBe(544), { timeout: 2000 });
    fireEvent.click(within(settings).getByRole('button', { name: '关闭本章生成设置' }));
    chooseShot(1);
    expect(screen.getByLabelText('镜头 1 提示词').value).toBe('完整视频提示词');
  });
  it('locks the first frame to an earlier shot and hides later shots', async () => {
    board.shots = [shot('s1'), { ...shot('s2'), title: '回望' }, { ...shot('s3'), title: '离开' }];
    open(); await ready();
    chooseShot(1);
    expect([...screen.getByLabelText('镜头 1 首帧来源').options].map((option) => option.textContent)).toEqual(['不锁定']);
    chooseShot(2);
    const source = screen.getByLabelText('镜头 2 首帧来源');
    expect(within(source).getByRole('option', { name: '01 推门' }).value).toBe('s1');
    expect(within(source).queryByRole('option', { name: '02 回望' })).toBeNull();
    expect(within(source).queryByRole('option', { name: '03 离开' })).toBeNull();
    expect(screen.queryByText('首帧路径')).toBeNull();
    fireEvent.change(source, { target: { value: 's1' } });
    await waitFor(() => expect(board.shots[1]).toMatchObject({ inputMode: 'first_lock', firstFrameShotId: 's1' }), { timeout: 2000 });
    chooseShot(3);
    const later = screen.getByLabelText('镜头 3 首帧来源');
    expect(within(later).getByRole('option', { name: '02 回望' })).toBeTruthy();
    expect(within(later).queryByRole('option', { name: '03 离开' })).toBeNull();
  });
  it('removes the task queue and blocks every media button while one video is unfinished', async () => {
    board.shots = [shot('s1'), { ...shot('s2'), title: '回望' }];
    board.portraits = [{ id: 'p1', roleId: 'role-1', imagePath: '', prompt: '完整立绘' }];
    api.listDramaVideos.mockResolvedValue([
      { id: 'busy', shot_id: 's2', title: '回望', status: 'running', quality: 'final', duration: 5, width: 960, height: 544 },
    ]);
    open(); await ready();
    expect(screen.queryByRole('button', { name: '任务队列' })).toBeNull();
    chooseShot(1);
    const first = screen.getByRole('group', { name: '镜头 1 操作区' });
    expect(within(first).getByRole('button', { name: '生成预览视频' }).disabled).toBe(true);
    expect(within(first).getByRole('button', { name: '生成最终视频' }).disabled).toBe(true);
    expect(within(first).getByText('已有生图或生视频正在处理')).toBeTruthy();
    chooseShot(2);
    const second = screen.getByRole('group', { name: '镜头 2 操作区' });
    expect(within(second).getByRole('button', { name: '生成预览视频' }).disabled).toBe(true);
    expect(within(second).getByRole('button', { name: '生成最终视频' }).disabled).toBe(true);
    fireEvent.click(screen.getByRole('tab', { name: /立绘设计/ }));
    expect(screen.getByRole('button', { name: '生成林雨立绘 1' }).disabled).toBe(true);
    expect(api.generateDramaVideos).not.toHaveBeenCalled();
    expect(api.generateDramaPortrait).not.toHaveBeenCalled();
  });

  it('loads a database session without adoption controls', async () => {
    open(); await ready(); expect(screen.getByLabelText('分镜会话').value).toBe('session-1');
    expect(screen.queryByRole('button', { name: '采用分镜方案' })).toBeNull(); expect(screen.queryByText('待采用的分镜方案')).toBeNull();
    expect(screen.getByRole('button', { name: '发送给 Agent' }).disabled).toBe(true); expect(screen.getByText('已保存')).toBeTruthy();
    const chat = screen.getByRole('complementary', { name: '分镜设计助手' });
    expect(within(chat).queryByText('章节全文与角色设定')).toBeNull();
    expect(within(chat).queryByText('完整要求 · 分镜生成后直接保存')).toBeNull();
    expect(within(chat).queryByText('从文字，到镜头')).toBeNull();
    expect(within(chat).getByLabelText('分镜会话').closest('.workbench-sidebar__header')).toBeTruthy();
  });
  it('ignores old browser records entirely', async () => {
    localStorage.setItem(`novel.short-drama.v1:${JSON.stringify(['author', 'work-1', 'chapter-1'])}`, JSON.stringify({ messages: [{ role: 'assistant', content: '旧对话' }], shots: [shot()] }));
    open(); await ready();
    expect(screen.queryByText('发现本浏览器中的旧分镜与对话记录。')).toBeNull();
    expect(screen.queryByRole('button', { name: '导入到服务器' })).toBeNull();
  });
  it('restores the work session preference across chapters', async () => {
    sessions.push({ id: 'session-2', title: '作品会话', running: false }); histories['session-2'] = [];
    localStorage.setItem('novel.drama.session:author:work-1', 'session-2');
    open(); await ready();
    expect(screen.getByLabelText('分镜会话').value).toBe('session-2');
  });
  it('does not subscribe to generation targeting another chapter', async () => {
    sessions[0].running = true; sessions[0].runningChapterId = 'chapter-2';
    open(); await ready();
    expect(api.resumeStoryboardSession).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: '发送给 Agent' }).disabled).toBe(true);
  });
  it('creates and switches sessions while sharing chapter shots', async () => {
    board.shots = [shot()]; histories['session-1'] = [{ id: 'm1', role: 'assistant', content: '第一个会话的历史' }];
    open(); await ready(); await screen.findByText('第一个会话的历史'); fireEvent.click(screen.getByRole('button', { name: '新建会话' }));
    await waitFor(() => expect(screen.getByLabelText('分镜会话').value).toBe('session-2'));
    chooseShot(1);
    expect(screen.queryByText('第一个会话的历史')).toBeNull(); expect(screen.getByLabelText('镜头 1 提示词').value).toBe('完整视频提示词');
    fireEvent.change(screen.getByLabelText('分镜会话'), { target: { value: 'session-1' } }); expect(await screen.findByText('第一个会话的历史')).toBeTruthy();
  });
  it('directly displays generated shots and reloads server messages after remount', async () => {
    api.sendStoryboardMessage.mockImplementation(async () => complete()); const mounted = open(); await ready(); send(); await screen.findByText('已生成分镜');
    chooseShot(1);
    expect(screen.getByLabelText('镜头 1 提示词').value).toBe('完整视频提示词'); expect(screen.queryByText('草稿')).toBeNull();
    expect(api.sendStoryboardMessage.mock.calls[0][2]).toEqual({ message: '设计分镜', source_content: chapter.content, session_id: 'session-1', selected_shot_id: null });
    mounted.unmount(); open(); await ready(); expect(await screen.findByText('已生成分镜')).toBeTruthy(); chooseShot(1); expect(screen.getByLabelText('镜头 1 提示词').value).toBe('完整视频提示词');
  });
  it('sends the draft when Enter is pressed and keeps Shift+Enter as a newline', async () => {
    api.sendStoryboardMessage.mockImplementation(async () => complete('已按回车发送'));
    open(); await ready();
    const input = screen.getByLabelText('对话输入');
    fireEvent.change(input, { target: { value: '设计分镜' } });
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true });
    expect(api.sendStoryboardMessage).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(await screen.findByText('已按回车发送')).toBeTruthy();
    expect(api.sendStoryboardMessage.mock.calls[0][2].message).toBe('设计分镜');
  });
  it('autosaves full edits and updates the chapter duration', async () => {
    board.shots = Array.from({ length: 5 }, (_, i) => shot(`s${i}`, 15)); open(); await ready();
    expect(screen.getByLabelText('全章分镜总时长').textContent).toContain('1 分 15 秒（75 秒）');
    chooseShot(2);
    const full = '完整内容\n' + '细节'.repeat(3000); fireEvent.change(screen.getByLabelText('镜头 2 提示词'), { target: { value: full } });
    await waitFor(() => expect(api.saveDramaWorkspace).toHaveBeenCalled(), { timeout: 2000 }); expect(board.shots[1].prompt).toBe(full);
    chooseShot(1);
    const firstCard = screen.getByLabelText('镜头 1 名称').closest('article');
    within(firstCard).getByText('更多').closest('details').open = true;
    fireEvent.click(within(firstCard).getByRole('button', { name: '删除镜头 1' }));
    expect(screen.getByLabelText('全章分镜总时长').textContent).toContain('1 分 0 秒（60 秒）');
  });
  it('flushes edits before sending and selects only the requested shot', async () => {
    board.shots = [shot('first'), shot('second')]; api.sendStoryboardMessage.mockImplementation(async () => complete('收到修改要求', board.shots)); open(); await ready();
    chooseShot(2);
    fireEvent.change(screen.getByLabelText('镜头 2 提示词'), { target: { value: '第二镜新的完整提示词' } });
    fireEvent.click(screen.getByLabelText('镜头 2 名称').closest('article').querySelector('.drama-shot-number'));
    fireEvent.change(screen.getByLabelText('对话输入'), { target: { value: '只改第二镜' } });
    fireEvent.click(screen.getByRole('button', { name: '发送给 Agent' }));
    await screen.findByText('收到修改要求'); expect(api.sendStoryboardMessage.mock.calls[0][2].selected_shot_id).toBe('second'); expect(board.shots[1].prompt).toBe('第二镜新的完整提示词');
  });
  it('shows streaming markdown and tool parameters using the shared timeline before saving', async () => {
    let emit, finish;
    api.sendStoryboardMessage.mockImplementation((_w, _c, _body, _signal, onEvent) => new Promise(resolve => {
      emit = onEvent; finish = () => resolve(complete('**已生成**'));
      onEvent('message_updated', stored('a1', 'assistant', '', { status: 'running', sort_order: 1 }));
      onEvent('storyboard_stream', { message_id: 'a1', phase: 'reasoning', chunk: '先看冲突。' });
    }));
    open(); await ready(); send(); await screen.findByText('先看冲突。');
    await act(async () => { emit('storyboard_stream', { message_id: 'a1', phase: 'content', chunk: '**已生成**' }); });
    expect(screen.getByTestId('streaming-message-bubble').querySelector('strong').textContent).toBe('已生成');
    await act(async () => {
      emit('message_updated', stored('a1', 'assistant', '**已生成**', { reasoning: '先看冲突。', sort_order: 1 }));
      emit('message_updated', stored('t1', 'tool_call', '', { tool_call_id: 'call1', tool_name: 'replace_storyboard', status: 'running', sort_order: 2 }));
      emit('storyboard_stream', { message_id: 't1', phase: 'tool_args', tool: 'replace_storyboard', chunk: '{"shots":[{"title":"推门","prompt":"完整视频提示词"}]}' });
    });
    expect(screen.getByText('工具调用 · replace_storyboard')).toBeTruthy();
    expect(screen.getByText(/完整视频提示词/)).toBeTruthy();
    expect(screen.queryByLabelText('镜头 1 提示词')).toBeNull();
    await act(async () => { finish(); });
    chooseShot(1);
    expect(screen.getByLabelText('镜头 1 提示词').value).toBe('完整视频提示词');
    expect(screen.queryByTestId('streaming-message-bubble')).toBeNull();
    expect(screen.queryByRole('button', { name: '采用分镜方案' })).toBeNull();
  });
  it('keeps failed tools between independent model rounds until completion', async () => {
    let emit, finish;
    api.sendStoryboardMessage.mockImplementation((_w, _c, _body, _signal, onEvent) => new Promise(resolve => { emit = onEvent; finish = () => resolve(complete()); }));
    open(); await ready(); send(); await waitFor(() => expect(emit).toBeTruthy());
    await act(async () => {
      emit('message_updated', stored('a1', 'assistant', '第一轮说明', { reasoning: '第一轮思考', sort_order: 1 }));
      emit('message_updated', stored('t1', 'tool_call', '', { tool_name: 'replace_storyboard', tool_call_id: 'bad', status: 'failed', arguments: '{"shots":[]}', sort_order: 2 }));
      emit('message_updated', stored('r1', 'tool_result', '行号超出范围', { tool_call_id: 'bad', status: 'failed', sort_order: 3 }));
      emit('stage_start', { label: '正在修正工具参数' });
      emit('message_updated', stored('a2', 'assistant', '', { status: 'running', sort_order: 4 }));
      emit('storyboard_stream', { message_id: 'a2', phase: 'reasoning', chunk: '第二轮思考' });
    });
    expect(screen.getByText('第一轮说明')).toBeTruthy();
    expect(screen.getByText('第二轮思考')).toBeTruthy();
    fireEvent.click(screen.getByText('工具调用 · replace_storyboard'));
    expect(screen.getByText(/行号超出范围/)).toBeTruthy();
    await act(async () => { finish(); }); await screen.findByText('已生成分镜');
  });
  it('unlocks sending after saved results even if session list refresh is still pending', async () => {
    api.sendStoryboardMessage.mockImplementation(async () => { api.listDramaSessions.mockImplementation(() => new Promise(() => {})); return complete(); });
    open(); await ready(); send(); await screen.findByText('已生成分镜');
    fireEvent.change(screen.getByLabelText('对话输入'), { target: { value: '继续修改' } });
    expect(screen.getByRole('button', { name: '发送给 Agent' }).disabled).toBe(false);
  });
  it('shows saved boards immediately and retains shared tool rows during later model rounds', async () => {
    let emit, finish;
    api.sendStoryboardMessage.mockImplementation((_w, _c, _body, _signal, onEvent) => new Promise(resolve => { emit = onEvent; finish = () => resolve(complete('两批均已完成', board.shots)); }));
    open(); await ready(); send(); await waitFor(() => expect(emit).toBeTruthy());
    await act(async () => {
      emit('message_updated', stored('t1', 'tool_call', '', { tool_name: 'replace_storyboard', tool_call_id: 'batch1', status: 'done', sort_order: 1 }));
      board = { ...board, shots: [shot()], revision: 1, activeSessionId: 'session-1' };
      emit('storyboard_updated', { workspace: copy(board) });
      emit('stage_start', { label: '正在继续处理' });
      emit('message_updated', stored('a2', 'assistant', '', { status: 'running', sort_order: 2 }));
    });
    chooseShot(1);
    expect(screen.getByLabelText('镜头 1 提示词').value).toBe('完整视频提示词');
    expect(screen.getByText('工具调用 · replace_storyboard')).toBeTruthy();
    expect(screen.getByRole('button', { name: '发送给 Agent' }).disabled).toBe(true);
    await act(async () => {
      emit('message_updated', stored('t2', 'tool_call', '', { tool_name: 'update_shots', tool_call_id: 'batch2', status: 'done', sort_order: 3 }));
      board = { ...board, shots: [shot('s1', 7)], revision: 2 };
      emit('storyboard_updated', { workspace: copy(board) });
    });
    expect(screen.getByLabelText('全章分镜总时长').textContent).toContain('7 秒');
    expect(screen.getByText('工具调用 · replace_storyboard')).toBeTruthy();
    expect(screen.getByText('工具调用 · update_shots')).toBeTruthy();
    await act(async () => { finish(); }); expect(await screen.findByText('两批均已完成')).toBeTruthy();
  });
  it('clears the composer as soon as the message is sent', async () => {
    let finish; api.sendStoryboardMessage.mockImplementation(() => new Promise(resolve => { finish = () => resolve(complete()); }));
    open(); await ready(); send();
    expect(screen.getByLabelText('对话输入').value).toBe('');
    await waitFor(() => expect(finish).toBeTypeOf('function'));
    await act(async () => { finish(); });
    expect(await screen.findByText('已生成分镜')).toBeTruthy();
    expect(screen.getByLabelText('对话输入').value).toBe('');
  });
  it('preserves input and saved shots when streaming fails', async () => {
    board.shots = [shot()]; api.sendStoryboardMessage.mockRejectedValue(new Error('模型错误')); open(); await ready(); send('只修改本镜');
    chooseShot(1);
    expect(await screen.findByRole('alert')).toHaveProperty('textContent', '模型错误'); expect(screen.getByLabelText('对话输入').value).toBe('只修改本镜'); expect(screen.getByLabelText('镜头 1 提示词').value).toBe('完整视频提示词');
  });
  it('reports server saving failures without claiming a successful save', async () => {
    api.saveDramaWorkspace.mockRejectedValue(new Error('保存失败')); open(); await ready(); fireEvent.click(screen.getByRole('button', { name: '添加分镜' })); await screen.findByRole('alert'); expect(screen.getByText('未保存')).toBeTruthy(); expect(screen.queryByText('已保存')).toBeNull();
  });
  it('hides all source-location actions even when an old shot has a saved source range', async () => {
    board.shots = [{ ...shot('old'), sourceQuote: chapter.content, sourceStartLine: 1, sourceEndLine: 9 }];
    open(); await ready();
    chooseShot(1);
    expect(screen.queryByRole('button', { name: /已关联原文/ })).toBeNull();
    expect(screen.queryByRole('button', { name: '关联当前镜头' })).toBeNull();
    expect(screen.getByRole('button', { name: '引用原文第 1 行' })).toBeTruthy();
    expect(screen.getByLabelText('镜头 1 提示词').value).toBe('完整视频提示词');
  });
  it('shows reconstructed shots without requiring or displaying an original-text link', async () => {
    board.shots = [{ ...shot('reconstructed'), prompt: '先以信封和人物反应建立冲突，再用简短对白交代来意。', sourceQuote: '', sourceStartLine: null, sourceEndLine: null }];
    open(); await ready();
    chooseShot(1);
    expect(screen.getByLabelText('镜头 1 提示词').value).toBe('先以信封和人物反应建立冲突，再用简短对白交代来意。');
    expect(screen.queryByRole('button', { name: /已关联原文/ })).toBeNull();
    expect(screen.getByRole('button', { name: '生成预览视频' }).disabled).toBe(false);
    expect(screen.getByRole('button', { name: '展开编辑镜头 1 提示词' })).toBeTruthy();
  });
  it('expands the complete video prompt and keeps edits synchronized with the card and saved board', async () => {
    const fullPrompt = 'summary:\n完整概述\n\ndetailed_description:\n' + '画面、动作和运镜细节。'.repeat(3000);
    board.shots = [{ ...shot('s1'), prompt: fullPrompt }];
    open(); await ready();
    chooseShot(1);
    const inline = screen.getByLabelText('镜头 1 提示词');
    expect(inline.rows).toBe(12);
    const trigger = screen.getByRole('button', { name: '展开编辑镜头 1 提示词' });
    trigger.focus(); fireEvent.click(trigger);
    const dialog = screen.getByRole('dialog', { name: '镜头 1 · 视频提示词' });
    const expanded = within(dialog).getByLabelText('完整视频提示词');
    expect(expanded.value).toBe(fullPrompt);
    expect(document.activeElement).toBe(expanded);
    const edited = fullPrompt + '\n结尾：人物停在门口。';
    fireEvent.change(expanded, { target: { value: edited } });
    expect(inline.value).toBe(edited);
    await waitFor(() => expect(board.shots[0].prompt).toBe(edited));
    fireEvent.click(within(dialog).getByRole('button', { name: '完成' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(document.activeElement).toBe(trigger);
    expect(inline.value).toBe(edited);
  });
  it('uses the same expanded editor on mobile and closes with Escape without losing edits', async () => {
    board.shots = [shot('s1')]; open(); await ready(); setMobile(true);
    fireEvent.click(screen.getByRole('button', { name: '分镜', exact: true }));
    chooseShot(1);
    fireEvent.click(screen.getByRole('button', { name: '展开编辑镜头 1 提示词' }));
    const dialog = screen.getByRole('dialog', { name: '镜头 1 · 视频提示词' });
    fireEvent.change(within(dialog).getByLabelText('完整视频提示词'), { target: { value: '手机修改\n完整保留换行' } });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(screen.getByLabelText('镜头 1 提示词').value).toBe('手机修改\n完整保留换行');
    await waitFor(() => expect(board.shots[0].prompt).toBe('手机修改\n完整保留换行'));
  });
  it('submits preview and final separately without changing the chapter frame size', async () => {
    board.shots = [shot('first'), shot('second')]; open(); await ready();
    chooseShot(2);
    const group = screen.getByRole('group', { name: '镜头 2 操作区' });
    fireEvent.click(within(group).getByRole('button', { name: '生成预览视频' }));
    await waitFor(() => expect(api.generateDramaVideos).toHaveBeenLastCalledWith('work-1', 'chapter-1', ['second'], 'preview'));
    await waitFor(() => expect(within(group).getByRole('button', { name: '生成最终视频' }).disabled).toBe(false));
    fireEvent.click(within(group).getByRole('button', { name: '生成最终视频' }));
    await waitFor(() => expect(api.generateDramaVideos).toHaveBeenLastCalledWith('work-1', 'chapter-1', ['second'], 'final'));
    expect(screen.queryByRole('dialog', { name: '任务队列' })).toBeNull();
    expect(screen.queryByRole('button', { name: '预览生成全部镜头' })).toBeNull();
    expect(screen.queryByRole('button', { name: '最终生成全部镜头' })).toBeNull();
    expect(board.width).toBe(960); expect(board.height).toBe(544);
    expect(screen.queryByLabelText('画面宽度')).toBeNull();
  });
  it('restores the quality and resolution of saved videos and opens the chosen result', async () => {
    board.shots = [shot('s1')];
    api.listDramaVideos.mockResolvedValue([
      { id: 'preview-1', shot_id: 's1', title: '推门', status: 'succeeded', quality: 'preview', width: 480, height: 272, fps: 24 },
      { id: 'final-1', shot_id: 's1', title: '推门', status: 'succeeded', quality: 'final', width: 960, height: 544, fps: 24 },
    ]);
    const previousCreate = URL.createObjectURL, previousRevoke = URL.revokeObjectURL;
    URL.createObjectURL = () => 'blob:quality-result'; URL.revokeObjectURL = () => {};
    try {
      api.fetchDramaVideo.mockResolvedValue(new Blob(['video']));
      open(); await ready();
      chooseShot(1);
      const monitor = document.querySelector('.drama-monitor');
      expect(within(monitor).getByText('预览视频', { exact: true })).toBeTruthy();
      expect(within(monitor).getByText('最终视频', { exact: true })).toBeTruthy();
      const paused = await waitFor(() => {
        expect(api.fetchDramaVideo).toHaveBeenCalledWith('work-1', 'chapter-1', 'preview-1');
        const video = document.querySelector('.drama-monitor video');
        expect(video?.getAttribute('src')).toBe('blob:quality-result');
        return video;
      });
      expect(paused.hasAttribute('autoplay')).toBe(false);
    } finally { cleanup(); URL.createObjectURL = previousCreate; URL.revokeObjectURL = previousRevoke; }
  });
  it('shows the monitor timecode and disables a quality switch that has no finished video', async () => {
    board.shots = [shot('s1'), shot('s2'), shot('s3')];
    api.listDramaVideos.mockResolvedValue([
      { id: 'preview-only', shot_id: 's1', title: '推门', status: 'succeeded', quality: 'preview' },
      { id: 'preview-failed', shot_id: 's2', title: '推门', status: 'failed', quality: 'preview' },
      { id: 'final-only', shot_id: 's2', title: '推门', status: 'succeeded', quality: 'final' },
      { id: 'both-preview', shot_id: 's3', title: '推门', status: 'succeeded', quality: 'preview' },
      { id: 'both-final', shot_id: 's3', title: '推门', status: 'succeeded', quality: 'final' },
    ]);
    open(); await ready();
    expect(document.querySelector('.drama-tc').textContent).toBe('00:00 / 00:05');
    chooseShot(1);
    expect(screen.getByRole('button', { name: '预览' }).disabled).toBe(false);
    expect(screen.getByRole('button', { name: '最终' }).disabled).toBe(true);
    chooseShot(2);
    expect(screen.getByRole('button', { name: '预览' }).disabled).toBe(true);
    expect(screen.getByRole('button', { name: '最终' }).disabled).toBe(false);
    expect(screen.getByRole('button', { name: '最终' }).getAttribute('aria-pressed')).toBe('true');
    chooseShot(3);
    expect(screen.getByRole('button', { name: '预览' }).disabled).toBe(false);
    expect(screen.getByRole('button', { name: '最终' }).disabled).toBe(false);
  });
  it('lists finished videos in the bottom strip and drops a video when it is deleted', async () => {
    board.shots = [shot('s1', 9), shot('s2', 8)];
    api.listDramaVideos.mockResolvedValue([
      { id: 'final-1', shot_id: 's1', status: 'succeeded', quality: 'final', duration: 4 },
      { id: 'preview-1', shot_id: 's1', status: 'succeeded', quality: 'preview', duration: 6 },
      { id: 'running-1', shot_id: 's2', status: 'running', quality: 'final', duration: 8 },
    ]);
    api.deleteDramaVideo.mockResolvedValue(null);
    api.fetchDramaVideo.mockResolvedValue(new Blob(['mp4']));
    api.fetchDramaPoster.mockResolvedValue(new Blob(['frame'], { type: 'image/jpeg' }));
    const previousCreate = URL.createObjectURL, previousRevoke = URL.revokeObjectURL;
    URL.createObjectURL = () => 'blob:shot-frame'; URL.revokeObjectURL = () => {};
    try {
      open(); await ready();
      expect(screen.queryByRole('button', { name: '播放镜头 2 的最终视频' })).toBeNull();
      expect(screen.getByLabelText('成片总时长').textContent).toBe('00:10');
      expect(screen.getByRole('button', { name: '播放镜头 1 的最终视频' }).textContent).toContain('4s');
      expect(screen.getByRole('button', { name: '播放镜头 1 的预览视频' }).textContent).toContain('6s');
      fireEvent.click(screen.getByRole('button', { name: '收起本章视频' }));
      expect(document.querySelector('.drama-filmstrip .drama-tiles').hidden).toBe(true);
      expect(screen.queryByRole('button', { name: '播放镜头 1 的最终视频' })).toBeNull();
      fireEvent.click(screen.getByRole('button', { name: '展开本章视频' }));
      await waitFor(() => expect(api.fetchDramaPoster).toHaveBeenCalledWith('work-1', 'chapter-1', 'final-1'));
      expect(api.fetchDramaPoster).toHaveBeenCalledWith('work-1', 'chapter-1', 'preview-1');
      fireEvent.click(screen.getByRole('button', { name: '最终', exact: true }));
      fireEvent.click(screen.getByRole('button', { name: '删除最终视频' }));
      await waitFor(() => expect(screen.queryByRole('button', { name: '播放镜头 1 的最终视频' })).toBeNull());
      expect(screen.getByRole('button', { name: '播放镜头 1 的预览视频' }).textContent).toContain('6s');
      expect(screen.getByLabelText('成片总时长').textContent).toBe('00:06');
      expect(screen.getByLabelText('全章分镜总时长').textContent).toContain('17 秒');
    } finally { cleanup(); URL.createObjectURL = previousCreate; URL.revokeObjectURL = previousRevoke; }
  });
  it('submits one shot through the video buttons', async () => {
    board.shots = [shot('first'), shot('second')]; open(); await ready();
    chooseShot(2);
    fireEvent.click(within(screen.getByRole('group', { name: '镜头 2 操作区' })).getByRole('button', { name: '生成最终视频' }));
    await waitFor(() => expect(api.generateDramaVideos).toHaveBeenCalledWith('work-1', 'chapter-1', ['second'], 'final'));
    expect(screen.queryByRole('dialog', { name: '任务队列' })).toBeNull();
    expect(screen.queryByRole('button', { name: '最终生成全部镜头' })).toBeNull();
  });
  it('reads chapter and role names from title', async () => {
    const previousCreate = URL.createObjectURL;
    const previousRevoke = URL.revokeObjectURL;
    URL.createObjectURL = () => 'blob:portrait';
    URL.revokeObjectURL = () => {};
    try {
    board.shots = [shot()];
    open(); await ready();
    chooseShot(1);
    expect(screen.getByText('未关联角色')).toBeTruthy();
    const editor = screen.getByText('编辑出场角色').closest('details');
    expect(editor.open).toBe(false);
    editor.open = true;
    expect(screen.getByRole('checkbox', { name: '镜头 1 关联角色 林雨' })).toBeTruthy();
    fireEvent.click(screen.getByRole('checkbox', { name: '镜头 1 关联角色 林雨' }));
    expect(document.querySelector('.drama-role-tag').textContent).toBe('林林雨');
    expect(screen.queryByRole('button', { name: '角色立绘' })).toBeNull();
    fireEvent.click(screen.getByRole('tab', { name: /立绘设计/ }));
    expect(await screen.findByRole('heading', { name: '林雨' })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '为林雨添加立绘' }));
    expect(screen.queryByLabelText(/图片路径/)).toBeNull();
    expect(screen.queryByText('黑色长发，蓝色棉布上衣。')).toBeNull();
    fireEvent.change(screen.getByLabelText('林雨立绘 1 提示词'), { target: { value: '蓝色棉布上衣' } });
    fireEvent.click(screen.getByRole('button', { name: '为林雨添加立绘' }));
    expect(screen.getByLabelText('林雨立绘 2 提示词')).toBeTruthy();
    await waitFor(() => expect(api.saveDramaPortraits).toHaveBeenCalled());
    expect(api.fetchPortraitFile).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('tab', { name: /分镜设计/ }));
    const shotEditor = screen.getByText('编辑出场角色').closest('details');
    shotEditor.open = true;
    expect(screen.queryByRole('radio', { name: '镜头 1 林雨 的第 1 张立绘' })).toBeNull();
    } finally {
      URL.createObjectURL = previousCreate;
      URL.revokeObjectURL = previousRevoke;
    }
  });
  it('uses selected portraits for reference video generation without a path input', async () => {
    board.shots = [{ ...shot(), inputMode: 'reference', roles: [{ roleId: 'role-1', portraitId: 'p1' }] }];
    board.portraits = [{ id: 'p1', roleId: 'role-1', imagePath: '/generated.png', prompt: '角色立绘' }];
    open(); await ready();
    chooseShot(1);
    screen.getByText('高级设置').closest('details').open = true;
    expect(screen.queryByLabelText('镜头 1 参考图路径')).toBeNull();
    expect(screen.queryByText(/远端临时参考图/)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '生成最终视频', exact: true }));
    await waitFor(() => expect(api.generateDramaVideos).toHaveBeenCalledWith('work-1', 'chapter-1', ['s1'], 'final'));
  });
  it('selects portrait images without showing prompts, paths or ungenerated drafts', async () => {
    const previousCreate = URL.createObjectURL, previousRevoke = URL.revokeObjectURL;
    URL.createObjectURL = () => 'blob:portrait-choice'; URL.revokeObjectURL = () => {};
    try {
      board.shots = [{ ...shot(), roles: [{ roleId: 'role-1', portraitId: null }] }];
      board.portraits = [
        { id: 'ready', roleId: 'role-1', imagePath: '/local/generated.png', prompt: '完整立绘提示词，仅设计区编辑' },
        { id: 'draft', roleId: 'role-1', imagePath: '', prompt: '未生成的立绘草稿' },
      ];
      open(); await ready();
      chooseShot(1);
      screen.getByText('编辑出场角色').closest('details').open = true;
      const choices = screen.getByRole('radiogroup', { name: '镜头 1 林雨 立绘' });
      expect(await within(choices).findByAltText('林雨立绘')).toBeTruthy();
      expect(within(choices).queryByText('完整立绘提示词，仅设计区编辑')).toBeNull();
      expect(within(choices).queryByText('未生成的立绘草稿')).toBeNull();
      expect(within(choices).queryByText('/local/generated.png')).toBeNull();
      expect(within(choices).getAllByRole('radio')).toHaveLength(2);
      expect(within(choices).getByRole('radio', { name: '镜头 1 林雨 无' }).closest('label').textContent).toBe('无');
      fireEvent.click(within(choices).getByAltText('林雨立绘'));
      await waitFor(() => expect(board.shots[0].roles[0].portraitId).toBe('ready'));
      expect(within(choices).getByRole('radio', { name: '镜头 1 林雨 的第 1 张立绘' }).checked).toBe(true);
    } finally { cleanup(); URL.createObjectURL = previousCreate; URL.revokeObjectURL = previousRevoke; }
  });
  it('saves the portrait before submitting a real image job and restores running status on reload', async () => {
    board.portraits = [{ id: 'p1', roleId: 'role-1', imagePath: '', prompt: '成年女性，蓝色上衣' }];
    open(); await ready();
    fireEvent.click(screen.getByRole('tab', { name: /立绘设计/ }));
    fireEvent.change(screen.getByLabelText('林雨立绘 1 提示词'), { target: { value: '完整中文立绘' } });
    fireEvent.click(screen.getByRole('button', { name: '生成林雨立绘 1' }));
    await waitFor(() => expect(api.generateDramaPortrait).toHaveBeenCalledWith('work-1', 'p1', { width: 768, height: 1024, seed: 42 }));
    expect(board.portraits[0].prompt).toBe('完整中文立绘');
    expect(screen.getByText('已提交，等待生成')).toBeTruthy();
    expect(screen.getByRole('button', { name: '生成林雨立绘 1' }).disabled).toBe(true);
  });
  it('restores an active image job and refreshes the portrait preview when it succeeds', async () => {
    const previousCreate = URL.createObjectURL, previousRevoke = URL.revokeObjectURL;
    URL.createObjectURL = () => 'blob:generated-portrait'; URL.revokeObjectURL = () => {};
    try {
      board.shots = [shot()];
      board.portraits = [{ id: 'p1', roleId: 'role-1', imagePath: '', prompt: '完整中文立绘' }];
      api.listDramaImages.mockResolvedValue([{ id: 'active', portrait_id: 'p1', status: 'running' }]);
      open(); await ready();
      chooseShot(1);
      expect(within(screen.getByRole('group', { name: '镜头 1 操作区' })).getByRole('button', { name: '生成最终视频' }).disabled).toBe(true);
      fireEvent.click(screen.getByRole('tab', { name: /立绘设计/ }));
      expect(screen.getByText('处理中')).toBeTruthy();
      expect(screen.getByRole('button', { name: '生成林雨立绘 1' }).disabled).toBe(true);
      board.portraits[0].imagePath = '/outputs/generated.png'; board.portraitRevision += 1;
      api.listDramaImages.mockResolvedValue([{ id: 'active', portrait_id: 'p1', status: 'succeeded' }]);
      await waitFor(() => expect(screen.getByText('立绘已生成')).toBeTruthy(), { timeout: 4500 });
      expect(await screen.findByAltText('林雨立绘')).toBeTruthy();
      expect(screen.queryByLabelText(/图片路径/)).toBeNull();
      expect(api.fetchPortraitFile).toHaveBeenCalledWith('work-1', 'p1');
      expect(screen.getByRole('button', { name: '生成林雨立绘 1' }).disabled).toBe(false);
      fireEvent.click(screen.getByRole('tab', { name: /分镜设计/ }));
      chooseShot(1);
      expect(within(screen.getByRole('group', { name: '镜头 1 操作区' })).getByRole('button', { name: '生成最终视频' }).disabled).toBe(false);
    } finally { cleanup(); URL.createObjectURL = previousCreate; URL.revokeObjectURL = previousRevoke; }
  });
  it('loads persisted image errors with the portrait and allows another generation', async () => {
    board.portraits = [{ id: 'p1', roleId: 'role-1', imagePath: '', prompt: '中文立绘' }];
    api.listDramaImages.mockResolvedValue([{ id: 'old', portrait_id: 'p1', status: 'failed', error: '缺少推理环境' }]);
    open(); await ready();
    fireEvent.click(screen.getByRole('tab', { name: /立绘设计/ }));
    expect(screen.getByText('缺少推理环境')).toBeTruthy();
    expect(screen.getByRole('button', { name: '生成林雨立绘 1' }).disabled).toBe(false);
  });
  it('puts copy, move and delete in the more menu and leaves generate on the footer', async () => {
    board.shots = [{ ...shot('first'), prompt: '第一镜提示词' }, { ...shot('second'), prompt: '第二镜提示词', title: '回头' }];
    open(); await ready();
    chooseShot(1);
    expect(screen.getByRole('button', { name: '生成最终视频' })).toBeTruthy();
    chooseShot(2);
    expect(screen.getByRole('button', { name: '生成最终视频' })).toBeTruthy();
    const card = screen.getByLabelText('镜头 2 名称').closest('article');
    const details = within(card).getByText('更多').closest('details');
    details.open = true;
    fireEvent.click(within(card).getByRole('button', { name: '复制提示词' }));
    expect(details.open).toBe(false);
    details.open = true;
    fireEvent.click(within(card).getByRole('button', { name: '上移镜头 2' }));
    expect(details.open).toBe(false);
    expect(screen.getByLabelText('镜头 1 提示词').value).toBe('第二镜提示词');
    const moved = screen.getByLabelText('镜头 1 名称').closest('article');
    const movedMenu = within(moved).getByText('更多').closest('details');
    movedMenu.open = true;
    fireEvent.click(within(moved).getByRole('button', { name: '下移镜头 1' }));
    expect(movedMenu.open).toBe(false);
    expect(screen.getByLabelText('镜头 2 提示词').value).toBe('第二镜提示词');
    const again = screen.getByLabelText('镜头 2 名称').closest('article');
    const deleteMenu = within(again).getByText('更多').closest('details');
    deleteMenu.open = true;
    fireEvent.click(within(again).getByRole('button', { name: '删除镜头 2' }));
    expect(deleteMenu.open).toBe(false);
    expect(screen.queryByDisplayValue('第二镜提示词')).toBeNull();
  });
  it('does not associate a shot until the card body is clicked, and keeps a cancelled association empty', async () => {
    board.shots = [shot('first'), { ...shot('second'), title: '回头' }];
    sessions.push({ id: 'session-2', title: '对话 2', running: false }); histories['session-2'] = [];
    let emit, finish;
    api.sendStoryboardMessage.mockImplementation((_w, _c, _body, _signal, onEvent) => new Promise(resolve => {
      emit = onEvent;
      finish = () => resolve(complete('已同步', board.shots));
    }));
    open(); await ready();
    expect(document.querySelector('.drama-shot.is-selected')).toBeNull();
    expect(screen.queryByRole('button', { name: '取消关联镜头' })).toBeNull();
    chooseShot(1);
    const first = screen.getByLabelText('镜头 1 名称').closest('article');
    expect(within(first).getByText('未关联角色')).toBeTruthy();
    expect(within(first).getByText('编辑出场角色').closest('details').open).toBe(false);
    fireEvent.click(screen.getByLabelText('镜头 1 名称'));
    fireEvent.click(screen.getByLabelText('镜头 1 时长'));
    within(first).getByText('编辑出场角色').closest('details').open = true;
    fireEvent.click(screen.getByRole('checkbox', { name: '镜头 1 关联角色 林雨' }));
    within(first).getByText('更多').closest('details').open = true;
    fireEvent.click(within(first).getByText('更多'));
    expect(first.classList.contains('is-selected')).toBe(true);
    chooseShot(2);
    const second = screen.getByLabelText('镜头 2 名称').closest('article');
    expect(second.classList.contains('is-selected')).toBe(true);
    expect(screen.getByText('关联镜头 02：回头')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '取消关联镜头' }));
    expect(document.querySelector('.drama-shot.is-selected')).toBeNull();
    expect(screen.queryByRole('button', { name: '取消关联镜头' })).toBeNull();
    send('继续设计');
    await waitFor(() => expect(api.sendStoryboardMessage).toHaveBeenCalled());
    expect(api.sendStoryboardMessage.mock.calls[0][2].selected_shot_id).toBeNull();
    await act(async () => { emit('storyboard_updated', { workspace: copy(board) }); });
    expect(document.querySelector('.drama-shot.is-selected')).toBeNull();
    await act(async () => { finish(); });
    await screen.findByText('已同步');
    expect(document.querySelector('.drama-shot.is-selected')).toBeNull();
    fireEvent.change(screen.getByLabelText('分镜会话'), { target: { value: 'session-2' } });
    await waitFor(() => expect(screen.getByLabelText('分镜会话').value).toBe('session-2'));
    expect(document.querySelector('.drama-shot.is-selected')).toBeNull();
    expect(screen.queryByRole('button', { name: '取消关联镜头' })).toBeNull();
  });
  it('clears the association when the selected shot is deleted', async () => {
    board.shots = [shot('first'), { ...shot('second'), title: '回头' }];
    open(); await ready();
    chooseShot(2);
    const second = screen.getByLabelText('镜头 2 名称').closest('article');
    expect(screen.getByText('关联镜头 02：回头')).toBeTruthy();
    within(second).getByText('更多').closest('details').open = true;
    fireEvent.click(within(second).getByRole('button', { name: '删除镜头 2' }));
    expect(document.querySelector('.drama-shot.is-selected')).toBeNull();
    expect(screen.queryByRole('button', { name: '取消关联镜头' })).toBeNull();
    expect(screen.queryByDisplayValue('回头')).toBeNull();
  });
  it('resubscribes to a running session without duplicating its saved user message', async () => {
    sessions[0].running = true; sessions[0].runningChapterId = chapter.id; board.activeSessionId = 'session-1'; histories['session-1'] = [{ id: 'm1', role: 'user', content: '之前发送的设计要求' }]; api.resumeStoryboardSession.mockImplementation(() => new Promise(() => {})); open(); await ready(); await waitFor(() => expect(api.resumeStoryboardSession).toHaveBeenCalled()); expect(screen.getAllByText('之前发送的设计要求')).toHaveLength(1); expect(api.sendStoryboardMessage).not.toHaveBeenCalled();
  });
  it('uses independent sidebars and keeps a collapsed chat mounted while streaming', async () => {
    let emit, finish;
    api.sendStoryboardMessage.mockImplementation((_w, _c, _body, _signal, onEvent) => new Promise(resolve => {
      emit = onEvent;
      finish = () => resolve(complete('设计结束'));
    }));
    open(); await ready();
    expect(screen.queryByRole('heading', { name: '章节原文' })).toBeNull();
    expect(screen.queryByRole('heading', { name: '分镜设计助手' })).toBeNull();
    expect(screen.getByRole('complementary', { name: '章节原文' }).style.flexBasis).toBe('264px');
    expect(screen.getByRole('complementary', { name: '分镜设计助手' }).style.flexBasis).toBe('348px');
    fireEvent.keyDown(screen.getByRole('separator', { name: '调整章节原文宽度' }), { key: 'ArrowRight' });
    fireEvent.keyDown(screen.getByRole('separator', { name: '调整分镜设计助手宽度' }), { key: 'ArrowLeft' });
    expect(screen.getByRole('complementary', { name: '章节原文' }).style.flexBasis).toBe('284px');
    expect(screen.getByRole('complementary', { name: '分镜设计助手' }).style.flexBasis).toBe('368px');
    fireEvent.click(screen.getByRole('button', { name: '收起章节原文' }));
    expect(document.querySelector('.drama-source .workbench-sidebar__body').hidden).toBe(true);
    expect(document.querySelector('.drama-chat .workbench-sidebar__body').hidden).toBe(false);
    send();
    await waitFor(() => expect(emit).toBeTruthy());
    fireEvent.click(screen.getByRole('button', { name: '收起分镜设计助手' }));
    expect(screen.getByRole('button', { name: '本章生成设置' }).disabled).toBe(true);
    await act(async () => {
      emit('message_updated', stored('a1', 'assistant', '第一批正文', { sort_order: 1 }));
      emit('message_updated', stored('t1', 'tool_call', '', { tool_name: 'replace_storyboard', status: 'done', sort_order: 2 }));
      emit('message_updated', stored('t2', 'tool_call', '', { tool_name: 'update_shots', status: 'done', sort_order: 3 }));
    });
    const chatBody = document.querySelector('.drama-chat .workbench-sidebar__body');
    expect(chatBody.hidden).toBe(true);
    expect(chatBody.textContent).toContain('第一批正文');
    expect(chatBody.textContent).toContain('工具调用 · replace_storyboard');
    expect(chatBody.textContent).toContain('工具调用 · update_shots');
    await act(async () => { finish(); });
    expect(chatBody.textContent).toContain('设计结束');
    fireEvent.click(screen.getByRole('button', { name: '展开分镜设计助手' }));
    fireEvent.change(screen.getByLabelText('对话输入'), { target: { value: '继续' } });
    expect(screen.getByRole('button', { name: '发送给 Agent' }).disabled).toBe(false);
  });
  it('expands the assistant when quoting and keeps source reading independent of shots', async () => {
    board.shots = [shot()];
    open(); await ready();
    fireEvent.click(screen.getByRole('button', { name: '收起分镜设计助手' }));
    fireEvent.click(screen.getByRole('button', { name: '引用原文第 1 行' }));
    expect(document.querySelector('.drama-chat .workbench-sidebar__body').hidden).toBe(false);
    expect(screen.getByRole('button', { name: '设计助手' }).getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByLabelText('对话输入').value).toContain('【原文第 1 行】');
    expect(screen.getByLabelText('对话输入').value).toContain('雨水打在门上。');
    fireEvent.click(screen.getByRole('button', { name: '收起章节原文' }));
    fireEvent.click(screen.getByRole('button', { name: '展开章节原文' }));
    fireEvent.click(screen.getByRole('button', { name: '章节原文', exact: true }));
    expect(document.querySelector('.drama-source .workbench-sidebar__body').hidden).toBe(false);
    expect(screen.getByRole('button', { name: '章节原文' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(screen.getByRole('button', { name: '收起章节原文' }));
    expect(document.querySelector('.drama-source .workbench-sidebar__body').hidden).toBe(true);
    setMobile(true);
    expect(document.querySelector('.drama-source .workbench-sidebar__body').hidden).toBe(false);
    expect(document.querySelector('.drama-chat').classList.contains('drama-mobile-inactive')).toBe(true);
    expect(document.querySelector('.drama-chat').textContent).toContain('【原文第 1 行】');
    fireEvent.click(screen.getByRole('button', { name: '分镜' }));
    chooseShot(1);
    expect(document.querySelector('.drama-shots').classList.contains('drama-mobile-inactive')).toBe(false);
    expect(document.querySelector('.drama-source').classList.contains('drama-mobile-inactive')).toBe(true);
    expect(screen.getByLabelText('镜头 1 提示词')).toBeTruthy();
  });
  it('saves a valid frame size, blocks video actions while the size is invalid, and keeps visual style', async () => {
    board.shots = [shot()];
    open(); await ready();
    chooseShot(1);
    fireEvent.click(screen.getByRole('button', { name: '本章生成设置' }));
    expect(screen.getByLabelText('画面宽度').value).toBe('960');
    expect(screen.getByLabelText('画面高度').value).toBe('544');
    expect(screen.getAllByText('24fps').length).toBeGreaterThan(0);
    fireEvent.change(screen.getByLabelText('画面宽度'), { target: { value: '' } });
    fireEvent.blur(screen.getByLabelText('画面宽度'));
    expect(screen.getByLabelText('画面宽度').value).toBe('');
    expect(screen.getByText('宽和高须为 256 到 1280 之间的 16 倍数')).toBeTruthy();
    expect(within(screen.getByRole('group', { name: '镜头 1 操作区' })).getByRole('button', { name: '生成最终视频' }).disabled).toBe(true);
    await new Promise(resolve => setTimeout(resolve, 700));
    expect(api.saveDramaWorkspace).not.toHaveBeenCalled();
    expect(board.width).toBe(960);
    fireEvent.click(screen.getByRole('button', { name: '544×960' }));
    expect(screen.getByLabelText('画面宽度').value).toBe('544');
    expect(screen.getByLabelText('画面高度').value).toBe('960');
    expect(screen.queryByText('宽和高须为 256 到 1280 之间的 16 倍数')).toBeNull();
    await waitFor(() => expect(board.width).toBe(544), { timeout: 2000 });
    expect(board.height).toBe(960);
    fireEvent.change(screen.getByLabelText('画面宽度'), { target: { value: '1280' } });
    fireEvent.change(screen.getByLabelText('画面高度'), { target: { value: '720' } });
    fireEvent.blur(screen.getByLabelText('画面高度'));
    await waitFor(() => expect(board.width).toBe(1280), { timeout: 2000 });
    expect(board.height).toBe(720);
    fireEvent.change(screen.getByLabelText('画面高度'), { target: { value: '255' } });
    fireEvent.blur(screen.getByLabelText('画面高度'));
    expect(screen.getByLabelText('画面高度').value).toBe('255');
    expect(within(screen.getByRole('group', { name: '镜头 1 操作区' })).getByRole('button', { name: '生成最终视频' }).disabled).toBe(true);
    await new Promise(resolve => setTimeout(resolve, 700));
    expect(board.height).toBe(720);
    expect(screen.queryByLabelText('本章画幅')).toBeNull();
    expect(screen.getByPlaceholderText('例如：电影写实风格，自然光，克制的镜头运动。')).toBeTruthy();
  });
  it('disables frame editing while a session is generating', async () => {
    board.activeSessionId = 'session-1';
    open(); await ready();
    expect(screen.getByRole('button', { name: '本章生成设置' }).disabled).toBe(true);
    expect(screen.queryByLabelText('画面宽度')).toBeNull();
  });
  it('keeps chapter duration clear and frame timing in advanced settings', async () => {
    board.shots = [shot('a', 5), { ...shot('b', 7), title: '回头' }];
    open(); await ready();
    const total = screen.getByLabelText('全章分镜总时长').textContent;
    expect(total).toContain('12 秒');
    expect(total).not.toContain('12.459');
    chooseShot(1);
    expect(screen.getByLabelText('镜头 1 时长').closest('article').textContent).toContain('124 帧 · 24fps · 预计 5.17 秒');
    chooseShot(2);
    expect(screen.getByLabelText('镜头 2 时长').closest('article').textContent).toContain('175 帧 · 24fps · 预计 7.29 秒');
    expect(screen.queryByLabelText('帧率')).toBeNull();
    expect(screen.queryByText(/SSH/)).toBeNull();
  });
  it('deletes the playing video and leaves the other quality in place', async () => {
    board.shots = [shot('s1'), shot('s2')];
    api.listDramaVideos.mockResolvedValue([
      { id: 'final-1', shot_id: 's1', title: '推门', status: 'succeeded', quality: 'final' },
      { id: 'preview-1', shot_id: 's1', title: '推门', status: 'succeeded', quality: 'preview' },
      { id: 'running-1', shot_id: 's2', title: '推门', status: 'running', quality: 'final' },
    ]);
    api.deleteDramaVideo.mockResolvedValue(null);
    api.fetchDramaVideo.mockResolvedValue(new Blob(['mp4']));
    const previousCreate = URL.createObjectURL, previousRevoke = URL.revokeObjectURL;
    URL.createObjectURL = () => 'blob:delete-video'; URL.revokeObjectURL = () => {};
    try {
      open(); await ready();
      chooseShot(2);
      expect(screen.queryByRole('button', { name: '删除最终视频' })).toBeNull();
      chooseShot(1);
      fireEvent.click(screen.getByRole('button', { name: '最终', exact: true }));
      fireEvent.click(screen.getByRole('button', { name: '删除最终视频' }));
      await waitFor(() => expect(api.deleteDramaVideo).toHaveBeenCalledWith('work-1', 'chapter-1', 'final-1'));
      await waitFor(() => expect(screen.queryByRole('button', { name: '删除最终视频' })).toBeNull());
      expect(screen.getByRole('button', { name: '删除预览视频' })).toBeTruthy();
      expect(api.deleteDramaVideo).toHaveBeenCalledTimes(1);
    } finally { cleanup(); URL.createObjectURL = previousCreate; URL.revokeObjectURL = previousRevoke; }
  });
  it('plays a succeeded shot video in the monitor', async () => {
    board.shots = [shot('s1'), shot('s2')];
    api.listDramaVideos.mockResolvedValue([
      { id: 'job-1', shot_id: 's1', title: '推门', status: 'succeeded', error: '', quality: 'final', width: 960, height: 544, fps: 24 },
      { id: 'job-2', shot_id: 's2', title: '推门', status: 'running', error: '', quality: 'final', width: 960, height: 544, fps: 24 },
    ]);
    api.fetchDramaVideo.mockResolvedValue(new Blob(['mp4']));
    const previousCreate = URL.createObjectURL;
    const previousRevoke = URL.revokeObjectURL;
    URL.createObjectURL = () => 'blob:shot-video';
    URL.revokeObjectURL = () => {};
    try {
      open(); await ready();
      chooseShot(2);
      expect(screen.getByText('处理中')).toBeTruthy();
      expect(screen.queryByRole('button', { name: '查看最终视频' })).toBeNull();
      chooseShot(1);
      expect(screen.getByText('已完成')).toBeTruthy();
      const paused = await waitFor(() => {
        expect(api.fetchDramaVideo).toHaveBeenCalledWith('work-1', 'chapter-1', 'job-1');
        const video = document.querySelector('.drama-monitor video');
        expect(video?.getAttribute('src')).toBe('blob:shot-video');
        return video;
      });
      expect(paused.hasAttribute('autoplay')).toBe(false);
      let seen = 0;
      Object.defineProperty(paused, 'currentTime', { configurable: true, get() { return seen; }, set(value) { seen = value; } });
      fireEvent.loadedData(paused);
      expect(paused.currentTime).toBe(0.001);
      expect(screen.queryByRole('dialog', { name: '任务队列' })).toBeNull();
    } finally {
      URL.createObjectURL = previousCreate;
      URL.revokeObjectURL = previousRevoke;
    }
  });
  it('returns from a shot and then leaves the storyboard on the system back button', async () => {
    board.shots = [shot()];
    render(<MemoryRouter initialEntries={['/short-drama/work-1/chapter-1']}><Routes>
      <Route path='/short-drama/:workId/:chapterId' element={<ShortDramaPage appMode />} />
      <Route path='/' element={<div>小说画布</div>} />
    </Routes></MemoryRouter>);
    await screen.findByText('第一章 雨夜');
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: '选择镜头 1' }));
    expect(document.querySelector('.drama-page').getAttribute('data-screen')).toBe('detail');
    await act(async () => {});
    const onDetail = backNavigationMocks.listener;
    await act(async () => { onDetail(); });
    await waitFor(() => expect(document.querySelector('.drama-page').getAttribute('data-screen')).toBe('shots'));
    await act(async () => {});
    await act(async () => { backNavigationMocks.listener(); });
    expect(await screen.findByText('小说画布')).toBeTruthy();
  });
});
