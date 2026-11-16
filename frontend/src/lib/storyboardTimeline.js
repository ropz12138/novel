import { previewStoryboardArguments } from './shortDrama';

/** 实时与历史使用同一批有序消息，ID 来自数据库。 */
export function reduceStoryboardMessages(rows, event, data) {
  if (event === 'message_updated') {
    const index = rows.findIndex(row => row.id === data.id);
    const next = index < 0 ? [...rows, data] : rows.map(row => row.id === data.id ? data : row);
    return next.sort((a, b) => a.sort_order - b.sort_order);
  }
  if (event !== 'storyboard_stream') return rows;
  const field = { reasoning: 'reasoning', content: 'content', tool_args: 'arguments' }[data.phase];
  return rows.map(row => row.id === data.message_id ? { ...row, [field]: row[field] + data.chunk } : row);
}

export function storyboardTimeline(rows, opened) {
  const results = new Map(rows.filter(row => row.role === 'tool_result').map(row => [row.tool_call_id, row]));
  const finishing = new Map(rows.filter(row => row.role === 'tool_call' && row.tool_name === 'finish_turn' && row.status === 'running').map(row => [row.llm_call_id, row]));
  let assistantDraft = '', assistantReasoningDraft = '';
  const timeline = [];
  for (const row of rows) {
    if (row.role === 'tool_result' || row.role === 'process') continue;
    if (row.role === 'tool_call' && row.tool_name === 'finish_turn') continue;
    if (row.role === 'assistant') {
      timeline.push({ kind: 'step', id: `thinking-${row.id}`, label: 'AI 思考中',
        status: row.status === 'running' && !row.content ? 'running' : row.status === 'failed' ? 'failed' : 'done' });
    }
    if (row.role === 'tool_call') {
      const result = results.get(row.tool_call_id);
      timeline.push({ kind: 'step', id: row.id, label: `工具调用 · ${row.tool_name}`, status: row.status,
        stream: `参数：\n${row.arguments}${result ? `\n\n结果：\n${result.content}` : ''}`, panelOpen: Boolean(opened[row.id]) });
    } else if (row.role === 'assistant' && (row.status === 'running' || finishing.has(row.id))) {
      timeline.push({ kind: 'draft', id: row.id });
      assistantDraft = row.content || previewStoryboardArguments(finishing.get(row.id)?.arguments).message;
      assistantReasoningDraft = row.reasoning;
    } else if (row.content || row.reasoning) {
      timeline.push({ kind: 'message', id: row.id, role: row.role, content: row.content,
        reasoningContent: row.reasoning, type: row.role === 'error' ? 'error' : undefined });
    }
  }
  return { timeline, assistantDraft, assistantReasoningDraft };
}
