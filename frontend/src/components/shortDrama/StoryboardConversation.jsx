import { useEffect, useRef, useState } from 'react';
import { ChatTimeline } from '../supervisor/ChatTimeline';
import { useSmartScroll } from '../../hooks/useSmartScroll';
import { storyboardTimeline } from '../../lib/storyboardTimeline';

export function StoryboardConversation({
  messages,
  sending,
  inFlightMessage,
  chatError,
}) {
  const scrollRef = useRef(null);
  const [opened, setOpened] = useState({});
  const { timeline, assistantDraft, assistantReasoningDraft } = storyboardTimeline(messages || [], opened);
  if (sending && inFlightMessage) timeline.push({ kind: 'message', id: 'pending-user', role: 'user', content: inFlightMessage });
  if (sending && (inFlightMessage || !messages?.length || messages.at(-1).role === 'user')) {
    timeline.push({ kind: 'step', id: 'pending-thinking', label: 'AI 思考中', status: 'running' });
  }

  const { stickToBottom, scrollToBottom } = useSmartScroll(scrollRef, [
    timeline, assistantDraft, assistantReasoningDraft, sending, chatError,
  ]);
  useEffect(() => {
    if (sending) scrollToBottom();
  }, [sending, scrollToBottom]);

  const idle = !messages?.length && !sending;

  return (
    <div className="drama-chat-scroll-shell">
    <div ref={scrollRef} className="drama-chat-body" data-testid="storyboard-chat-scroll">
      {idle && (
        <div className="drama-chat-empty">
          <p>描述节奏、风格和重点情节，设计整章分镜或修改指定镜头。</p>
        </div>
      )}
      <div className="drama-chat-thread drama-chat-transcript">
        <ChatTimeline
          timeline={timeline}
          assistantDraft={assistantDraft}
          assistantReasoningDraft={assistantReasoningDraft}
          running={sending}
          onToggleStep={id => setOpened(value => ({ ...value, [id]: !value[id] }))}
        />
      </div>
      {chatError && <p className="drama-chat-error" role="alert">{chatError}</p>}
    </div>
      {!stickToBottom && (
        <button type="button" className="drama-chat-jump" onClick={scrollToBottom}>回到底部</button>
      )}
    </div>
  );
}
