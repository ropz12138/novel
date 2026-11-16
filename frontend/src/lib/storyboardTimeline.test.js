import { describe, it, expect } from 'vitest';
import { reduceStoryboardMessages, storyboardTimeline } from './storyboardTimeline';

describe('ordered storyboard conversation', () => {
  it('keeps retries in separate messages and updates one tool without changing its position', () => {
    let rows = [];
    const emit = (event, data) => { rows = reduceStoryboardMessages(rows, event, data); };
    emit('message_updated', { id: 'a1', role: 'assistant', content: '', reasoning: '', status: 'running', sort_order: 1 });
    emit('storyboard_stream', { message_id: 'a1', phase: 'reasoning', chunk: '第一轮思考' });
    emit('message_updated', { ...rows[0], status: 'done' });
    emit('message_updated', { id: 't1', role: 'tool_call', tool_call_id: 'call1', tool_name: 'replace_storyboard', arguments: '', status: 'running', sort_order: 2 });
    emit('storyboard_stream', { message_id: 't1', phase: 'tool_args', chunk: '{"shots":[' });
    emit('message_updated', { ...rows[1], status: 'failed' });
    emit('message_updated', { id: 'r1', role: 'tool_result', tool_call_id: 'call1', content: '行号错误', status: 'failed', sort_order: 3 });
    emit('message_updated', { id: 'a2', role: 'assistant', reasoning: '', content: '', status: 'running', sort_order: 4 });
    emit('storyboard_stream', { message_id: 'a2', phase: 'reasoning', chunk: '第二轮思考' });
    expect(rows[0].reasoning).toBe('第一轮思考');
    expect(rows.at(-1).reasoning).toBe('第二轮思考');
    const { timeline, assistantReasoningDraft } = storyboardTimeline(rows, {});
    expect(timeline.map(item => item.kind)).toEqual(['step', 'message', 'step', 'step', 'draft']);
    expect(timeline[2]).toMatchObject({ status: 'failed', label: '工具调用 · replace_storyboard' });
    expect(timeline[2].stream).toContain('行号错误');
    expect(assistantReasoningDraft).toBe('第二轮思考');
    // Reloading uses the same rows and produces the same chronological display.
    expect(storyboardTimeline(JSON.parse(JSON.stringify(rows)), {})).toEqual(storyboardTimeline(rows, {}));
    emit('message_updated', { ...rows[0], reasoning: '服务端完整第一轮思考' });
    expect(rows.map(row => row.id)).toEqual(['a1', 't1', 'r1', 'a2']);
  });
});

it('streams finish_turn text into its own assistant bubble and retains the complete tool arguments', () => {
  const rows = [
    { id: 'a', llm_call_id: 'a', role: 'assistant', content: '', reasoning: '本轮思考', status: 'done', sort_order: 1 },
    { id: 't', llm_call_id: 'a', role: 'tool_call', tool_name: 'finish_turn', tool_call_id: 'finish', arguments: '{"message":"**已完成**', status: 'running', sort_order: 2 },
  ];
  const view = storyboardTimeline(rows, {});
  expect(view.timeline[1].kind).toBe('draft');
  expect(view.assistantDraft).toBe('**已完成**');
  expect(view.assistantReasoningDraft).toBe('本轮思考');
  expect(view.timeline).toHaveLength(2);
  expect(rows[1].arguments).toBe('{"message":"**已完成**');
});


it('shows the saved final reply without internal finish or saving steps after reload', () => {
  const rows = [
    { id: 'a', role: 'assistant', content: '完成', reasoning: '汇总思考', status: 'done' },
    { id: 't', role: 'tool_call', tool_name: 'finish_turn', tool_call_id: 'finish', arguments: '{"message":"完成"}', status: 'done' },
    { id: 'r', role: 'tool_result', tool_call_id: 'finish', content: '{"success":true}' },
    { id: 'p', role: 'process', content: '正在保存本轮对话' },
  ];
  expect(storyboardTimeline(JSON.parse(JSON.stringify(rows)), {}).timeline).toEqual([
    { kind: 'step', id: 'thinking-a', label: 'AI 思考中', status: 'done' },
    { kind: 'message', id: 'a', role: 'assistant', content: '完成', reasoningContent: '汇总思考', type: undefined },
  ]);
  expect(rows).toHaveLength(4);
});


it('keeps thinking stages with their own model round and ends the spinner on content or tools', () => {
  const first = { id: 'a1', role: 'assistant', content: '', reasoning: '第一轮思考', status: 'running' };
  let view = storyboardTimeline([first], {});
  expect(view.timeline[0]).toMatchObject({ kind: 'step', label: 'AI 思考中', status: 'running' });
  view = storyboardTimeline([{ ...first, content: '开始回答' }], {});
  expect(view.timeline[0].status).toBe('done');
  const rows = [{ ...first, status: 'done' },
    { id: 't1', role: 'tool_call', tool_name: 'update_shots', tool_call_id: 'call', arguments: '{}', status: 'running' },
    { id: 'p', role: 'process', content: '工具校验未通过，正在修正' },
    { id: 'a2', role: 'assistant', content: '', reasoning: '', status: 'running' }];
  view = storyboardTimeline(rows, {});
  expect(view.timeline.filter(item => item.label === 'AI 思考中').map(item => item.status)).toEqual(['done', 'running']);
  expect(view.timeline.some(item => item.label === '工具校验未通过，正在修正')).toBe(false);
});
