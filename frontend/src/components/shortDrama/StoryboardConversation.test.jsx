import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { StoryboardConversation } from './StoryboardConversation';

afterEach(() => vi.useRealTimers());

describe('storyboard progress and navigation', () => {
  it('uses supervisor thinking steps with a spinner and checkmark instead of stage text or wait counters', () => {
    vi.useFakeTimers();
    const view = render(<StoryboardConversation messages={[]} sending inFlightMessage='设计分镜' live={{ stage: '正在设计分镜', detail: '旧校验详情', updatedAt: Date.now() }} />);
    expect(screen.getByText('AI 思考中')).toBeTruthy();
    expect(view.container.querySelector('.animate-spin')).toBeTruthy();
    act(() => vi.advanceTimersByTime(12000));
    expect(screen.queryByText('正在设计分镜')).toBeNull();
    expect(screen.queryByText('旧校验详情')).toBeNull();
    expect(screen.queryByText(/距上次进度更新/)).toBeNull();
    view.rerender(<StoryboardConversation messages={[
      { id: 'a1', role: 'assistant', content: '', reasoning: '完整思考', status: 'running' },
      { id: 'p1', role: 'process', content: '正在继续任务并请求工具提交' },
    ]} sending />);
    expect(screen.getAllByText('AI 思考中')).toHaveLength(1);
    expect(screen.getByText('完整思考')).toBeTruthy();
    expect(screen.queryByText('正在继续任务并请求工具提交')).toBeNull();
    view.rerender(<StoryboardConversation messages={[{ id: 'a1', role: 'assistant', content: '已完成', reasoning: '完整思考', status: 'done' }]} sending={false} />);
    expect(screen.getByText('AI 思考中')).toBeTruthy();
    expect(view.container.querySelector('.animate-spin')).toBeNull();
    expect(view.container.querySelector('.lucide-check')).toBeTruthy();
    expect(screen.getByText('已完成')).toBeTruthy();
  });
  it('keeps the return button outside the scrolling transcript', () => {
    render(<StoryboardConversation messages={[{ id: 'm', role: 'assistant', content: '完整对话' }]} sending={false} />);
    const scroll = screen.getByTestId('storyboard-chat-scroll');
    Object.defineProperties(scroll, { scrollHeight: { value: 2000 }, clientHeight: { value: 300 }, scrollTop: { value: 0, writable: true } });
    fireEvent.scroll(scroll); fireEvent.scroll(scroll);
    const button = screen.getByRole('button', { name: '回到底部' });
    expect(scroll.contains(button)).toBe(false);
    fireEvent.click(button);
    expect(scroll.scrollTop).toBe(2000);
    expect(screen.queryByRole('button', { name: '回到底部' })).toBeNull();
  });
});

it('uses supervisor tool steps between independent assistant bubbles, including failed tool details', () => {
  const rows = [
    { id: 'a1', role: 'assistant', reasoning: '第一轮思考', content: '第一轮说明', status: 'done' },
    { id: 't1', role: 'tool_call', tool_name: 'replace_storyboard', tool_call_id: 'call1', arguments: '{"shots":[]}', status: 'failed' },
    { id: 'r1', role: 'tool_result', tool_call_id: 'call1', content: '行号超出章节范围', status: 'failed' },
    { id: 'a2', role: 'assistant', reasoning: '第二轮思考', content: '第二轮说明', status: 'done' },
  ];
  render(<StoryboardConversation messages={rows} sending={false} />);
  expect(screen.getByText('第一轮说明')).toBeTruthy();
  expect(screen.getByText('第二轮说明')).toBeTruthy();
  const tool = screen.getByText('工具调用 · replace_storyboard');
  fireEvent.click(tool);
  expect(screen.getByText(/行号超出章节范围/)).toBeTruthy();
  expect(screen.queryByRole('region', { name: '工具执行记录' })).toBeNull();
  const transcript = screen.getByTestId('storyboard-chat-scroll');
  expect(transcript.textContent.indexOf('第一轮说明')).toBeLessThan(transcript.textContent.indexOf('工具调用 · replace_storyboard'));
  expect(transcript.textContent.indexOf('工具调用 · replace_storyboard')).toBeLessThan(transcript.textContent.indexOf('第二轮说明'));
});
