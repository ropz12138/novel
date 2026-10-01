import { forwardRef, useRef, useState, useCallback, useEffect, useLayoutEffect, useImperativeHandle, useMemo } from "react";
import { Bot, Send, Square, Sparkles, Plus, ChevronDown, ChevronRight, Trash2 } from "lucide-react";
import { useSupervisorChat } from "../hooks/useSupervisorChat";
import { ChatTimeline } from "./supervisor/ChatTimeline";
import { useSmartScroll } from "../hooks/useSmartScroll";
import { sessionApi } from "../lib/api";
import { getChapterReviewIntensity, putChapterReviewIntensity } from "../lib/canvasApi";
import { getLatestSupervisorSession } from "../lib/supervisorSession";
import { useKeyboardInset } from "../lib/keyboardInset";
import ModifiedNodeCapsules from "./ModifiedNodeCapsules";
import { attachModifiedNodes } from "../lib/modifiedNodeDraft";

export function scrollTopAfterPrepend(previousTop, previousHeight, nextHeight) {
  return previousTop + (nextHeight - previousHeight);
}

const CHAPTER_REVIEW_INTENSITIES = [
  { value: "low", shortLabel: "低", label: "低 · 不评审，不去 AI 味" },
  { value: "medium", shortLabel: "中", label: "中 · 各评审一次，并去 AI 味" },
  { value: "high", shortLabel: "高", label: "高 · 按需复评，并去 AI 味" },
];

function snapIntensityIndex(ratio) {
  return Math.min(2, Math.max(0, Math.round(ratio * 2)));
}

const NODE_PILL_COLORS = {
  outline: "#3b82f6",
  volume: "#6366f1",
  plot: "#f97316",
  chapter: "#22c55e",
  character: "#ec4899",
  worldbuilding: "#8b5cf6",
  note: "#a855f7",
  element: "#d97706",
};

function latestStreamLine(chat) {
  const runningStep = [...chat.timeline]
    .reverse()
    .find((item) => item.kind === "step" && item.status === "running");
  const source = chat.assistantDraft
    || runningStep?.stream
    || runningStep?.reasoningStream
    || chat.assistantReasoningDraft
    || runningStep?.label
    || (chat.running ? "连接中…" : "");
  return String(source).split(/\r?\n/).filter((line) => line.trim()).at(-1) || "";
}

const AgentChat = forwardRef(function AgentChat({ workId, draft = "", onDraftChange, modifiedNodes = [], onRemoveModifiedNode, onModifiedNodesSent, onNodesUpdate, onNodeContentDiff, onNodeContentDiffsReset, onOpenNodeDetail, onRunningChange, onStateChange, insertPillRef, onCollapse, appMode = false }, ref) {
  const keyboardInset = useKeyboardInset();
  const chat = useSupervisorChat({
    workId,
    callbacks: {
      onChapterUpdated: () => onNodesUpdate?.(),
      onNodesUpdate: () => onNodesUpdate?.(),
      onNodeContentDiff,
      onNodeContentDiffsReset,
    },
  });

  useEffect(() => {
    onRunningChange?.(chat.running);
    return () => onRunningChange?.(false);
  }, [chat.running, onRunningChange]);

  const inputRef = useRef(null);
  const [hasInput, setHasInput] = useState(false);
  const pendingMessages = chat.pendingMessages || [];
  const [chapterReviewIntensity, setChapterReviewIntensity] = useState("medium");
  const [intensityReady, setIntensityReady] = useState(false);
  const [intensityDragRatio, setIntensityDragRatio] = useState(null);
  const intensityTrackRef = useRef(null);
  const intensityDragRef = useRef({ active: false, moved: false });
  const intensityIndex = CHAPTER_REVIEW_INTENSITIES.findIndex((item) => item.value === chapterReviewIntensity);
  const intensityDisplayRatio = intensityDragRatio ?? intensityIndex / 2;

  const ratioFromIntensityPointer = useCallback((clientX) => {
    const rect = intensityTrackRef.current.getBoundingClientRect();
    return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
  }, []);

  const onIntensityPointerDown = useCallback((event) => {
    if (chat.running) return;
    intensityDragRef.current = { active: true, moved: false };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setIntensityDragRatio(intensityIndex / 2);
  }, [chat.running, intensityIndex]);

  const onIntensityPointerMove = useCallback((event) => {
    if (!intensityDragRef.current.active) return;
    intensityDragRef.current.moved = true;
    setIntensityDragRatio(ratioFromIntensityPointer(event.clientX));
  }, [ratioFromIntensityPointer]);

  const intensityChosen = useRef(false);

  const persistChapterReviewIntensity = useCallback((value) => {
    intensityChosen.current = true;
    setChapterReviewIntensity(value);
    putChapterReviewIntensity({ chapter_review_intensity: value }).catch((error) => {
      setSessionError(error?.message || "保存评审强度失败");
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    getChapterReviewIntensity()
      .then((data) => {
        const value = data?.chapter_review_intensity;
        if (cancelled) return;
        if (!CHAPTER_REVIEW_INTENSITIES.some((item) => item.value === value)) {
          setSessionError("评审强度无效");
          return;
        }
        if (!intensityChosen.current) setChapterReviewIntensity(value);
        setIntensityReady(true);
      })
      .catch((error) => {
        if (!cancelled) setSessionError(error?.message || "加载评审强度失败");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const onIntensityPointerUp = useCallback((event) => {
    if (!intensityDragRef.current.active) return;
    const moved = intensityDragRef.current.moved;
    intensityDragRef.current = { active: false, moved: false };
    if (moved) {
      const snapped = snapIntensityIndex(ratioFromIntensityPointer(event.clientX));
      persistChapterReviewIntensity(CHAPTER_REVIEW_INTENSITIES[snapped].value);
    }
    setIntensityDragRatio(null);
  }, [persistChapterReviewIntensity, ratioFromIntensityPointer]);

  const serializeContentEditable = useCallback((el) => {
    let result = "";
    el.childNodes.forEach((node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        result += node.textContent;
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        if (node.dataset.uuid) {
          result += `[[ctx|${node.dataset.uuid}|${node.dataset.type}|${node.dataset.title}]]`;
        } else if (node.dataset.contextQuote) {
          result += `\n“${node.dataset.contextQuote}”`;
        } else if (node.tagName === "BR") {
          result += "\n";
        } else {
          result += node.textContent || "";
        }
      }
    });
    return result.replaceAll("\u200B", "");
  }, []);

  const insertPill = useCallback((uuid, type, title, selectedText = "") => {
    const el = inputRef.current;
    if (!el) return;
    const quote = (selectedText || "").trim();

    const pill = document.createElement("span");
    pill.contentEditable = false;
    pill.className = "inline-flex items-center rounded-full px-2 py-0.5 text-xs text-white mx-0.5 align-middle";
    pill.style.backgroundColor = NODE_PILL_COLORS[type] || "#6b7280";
    const pillTitle = document.createElement("span");
    pillTitle.textContent = title;
    pill.appendChild(pillTitle);
    pill.dataset.uuid = uuid;
    pill.dataset.type = type;
    pill.dataset.title = title;

    let quoteNode = null;
    if (quote) {
      quoteNode = document.createElement("span");
      quoteNode.contentEditable = false;
      quoteNode.dataset.contextQuote = quote;
      quoteNode.className = "my-1 block rounded-r-md border-l-2 border-amber-400 bg-amber-50 px-2 py-1 text-xs leading-relaxed text-slate-700";
      quoteNode.textContent = quote;
      quoteNode.title = "选中的节点原文";
    }
    const trailingBreak = quoteNode ? document.createElement("br") : null;
    const caretNode = document.createTextNode("\u200B");

    const removeContext = () => {
      pill.remove();
      quoteNode?.remove();
      trailingBreak?.remove();
      const hasVisibleContent = el.textContent.replaceAll("\u200B", "").trim().length > 0
        || el.querySelector("[data-uuid]");
      if (!hasVisibleContent) el.setAttribute("data-empty", "");
      setHasInput(Boolean(hasVisibleContent));
      onDraftChange?.(serializeContentEditable(el));
      el.focus();
    };

    const removeButton = document.createElement("span");
    removeButton.contentEditable = false;
    removeButton.setAttribute("role", "button");
    removeButton.setAttribute("aria-label", `移除上下文 ${title}`);
    removeButton.dataset.contextRemove = "";
    removeButton.className = "ml-1 inline-flex h-3.5 w-3.5 cursor-pointer items-center justify-center rounded-full text-[11px] leading-none hover:bg-black/20";
    removeButton.textContent = "×";
    removeButton.addEventListener("mousedown", (event) => event.preventDefault());
    removeButton.addEventListener("click", removeContext);
    pill.appendChild(removeButton);

    const sel = window.getSelection();
    if (sel && sel.rangeCount > 0 && el.contains(sel.anchorNode)) {
      const range = sel.getRangeAt(0);
      range.deleteContents();
      range.insertNode(pill);
      range.setStartAfter(pill);
      if (quoteNode) {
        range.insertNode(quoteNode);
        range.setStartAfter(quoteNode);
        range.insertNode(trailingBreak);
        range.setStartAfter(trailingBreak);
      }
      range.insertNode(caretNode);
      range.setStart(caretNode, caretNode.length);
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
    } else {
      el.appendChild(pill);
      if (quoteNode) {
        el.appendChild(quoteNode);
        el.appendChild(trailingBreak);
      }
      el.appendChild(caretNode);
      const range = document.createRange();
      range.setStart(caretNode, caretNode.length);
      range.collapse(true);
      sel.removeAllRanges();
      sel.addRange(range);
    }
    el.removeAttribute("data-empty");
    setHasInput(true);
    onDraftChange?.(serializeContentEditable(el));
    const focusComposer = () => {
      el.focus();
      const nextSel = window.getSelection();
      if (!nextSel) return;
      const caret = document.createRange();
      caret.setStart(caretNode, caretNode.length);
      caret.collapse(true);
      nextSel.removeAllRanges();
      nextSel.addRange(caret);
    };
    focusComposer();
    requestAnimationFrame(focusComposer);
  }, [onDraftChange, serializeContentEditable]);

  useLayoutEffect(() => {
    if (insertPillRef) {
      insertPillRef.current = insertPill;
    }
    return () => {
      if (insertPillRef) {
        insertPillRef.current = null;
      }
    };
  }, [insertPillRef, insertPill]);

  const sendOrQueue = useCallback((message, intensity = chapterReviewIntensity) => {
    const text = String(message || "").trim();
    if (!text) return;
    const content = attachModifiedNodes(text, modifiedNodes, chat.sessionId);
    onModifiedNodesSent?.();
    chat.handleSend(content, intensity);
  }, [chat.running, chat.handleSend, chat.sessionId, chapterReviewIntensity, modifiedNodes, onModifiedNodesSent]);

  const handleContentEditableSend = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    const serialized = serializeContentEditable(el);
    if (!intensityReady || !serialized.trim()) return;
    el.innerHTML = "";
    el.setAttribute("data-empty", "");
    setHasInput(false);
    onDraftChange?.("");
    sendOrQueue(serialized, chapterReviewIntensity);
  }, [chapterReviewIntensity, intensityReady, onDraftChange, sendOrQueue, serializeContentEditable]);

  const onInput = useCallback(() => {
    const el = inputRef.current;
    const empty = !el || el.textContent.trim().length === 0;
    setHasInput(!empty);
    if (el) {
      if (empty) el.setAttribute("data-empty", "");
      else el.removeAttribute("data-empty");
      onDraftChange?.(serializeContentEditable(el));
    }
  }, [onDraftChange, serializeContentEditable]);

  useLayoutEffect(() => {
    const el = inputRef.current;
    if (!el || serializeContentEditable(el) === draft) return;
    el.textContent = draft;
    const empty = !draft.trim();
    if (empty) el.setAttribute("data-empty", "");
    else el.removeAttribute("data-empty");
    setHasInput(!empty);
  }, [draft, serializeContentEditable]);

  const scrollContainerRef = useRef(null);
  const loadingOlderRef = useRef(false);
  const preserveScrollRef = useRef(null);
  const { stickToBottom, scrollToBottom } = useSmartScroll(scrollContainerRef, [
    chat.timeline, chat.assistantReasoningDraft, chat.assistantDraft,
    chat.running,
  ]);

  const requestOlderMessages = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el || loadingOlderRef.current || !chat.hasMoreHistory || !chat.loadOlderMessages) return;
    loadingOlderRef.current = true;
    preserveScrollRef.current = { top: el.scrollTop, height: el.scrollHeight };
    Promise.resolve(chat.loadOlderMessages()).finally(() => {
      loadingOlderRef.current = false;
    });
  }, [chat.hasMoreHistory, chat.loadOlderMessages]);

  useLayoutEffect(() => {
    const el = scrollContainerRef.current;
    const snap = preserveScrollRef.current;
    if (!el || !snap) return;
    el.scrollTop = scrollTopAfterPrepend(snap.top, snap.height, el.scrollHeight);
    preserveScrollRef.current = null;
  }, [chat.timeline]);

  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el || !chat.hasMoreHistory || loadingOlderRef.current) return;
    if (el.clientHeight > 0 && el.scrollHeight <= el.clientHeight + 1) requestOlderMessages();
  }, [chat.timeline, chat.hasMoreHistory, requestOlderMessages]);

  // Session 下拉框状态
  const [sessions, setSessions] = useState([]);
  const [sessionError, setSessionError] = useState("");
  const [sessionListOpen, setSessionListOpen] = useState(false);
  const dropdownRef = useRef(null);
  const latestSessionLoadedForWorkRef = useRef(null);
  const [sessionReady, setSessionReady] = useState(false);


  const loadSessions = useCallback(async () => {
    setSessionError("");
    try {
      const list = await sessionApi.listSupervisor(workId);
      setSessions(list || []);
      return list || [];
    } catch (error) {
      setSessionError(error?.message || "加载对话列表失败");
      return null;
    }
  }, [workId]);

  // 进入/切换作品时，自动加载该作品最新一次对话
  useEffect(() => {
    if (!workId || chat.running) return;
    if (latestSessionLoadedForWorkRef.current === workId) return;

    let cancelled = false;
    setSessionReady(false);
    (async () => {
      const list = await loadSessions();
      if (cancelled) return;
      if (list === null) {
        setSessionReady(true);
        return;
      }

      latestSessionLoadedForWorkRef.current = workId;
      const latest = getLatestSupervisorSession(list);
      if (latest) {
        await chat.handleSelectSession(latest);
      } else {
        chat.resetState();
      }
      if (!cancelled) setSessionReady(true);
    })();

    return () => {
      cancelled = true;
    };
  }, [workId, chat.running]);

  // session 创建后刷新列表
  useEffect(() => {
    if (chat.sessionId) loadSessions();
  }, [chat.sessionId, loadSessions]);

  // 点击外部关闭下拉框
  useEffect(() => {
    const handleClick = (e) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target)) {
        setSessionListOpen(false);
      }
    };
    if (sessionListOpen) document.addEventListener("pointerdown", handleClick);
    return () => document.removeEventListener("pointerdown", handleClick);
  }, [sessionListOpen]);

  const currentSessionTitle = useMemo(() => {
    if (!chat.sessionId) return "新对话";
    const s = sessions.find((s) => s.id === chat.sessionId);
    return s?.title || "新对话";
  }, [chat.sessionId, sessions]);

  const handleNewSession = useCallback(() => {
    if (chat.running) return;
    chat.resetState();
    setSessionReady(true);
    setSessionListOpen(false);
  }, [chat]);

  const handleSelectSession = useCallback(async (session) => {
    setSessionListOpen(false);
    await chat.handleSelectSession(session);
  }, [chat]);

  const handleDeleteSession = useCallback(async (e, id) => {
    e.stopPropagation();
    if (chat.running) return;
    if (!confirm("确定删除这个对话？")) return;
    try {
      await sessionApi.deleteSupervisor(id);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      if (chat.sessionId === id) handleNewSession();
      setSessionError("");
    } catch (error) {
      setSessionError(error?.message || "删除对话失败");
    }
  }, [chat, handleNewSession]);

  const streamLine = useMemo(() => latestStreamLine(chat), [
    chat.timeline,
    chat.assistantDraft,
    chat.assistantReasoningDraft,
    chat.running,
  ]);

  useImperativeHandle(ref, () => ({
    ready: sessionReady,
    running: chat.running,
    streamLine,
    send: (message) => {
      if (sessionReady && intensityReady) sendOrQueue(message, chapterReviewIntensity);
    },
    stop: () => {
      chat.handleStop();
    },
    setIntensity: (value) => {
      if (CHAPTER_REVIEW_INTENSITIES.some((item) => item.value === value)) {
        persistChapterReviewIntensity(value);
      }
    },
    newSession: handleNewSession,
    selectSession: handleSelectSession,
    refresh: chat.refreshCurrentSession,
  }), [sessionReady, intensityReady, chat.running, chat.handleStop, chat.refreshCurrentSession, chapterReviewIntensity, persistChapterReviewIntensity, handleNewSession, handleSelectSession, sendOrQueue, streamLine]);

  useEffect(() => {
    onStateChange?.({
      ready: sessionReady,
      running: chat.running,
      streamLine,
      sessions,
      sessionId: chat.sessionId,
      chapterReviewIntensity,
      pendingMessages,
    });
  }, [onStateChange, sessionReady, chat.running, streamLine, sessions, chat.sessionId, chapterReviewIntensity, pendingMessages]);

  return (
    <div
      data-testid="agent-chat"
      className="flex h-full flex-col border-l border-gray-200 bg-white"
      style={{ paddingBottom: `${keyboardInset}px` }}
    >
      {/* Header — 下拉选择器 */}
      <div ref={dropdownRef} className="relative shrink-0 border-b border-gray-200">
        <div className="flex items-center justify-between px-3 py-2">
          <button
            type="button"
            onClick={onCollapse}
            className="mr-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
            title="收起Agent侧边栏"
            aria-label="收起Agent侧边栏"
          >
            <ChevronRight className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => !chat.running && setSessionListOpen(!sessionListOpen)}
            className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm text-slate-700 transition-colors hover:bg-slate-100 disabled:opacity-50"
            disabled={chat.running}
          >
            <Bot className="h-4 w-4 text-blue-500 shrink-0" />
            <span className="truncate">{currentSessionTitle}</span>
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          </button>
          <button
            type="button"
            onClick={handleNewSession}
            disabled={chat.running}
            className="flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-blue-50 hover:text-blue-500 disabled:opacity-50"
            title="新建对话"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* 下拉列表 */}
        {sessionListOpen && (
          <div className="absolute left-0 top-full z-50 w-full max-h-[280px] overflow-y-auto rounded-b-lg border border-t-0 border-slate-200 bg-white shadow-lg">
            {sessionError ? (
              <p className="px-3 py-4 text-center text-xs text-red-500">{sessionError}</p>
            ) : sessions.length === 0 ? (
              <p className="px-3 py-4 text-center text-xs text-slate-400">暂无对话</p>
            ) : (
              sessions.map((s) => (
                <div
                  key={s.id}
                  className={`group flex items-center px-3 py-2 cursor-pointer transition-colors ${
                    chat.sessionId === s.id
                      ? "bg-blue-50 text-blue-800"
                      : "text-slate-600 hover:bg-slate-50"
                  }`}
                  onClick={() => handleSelectSession(s)}
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-xs font-medium">{s.title}</p>
                    <p className="text-[10px] text-slate-400">
                      {s.updated_at ? new Date(s.updated_at).toLocaleDateString("zh-CN") : ""}
                    </p>
                  </div>
                  <button
                    onClick={(e) => handleDeleteSession(e, s.id)}
                    className="hidden group-hover:flex shrink-0 items-center justify-center rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-500"
                    title="删除"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* 消息列表 */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto p-4"
        onScroll={(event) => {
          if (event.currentTarget.scrollTop <= 48) requestOlderMessages();
        }}
      >
        <div className="space-y-4">
          {chat.timeline.length === 0 && !chat.running && (
            <div className="text-center text-gray-400 mt-12">
              <div className="flex justify-center mb-4">
                <div className="rounded-full bg-blue-100 p-3">
                  <Sparkles className="h-6 w-6 text-blue-500" />
                </div>
              </div>
              <p className="text-sm font-medium mb-2">AI 写作助手</p>
              <p className="text-xs text-gray-400 mb-4">
                输入你的创作需求，AI 会自动识别并执行
              </p>
              <div className="space-y-2">
                {[
                  "帮我写一个科幻大纲",
                  "写第1章",
                  "查看当前画布状态",
                ].map((example) => (
                  <button
                    key={example}
                    onClick={() => {
                      const el = inputRef.current;
                      if (el) {
                        el.textContent = example;
                        el.removeAttribute("data-empty");
                        setHasInput(true);
                      }
                    }}
                    className="block w-full text-left px-3 py-2 text-xs text-gray-500 hover:text-gray-700 hover:bg-gray-50 rounded-lg transition-colors border border-gray-100"
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          )}

          <ChatTimeline
            timeline={chat.timeline}
            assistantReasoningDraft={chat.assistantReasoningDraft}
            assistantDraft={chat.assistantDraft}
            running={chat.running}
            onToggleStep={chat.toggleStepPanel}
            onEditMessage={(messageId, content) => chat.handleEditResend(messageId, content, chapterReviewIntensity)}
            onExpandDiff={chat.expandDiffDetail}
            onCollapseDiff={chat.collapseDiffDetail}
            onOpenDiffNode={appMode ? undefined : onOpenNodeDetail}
          />

          {chat.running && !chat.timeline.some((item) => item.kind === "step" && item.status === "running") && !chat.assistantDraft && !chat.assistantReasoningDraft && (
            <div className="flex gap-3 justify-start">
              <div className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-500 animate-pulse">
                <Bot className="h-3.5 w-3.5" />
              </div>
              <div className="rounded-xl bg-slate-100 px-4 py-2.5 text-sm text-slate-500">连接中…</div>
            </div>
          )}
        </div>

        {!stickToBottom && chat.timeline.length > 3 && (
          <button
            onClick={scrollToBottom}
            className="sticky bottom-2 left-1/2 -translate-x-1/2 flex items-center gap-1 rounded-full bg-white/90 border border-slate-200 px-3 py-1 text-xs text-slate-600 shadow-sm backdrop-blur hover:bg-white hover:border-blue-300 transition-colors"
          >
            回到底部
          </button>
        )}
      </div>

      {/* 输入框 */}
      <div className="shrink-0 px-3 py-3 border-t border-gray-200 bg-gray-50">
        <ModifiedNodeCapsules nodes={chat.sessionId ? modifiedNodes : []} onRemove={onRemoveModifiedNode} />
        {pendingMessages.length > 0 && (
          <div aria-label="待发送消息" className="mb-2 max-h-24 space-y-1 overflow-y-auto rounded-lg border border-blue-100 bg-blue-50 p-2">
            {pendingMessages.map((message) => (
              <div key={message.id} className="truncate text-xs text-blue-700">等待发送：{message.content}</div>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2">
          <div
            ref={inputRef}
            role="textbox"
            aria-label="创作指令"
            contentEditable
            onInput={onInput}
            onKeyDown={(e) => {
              if (e.key === "Backspace") {
                const selection = window.getSelection();
                if (selection?.isCollapsed && selection.rangeCount > 0) {
                  const range = selection.getRangeAt(0);
                  const anchor = range.startContainer;
                  const textBeforeCaret = anchor.nodeType === Node.TEXT_NODE
                    ? anchor.textContent.slice(0, range.startOffset).replaceAll("\u200B", "")
                    : "";
                  if (!textBeforeCaret) {
                    let previous = anchor.nodeType === Node.TEXT_NODE
                      ? anchor.previousSibling
                      : inputRef.current?.childNodes[range.startOffset - 1];
                    if (previous?.nodeName === "BR") previous = previous.previousSibling;
                    if (previous?.dataset?.contextQuote) previous = previous.previousSibling;
                    if (previous?.dataset?.uuid) {
                      e.preventDefault();
                      previous.querySelector("[data-context-remove]")?.click();
                      return;
                    }
                  }
                }
              }
              if (e.key === "Enter" && !appMode && !e.shiftKey) {
                e.preventDefault();
                handleContentEditableSend();
              }
            }}
            onPaste={(e) => {
              e.preventDefault();
              const text = e.clipboardData.getData("text/plain");
              document.execCommand("insertText", false, text);
            }}
            data-placeholder="输入指令..."
            className="ce-input flex-1 px-3 py-2 border border-gray-300 rounded-lg bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm whitespace-pre-wrap break-words min-h-[2.5rem] max-h-32 overflow-y-auto"
          />
          <button
            onClick={chat.running && !hasInput ? chat.handleStop : handleContentEditableSend}
            disabled={!chat.running && (!hasInput || !intensityReady)}
            aria-label={chat.running && !hasInput ? "中止" : "发送"}
            className={`h-10 w-10 shrink-0 rounded-full flex items-center justify-center text-white transition-colors ${
              chat.running && !hasInput
                ? "bg-red-500 hover:bg-red-600"
                : "bg-blue-500 hover:bg-blue-600 disabled:cursor-not-allowed disabled:bg-gray-300"
            }`}
          >
            {chat.running && !hasInput ? <Square className="h-4 w-4" /> : <Send className="h-4 w-4" />}
          </button>
        </div>
        <div className="mt-2 flex justify-end">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-gray-500">章节评审强度</span>
            <div
              ref={intensityTrackRef}
              role="slider"
              aria-label="章节评审强度"
              aria-valuemin={0}
              aria-valuemax={2}
              aria-valuenow={intensityIndex}
              aria-valuetext={chapterReviewIntensity}
              aria-disabled={chat.running}
              tabIndex={chat.running ? -1 : 0}
              onPointerDown={onIntensityPointerDown}
              onPointerMove={onIntensityPointerMove}
              onPointerUp={onIntensityPointerUp}
              onPointerCancel={onIntensityPointerUp}
              className={`relative grid h-6 w-16 grid-cols-3 rounded-md bg-gray-200 p-0.5 text-[10px] select-none ${
                chat.running ? "cursor-not-allowed opacity-50" : "cursor-ew-resize"
              }`}
            >
              <div
                data-intensity-window
                data-intensity={chapterReviewIntensity}
                className={`pointer-events-none absolute inset-y-0.5 left-0.5 w-[calc((100%-4px)/3)] rounded bg-white shadow-sm ${
                  intensityDragRatio == null ? "transition-transform duration-150" : ""
                }`}
                style={{ transform: `translateX(${intensityDisplayRatio * 200}%)` }}
              />
              {CHAPTER_REVIEW_INTENSITIES.map((item) => (
                <span
                  key={item.value}
                  className={`pointer-events-none relative z-10 flex items-center justify-center ${
                    chapterReviewIntensity === item.value ? "font-medium text-gray-900" : "text-gray-500"
                  }`}
                >
                  {item.shortLabel}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
});

AgentChat.displayName = "AgentChat";

export { latestStreamLine };
export default AgentChat;
