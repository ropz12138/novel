import { useEffect, useRef, useState } from "react";
import { Bot, Minus, Send, Square } from "lucide-react";
import { useKeyboardInset } from "../lib/keyboardInset";
import ModifiedNodeCapsules from "./ModifiedNodeCapsules";
import SessionContextUsage from "./SessionContextUsage";

const COMPOSER_BOTTOM_GAP_PX = 12;

const REVIEW_INTENSITIES = [
  { value: "low", shortLabel: "低", label: "低 · 不评审，不去 AI 味" },
  { value: "medium", shortLabel: "中", label: "中 · 各评审一次，并去 AI 味" },
  { value: "high", shortLabel: "高", label: "高 · 按需复评，并去 AI 味" },
];

function snapIntensityIndex(ratio) {
  return Math.min(2, Math.max(0, Math.round(ratio * 2)));
}

function IntensitySlider({ value, disabled, onChange }) {
  const trackRef = useRef(null);
  const dragRef = useRef({ active: false });
  const [dragRatio, setDragRatio] = useState(null);
  const index = Math.max(0, REVIEW_INTENSITIES.findIndex((item) => item.value === value));
  const displayRatio = dragRatio ?? index / 2;

  const ratioFromPointer = (clientX) => {
    const rect = trackRef.current.getBoundingClientRect();
    return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  };

  const onPointerDown = (event) => {
    if (disabled) return;
    dragRef.current = { active: true };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setDragRatio(index / 2);
  };

  const onPointerMove = (event) => {
    if (!dragRef.current.active) return;
    setDragRatio(ratioFromPointer(event.clientX));
  };

  const onPointerUp = (event) => {
    if (!dragRef.current.active) return;
    dragRef.current = { active: false };
    const snapped = snapIntensityIndex(ratioFromPointer(event.clientX));
    onChange?.(REVIEW_INTENSITIES[snapped].value);
    setDragRatio(null);
  };

  return (
    <div
      ref={trackRef}
      role="slider"
      aria-label="快捷评审强度"
      aria-valuemin={0}
      aria-valuemax={2}
      aria-valuenow={index}
      aria-valuetext={REVIEW_INTENSITIES[index].value}
      aria-disabled={disabled}
      tabIndex={disabled ? -1 : 0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      className={`pointer-events-auto relative grid h-7 w-24 grid-cols-3 rounded-full bg-white/95 p-0.5 text-[11px] shadow-[0_8px_20px_rgba(15,23,42,0.12)] select-none ${
        disabled ? "cursor-not-allowed opacity-50" : "cursor-ew-resize"
      }`}
    >
      <div
        data-intensity-window
        className={`pointer-events-none absolute inset-y-0.5 left-0.5 w-[calc((100%-4px)/3)] rounded-full bg-slate-100 ${
          dragRatio == null ? "transition-transform duration-150" : ""
        }`}
        style={{ transform: `translateX(${displayRatio * 200}%)` }}
      />
      {REVIEW_INTENSITIES.map((item) => (
        <span
          key={item.value}
          title={item.label}
          className={`pointer-events-none relative z-10 flex items-center justify-center ${
            value === item.value ? "font-medium text-slate-900" : "text-slate-500"
          }`}
        >
          {item.shortLabel}
        </span>
      ))}
    </div>
  );
}

function isThinkingStream(line) {
  const text = String(line || "").trim();
  if (!text) return true;
  return /思考|连接中|重连|修复工具参数/.test(text);
}

function ThinkingPreview({ text }) {
  const label = text.trim() || "AI 思考中";
  return (
    <div
      data-testid="app-composer-thinking"
      className="flex h-10 min-w-0 flex-1 items-center overflow-hidden rounded-full bg-slate-50 px-3"
    >
      <span className="flex min-w-0 items-center text-[12px] leading-5 text-slate-500">
        {Array.from(label).map((ch, index) => (
          <span
            key={`${ch}-${index}`}
            className="app-composer-think-char"
            style={{ animationDelay: `${index * 0.12}s` }}
          >
            {ch === " " ? "\u00a0" : ch}
          </span>
        ))}
        <span className="ml-1 inline-flex items-center gap-0.5">
          {[0, 1, 2].map((index) => (
            <span
              key={index}
              className="app-composer-think-dot h-1 w-1 rounded-full bg-slate-400"
              style={{ animationDelay: `${index * 0.16}s` }}
            />
          ))}
        </span>
      </span>
    </div>
  );
}

function StreamPreview({ text }) {
  return (
    <div
      data-testid="app-composer-stream"
      className="flex h-10 min-w-0 flex-1 items-center overflow-hidden rounded-full bg-slate-100 px-3"
    >
      <span className="block w-full truncate text-[12px] leading-5 text-slate-500">{text}</span>
    </div>
  );
}


export default function AppFloatingComposer({
  modifiedNodes = [],
  onRemoveModifiedNode,
  draft,
  onDraftChange,
  ready = false,
  running = false,
  streamLine = "",
  sessions = [],
  currentSessionId = null,
  intensity = "medium",
  pendingMessages = [],
  agentCollapsed = false,
  onNewSession,
  onSelectSession,
  onSend,
  onStop,
  onIntensityChange,
  onExpandAgent,
}) {
  const [localMessage, setLocalMessage] = useState("");
  const message = draft ?? localMessage;
  const [inputFocused, setInputFocused] = useState(false);
  const [sessionListOpen, setSessionListOpen] = useState(false);
  const keyboardOffset = useKeyboardInset();
  const rootRef = useRef(null);

  const updateMessage = (nextMessage) => {
    if (draft === undefined) setLocalMessage(nextMessage);
    onDraftChange?.(nextMessage);
  };

  useEffect(() => {
    if (!sessionListOpen) return undefined;
    const handlePointerDown = (event) => {
      if (rootRef.current && !rootRef.current.contains(event.target)) {
        setSessionListOpen(false);
      }
    };
    document.addEventListener("pointerdown", handlePointerDown);
    return () => document.removeEventListener("pointerdown", handlePointerDown);
  }, [sessionListOpen]);

  const send = () => {
    const content = message.trim();
    if (!content || !ready) return;
    onSend?.(content);
    updateMessage("");
  };

  const showStream = running && !inputFocused && !message.trim();

  return (
    <div
      data-testid="app-floating-composer"
      className="pointer-events-none absolute inset-x-3 z-[60] flex justify-center"
      style={{ bottom: `${COMPOSER_BOTTOM_GAP_PX + keyboardOffset}px` }}
    >
      <div ref={rootRef} className="relative w-full max-w-3xl">
        <ModifiedNodeCapsules nodes={modifiedNodes} onRemove={onRemoveModifiedNode} />
        {pendingMessages.length > 0 && (
          <div aria-label="待发送消息" className="pointer-events-auto mb-2 max-h-20 space-y-1 overflow-y-auto rounded-xl border border-blue-100 bg-blue-50/95 px-3 py-2 shadow">
            {pendingMessages.map((item) => (
              <div key={item.id} className="truncate text-xs text-blue-700">等待发送：{item.content}</div>
            ))}
          </div>
        )}
        {sessionListOpen && (
          <div
            data-testid="app-session-list"
            className="pointer-events-auto absolute inset-x-0 bottom-full mb-2 max-h-64 overflow-y-auto rounded-2xl border border-slate-200 bg-white/95 shadow-[0_10px_35px_rgba(15,23,42,0.2)] backdrop-blur"
          >
            <button
              type="button"
              aria-label="新对话"
              disabled={!ready || running}
              onClick={() => {
                onNewSession?.();
                setSessionListOpen(false);
              }}
              className="flex w-full items-center px-4 py-2.5 text-left text-sm font-medium text-blue-600 hover:bg-blue-50 disabled:opacity-40"
            >
              新对话
            </button>
            {sessions.map((session) => (
              <button
                key={session.id}
                type="button"
                aria-label={session.title || "未命名对话"}
                disabled={running}
                onClick={() => {
                  onSelectSession?.(session);
                  setSessionListOpen(false);
                }}
                className={`flex w-full items-center px-4 py-2.5 text-left text-sm ${
                  currentSessionId === session.id
                    ? "bg-blue-50 text-blue-800"
                    : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                <span className="flex min-w-0 flex-col">
                  <span className="truncate">{session.title || "未命名对话"}</span>
                  <SessionContextUsage tokens={session.context_input_tokens} />
                </span>
              </button>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2">
        <div className="flex min-w-0 flex-1 flex-col items-end gap-1">
        <IntensitySlider
          value={intensity}
          disabled={running}
          onChange={onIntensityChange}
        />
        <div
          data-testid="app-floating-composer-bar"
          className="pointer-events-auto flex w-full min-w-0 items-center gap-2 rounded-full border border-slate-200/90 bg-white/95 px-2 py-1.5 shadow-[0_10px_35px_rgba(15,23,42,0.2)] backdrop-blur"
        >
          <button
            type="button"
            aria-label="会话列表"
            title="会话列表"
            disabled={!ready || running}
            onClick={() => setSessionListOpen((open) => !open)}
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-slate-500 hover:bg-blue-50 hover:text-blue-600 disabled:opacity-40"
          >
            <Minus className="h-5 w-5" />
          </button>
          <div className="relative min-w-0 flex-1">
          <textarea
            aria-label="快捷创作指令"
            value={message}
            disabled={!ready}
            onChange={(event) => updateMessage(event.target.value)}
            onFocus={() => setInputFocused(true)}
            onBlur={() => setInputFocused(false)}
            rows={1}
            placeholder={showStream ? "" : (ready ? (running ? "输入下一条指令…" : "输入创作指令…") : "正在载入最新会话…")}
            className="block w-full max-h-28 min-h-10 min-w-0 resize-none overflow-y-auto bg-transparent px-1 py-2.5 text-sm text-slate-700 outline-none placeholder:text-slate-400 disabled:cursor-wait"
          />
          {showStream && (
            <div className="pointer-events-none absolute inset-0 flex items-center" aria-hidden="true">
              {isThinkingStream(streamLine)
                ? <ThinkingPreview text={streamLine} />
                : <StreamPreview text={streamLine} />}
            </div>
          )}
          </div>
          <button
            type="button"
            aria-label={running && !message.trim() ? "中止" : "发送快捷指令"}
            title={running && !message.trim() ? "中止" : (running ? "加入待发送队列" : "发送")}
            disabled={!running && (!ready || !message.trim())}
            onClick={running && !message.trim() ? () => onStop?.() : send}
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-white ${
              running && !message.trim()
                ? "bg-red-500 hover:bg-red-600"
                : "bg-blue-600 hover:bg-blue-700 disabled:bg-slate-300"
            }`}
          >
            {running && !message.trim() ? <Square className="h-4 w-4" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
        </div>
        {agentCollapsed && (
          <button
            type="button"
            aria-label="展开Agent侧边栏"
            title="展开Agent"
            onClick={onExpandAgent}
            className="pointer-events-auto flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-slate-200/90 bg-white/95 text-slate-500 shadow-[0_10px_35px_rgba(15,23,42,0.2)] backdrop-blur hover:bg-blue-50 hover:text-blue-600"
          >
            <Bot className="h-4 w-4" />
          </button>
        )}
        </div>
      </div>
    </div>
  );
}
