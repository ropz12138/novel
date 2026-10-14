import { Children, cloneElement, createContext, useContext, memo, useState, useEffect, useLayoutEffect, useMemo, useRef, useCallback } from "react";
import { X, Trash2, BookOpen, FileText, User, StickyNote, Map as MapIcon, Zap, Layers, Pencil, Plus, Maximize2, Minimize2, Check, Copy, Undo2, ChevronLeft, ChevronRight } from "lucide-react";
import {
  buildStackedInlineDiffBlocks,
  contentAfterBatches,
  buildContentDiffFromContents,
  commitUserParagraphEdit,
  commitUserTextEdit,
  hydrateDiffBatches,
  joinParagraphs,
  pendingHunksFromBatches,
  setAllHunkStatusInBatches,
  setHunkStatusInBatches,
  splitParagraphs,
} from "../../lib/inlineContentDiff";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import AuthIllustrationImage, { isIllustrationApiPath } from "./AuthIllustrationImage";
import { compareSiblings } from "../../lib/canvasOrder";
import { remarkHtmlBreaks } from "../../lib/markdown";
import InlineTextDiff from "../InlineTextDiff";
import { agentDiffBlocks, decideAgentGroup } from "../../lib/agentContentDiff";
import { editorScrollDelta, useKeyboardInset } from "../../lib/keyboardInset";

const HIGHLIGHT_TOKEN_PREFIX = "%%NODE_HIGHLIGHT_";
const HIGHLIGHT_TOKEN_SUFFIX = "%%";
const PLOT_HIGHLIGHT_START = "[[PLOT]]";
const PLOT_HIGHLIGHT_END = "[[/PLOT]]";

function maskPlotHighlights(content) {
  const highlights = [];
  let masked = "";
  let cursor = 0;

  while (cursor < content.length) {
    const start = content.indexOf(PLOT_HIGHLIGHT_START, cursor);
    if (start < 0) {
      masked += content.slice(cursor);
      break;
    }

    const contentStart = start + PLOT_HIGHLIGHT_START.length;
    const end = content.indexOf(PLOT_HIGHLIGHT_END, contentStart);
    if (end < 0) {
      masked += content.slice(cursor);
      break;
    }

    masked += content.slice(cursor, start);
    const text = content.slice(contentStart, end);
    if (text) {
      const index = highlights.length;
      highlights.push(text);
      masked += `${HIGHLIGHT_TOKEN_PREFIX}${index}${HIGHLIGHT_TOKEN_SUFFIX}`;
    } else {
      masked += `${PLOT_HIGHLIGHT_START}${PLOT_HIGHLIGHT_END}`;
    }
    cursor = end + PLOT_HIGHLIGHT_END.length;
  }

  return { masked, highlights };
}

function renderHighlightTokens(text, highlights, keyPrefix) {
  const tokenRe = /%%NODE_HIGHLIGHT_(\d+)%%/g;
  const nodes = [];
  let cursor = 0;
  let index = 0;
  let match;

  while ((match = tokenRe.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(text.slice(cursor, match.index));
    }
    const highlight = highlights[Number(match[1])];
    if (highlight) {
      nodes.push(
        <span
          key={`${keyPrefix}-${index++}`}
          className="rounded bg-amber-100 px-0.5 font-semibold text-amber-950 ring-1 ring-amber-200/70"
        >
          {highlight}
        </span>
      );
    } else {
      nodes.push(match[0]);
    }
    cursor = match.index + match[0].length;
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor));
  }

  return nodes;
}

function renderMarkdownChildrenWithHighlights(children, highlights, keyPrefix = "hl") {
  return Children.map(children, (child, index) => {
    if (typeof child === "string") {
      return renderHighlightTokens(child, highlights, `${keyPrefix}-${index}`);
    }
    return child;
  });
}

const SourceReferenceContext = createContext(null);

const MarkdownRenderer = memo(function MarkdownRenderer({ content }) {
  const quote = useContext(SourceReferenceContext);
  const rootRef = useRef(null);
  const { masked, highlights } = quote ? { masked: content || "", highlights: [] } : maskPlotHighlights(content || "");
  const start = quote ? masked.indexOf(quote) : -1;
  const markComponents = (components) => Object.fromEntries(Object.entries(components).map(([tag, render]) => [tag, (props) => {
    const element = render(props);
    const position = props.node?.position;
    if (start < 0 || !position || !["p", "h1", "h2", "h3", "h4", "li", "blockquote", "td", "th", "code"].includes(tag)) return element;
    if (position.start.offset >= start + quote.length || position.end.offset <= start) return element;
    return cloneElement(element, { "data-node-reference-hit": true, style: { backgroundColor: "#fef3c7", borderRadius: "4px" } });
  }]));
  useEffect(() => {
    if (!quote) return;
    const frame = requestAnimationFrame(() => rootRef.current?.querySelector("[data-node-reference-hit]")?.scrollIntoView?.({ block: "center" }));
    return () => cancelAnimationFrame(frame);
  }, [quote, content]);
  const renderChildren = (children, keyPrefix) => renderMarkdownChildrenWithHighlights(children, highlights, keyPrefix);

  return (
    <div ref={rootRef} className="prose prose-sm max-w-none tracking-wider">
    <Markdown
      remarkPlugins={[remarkGfm, remarkHtmlBreaks]}
      components={markComponents({
        h1: ({ children }) => <h1 className="text-2xl font-bold mt-6 mb-3 text-gray-900">{renderChildren(children, "h1")}</h1>,
        h2: ({ children }) => <h2 className="text-xl font-bold mt-5 mb-2 text-gray-900">{renderChildren(children, "h2")}</h2>,
        h3: ({ children }) => <h3 className="text-lg font-semibold mt-4 mb-2 text-gray-800">{renderChildren(children, "h3")}</h3>,
        h4: ({ children }) => <h4 className="text-base font-semibold mt-3 mb-1 text-gray-800">{renderChildren(children, "h4")}</h4>,
        p: ({ children }) => <p className="mb-3 leading-8 text-gray-700">{renderChildren(children, "p")}</p>,
        ul: ({ children }) => <ul className="list-disc pl-5 mb-3 space-y-1">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-5 mb-3 space-y-1">{children}</ol>,
        li: ({ children }) => <li className="text-gray-700">{renderChildren(children, "li")}</li>,
        blockquote: ({ children }) => (
          <blockquote className="border-l-4 border-gray-300 pl-4 italic text-gray-600 my-3">
            {renderChildren(children, "blockquote")}
          </blockquote>
        ),
        code: ({ node, inline, className, children, ...props }) => {
          if (inline) {
            return <code className="bg-gray-100 px-1.5 py-0.5 rounded text-sm font-mono text-pink-600" {...props}>{children}</code>;
          }
          return (
            <pre className="bg-gray-900 text-gray-100 rounded-lg p-4 overflow-x-auto my-3">
              <code className="text-sm font-mono" {...props}>{children}</code>
            </pre>
          );
        },
        table: ({ children }) => (
          <div className="overflow-x-auto my-3">
            <table className="min-w-full border-collapse border border-gray-300">{children}</table>
          </div>
        ),
        thead: ({ children }) => <thead className="bg-gray-100">{children}</thead>,
        th: ({ children }) => <th className="border border-gray-300 px-4 py-2 text-left font-semibold text-gray-700">{renderChildren(children, "th")}</th>,
        td: ({ children }) => <td className="border border-gray-300 px-4 py-2 text-gray-700">{renderChildren(children, "td")}</td>,
        hr: () => <hr className="my-6 border-gray-300" />,
        strong: ({ children }) => <strong className="font-semibold text-gray-900">{children}</strong>,
        em: ({ children }) => <em className="italic">{children}</em>,
        a: ({ href, children }) => (
          <a href={href} className="text-blue-600 hover:underline" target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
        img: ({ src, alt }) => (
          isIllustrationApiPath(src)
            ? <AuthIllustrationImage src={src} alt={alt} />
            : <img src={src} alt={alt || ""} className="my-4 w-full rounded-lg" />
        ),
      })}
    >
      {masked}
    </Markdown>
    </div>
  );
});

const PlainTextRenderer = memo(function PlainTextRenderer({ content }) {
  const quote = useContext(SourceReferenceContext);
  const value = content || "";
  let children;

  if (quote) {
    const start = value.indexOf(quote);
    children = start < 0 ? value : (
      <>
        {value.slice(0, start)}
        <span data-node-reference-hit style={{ backgroundColor: "#fef3c7", borderRadius: "4px" }}>
          {value.slice(start, start + quote.length)}
        </span>
        {value.slice(start + quote.length)}
      </>
    );
  } else {
    const { masked, highlights } = maskPlotHighlights(value);
    children = renderHighlightTokens(masked, highlights, "plain");
  }

  return (
    <p className="my-0 whitespace-pre-wrap break-words leading-8 tracking-wider text-gray-700">
      {children}
    </p>
  );
});

const NODE_TYPE_CONFIG = {
  outline: { icon: FileText, label: "大纲", bg: "bg-blue-100", text: "text-blue-600", badge: "text-blue-700" },
  volume: { icon: Layers, label: "卷", bg: "bg-indigo-100", text: "text-indigo-600", badge: "text-indigo-700" },
  plot: { icon: Zap, label: "情节", bg: "bg-orange-100", text: "text-orange-600", badge: "text-orange-700" },
  chapter: { icon: BookOpen, label: "章节", bg: "bg-green-100", text: "text-green-600", badge: "text-green-700" },
  character: { icon: User, label: "角色", bg: "bg-pink-100", text: "text-pink-600", badge: "text-pink-700" },
  worldbuilding: { icon: MapIcon, label: "世界观", bg: "bg-purple-100", text: "text-purple-600", badge: "text-purple-700" },
  note: { icon: StickyNote, label: "笔记", bg: "bg-fuchsia-100", text: "text-fuchsia-600", badge: "text-fuchsia-700" },
};

const DEFAULT_NODE_TYPE_CONFIG = { icon: FileText, label: "节点", bg: "bg-slate-100", text: "text-slate-600", badge: "text-slate-700" };

const detailScrollPositions = new Map();

function selectionQuoteFromContainer(container) {
  if (!container) return null;
  const selection = window.getSelection?.();
  if (!selection || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  const ancestor = range.commonAncestorContainer;
  if (ancestor !== container && !container.contains(ancestor)) return null;
  const selectedText = selection.toString().trim();
  if (!selectedText) return null;
  const rect = range.getBoundingClientRect?.() || { left: 0, top: 0, bottom: 0 };
  return {
    text: selectedText,
    x: rect.left,
    y: rect.bottom || rect.top,
  };
}

function hasTextSelectionInside(container) {
  const selection = window.getSelection?.();
  if (!selection?.toString().trim() || selection.rangeCount === 0) return false;
  const ancestor = selection.getRangeAt(0).commonAncestorContainer;
  return ancestor === container || container.contains(ancestor);
}

function useRememberedDetailScroll(nodeId) {
  const scrollRef = useRef(null);

  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !nodeId) return undefined;

    const savedScrollTop = detailScrollPositions.get(nodeId) || 0;
    const scheduleRestore = typeof requestAnimationFrame === "function"
      ? requestAnimationFrame
      : (callback) => setTimeout(callback, 0);
    const cancelRestore = typeof cancelAnimationFrame === "function"
      ? cancelAnimationFrame
      : clearTimeout;
    const frame = scheduleRestore(() => {
      el.scrollTop = savedScrollTop;
    });

    const rememberScroll = () => {
      detailScrollPositions.set(nodeId, el.scrollTop);
    };

    el.addEventListener("scroll", rememberScroll, { passive: true });
    return () => {
      cancelRestore(frame);
      rememberScroll();
      el.removeEventListener("scroll", rememberScroll);
    };
  }, [nodeId]);

  return scrollRef;
}

function textRangesIn(container, text) {
  if (!container || !text) return [];
  const ranges = [];
  const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
  let textNode = walker.nextNode();
  while (textNode) {
    let offset = textNode.nodeValue.indexOf(text);
    while (offset >= 0) {
      const range = document.createRange();
      range.setStart(textNode, offset);
      range.setEnd(textNode, offset + text.length);
      ranges.push(range);
      offset = textNode.nodeValue.indexOf(text, offset + text.length);
    }
    textNode = walker.nextNode();
  }
  return ranges;
}

function ChapterCharactersBar({ characters, onCharacterClick, stacked = false }) {
  if (!Array.isArray(characters) || characters.length === 0) return null;

  return (
    <div className={`flex w-full min-w-0 items-center gap-2 text-left ${stacked ? "" : "border-l border-gray-200 pl-4"}`}>
      <h2 className="shrink-0 text-xs font-semibold uppercase tracking-wide text-pink-700">出场角色</h2>
      <span className="shrink-0 text-xs text-pink-700/70">{characters.length} 人</span>
      <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto overscroll-x-contain pb-1">
        {characters.map((character, index) => {
          const name = character?.name;
          if (!name) return null;
          return (
            <button
              type="button"
              key={character?.id || `${name}-${index}`}
              aria-label={`定位角色：${name}`}
              onClick={() => onCharacterClick?.(name)}
              className="inline-flex max-w-32 shrink-0 items-center rounded-full border border-pink-200 bg-pink-50 px-2 py-1 text-xs font-medium text-pink-900 hover:border-pink-300 hover:bg-pink-100"
            >
              <span className="truncate">{name}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ChapterElementsBar({ elements, stacked = false }) {
  if (!Array.isArray(elements) || elements.length === 0) return null;

  return (
    <div className={`flex w-full min-w-0 items-center gap-2 text-left ${stacked ? "" : "border-l border-gray-200 pl-4"}`}>
      <h2 className="shrink-0 text-xs font-semibold uppercase tracking-wide text-amber-700">本章元素</h2>
      <span className="shrink-0 text-xs text-amber-700/70">{elements.length} 项</span>
      <div className="flex min-w-0 flex-1 gap-1.5 overflow-x-auto overscroll-x-contain pb-1">
        {elements.map((element, index) => {
          const title = element?.title || element?.content || `元素 ${index + 1}`;
          const content = element?.content || "";
          return (
            <span
              key={element?.id || `${title}-${index}`}
              className="inline-flex max-w-40 shrink-0 items-center rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-xs font-medium text-amber-900"
              title={content || title}
            >
              <span className="truncate">{title}</span>
            </span>
          );
        })}
      </div>
    </div>
  );
}

function InlineTextEditor({ initialText, label, saveLabel, onSave, onCancel, onEditingChange, appMode = false }) {
  const [value, setValue] = useState(initialText);
  const [saving, setSaving] = useState(false);
  const editorRef = useRef(null);
  const stableViewportHeightRef = useRef(typeof window === "undefined" ? 0 : window.innerHeight);
  const keyboardInset = useKeyboardInset(appMode);

  useEffect(() => {
    onEditingChange?.(true);
    return () => onEditingChange?.(false);
  }, [onEditingChange]);

  useLayoutEffect(() => {
    if (!appMode || keyboardInset <= 0) return undefined;
    const frame = requestAnimationFrame(() => {
      const editor = editorRef.current;
      const scrollContainer = editor?.closest('[data-testid="node-detail-scroll"]');
      if (!editor || !scrollContainer) return;
      const visualViewport = window.visualViewport;
      const currentVisualBottom = visualViewport
        ? visualViewport.offsetTop + visualViewport.height
        : window.innerHeight;
      stableViewportHeightRef.current = Math.max(stableViewportHeightRef.current, window.innerHeight, currentVisualBottom);
      const visibleBottom = Math.min(
        currentVisualBottom,
        stableViewportHeightRef.current - keyboardInset,
      );
      const delta = editorScrollDelta(editor.getBoundingClientRect(), visibleBottom);
      if (delta > 0) scrollContainer.scrollBy({ top: delta, behavior: "smooth" });
    });
    return () => cancelAnimationFrame(frame);
  }, [appMode, keyboardInset]);

  const handleSave = async () => {
    setSaving(true);
    try {
      const saved = await onSave(value);
      if (saved !== false) onCancel();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div ref={editorRef} className="space-y-2" data-inline-editor-active="true">
      <textarea
        autoFocus
        aria-label={label}
        value={value}
        onChange={(event) => setValue(event.target.value)}
        className="min-h-28 w-full resize-y rounded-md border border-blue-300 bg-white px-3 py-2 text-sm leading-relaxed text-slate-800 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
      />
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-slate-100">
          取消
        </button>
        <button type="button" aria-label={saveLabel} disabled={saving} onClick={handleSave} className="rounded bg-blue-500 px-3 py-1 text-xs font-medium text-white hover:bg-blue-600 disabled:opacity-50">
          {saving ? "保存中..." : "保存"}
        </button>
      </div>
    </div>
  );
}

function EditableParagraph({ text, onSave, onEditingChange, editing, onStartEditing, onStopEditing, plainText = false, appMode = false }) {
  if (editing) {
    return (
      <InlineTextEditor
        initialText={text}
        label="编辑段落内容"
        saveLabel="保存段落"
        onSave={onSave}
        onCancel={onStopEditing}
        onEditingChange={onEditingChange}
        appMode={appMode}
      />
    );
  }

  return (
    <div className="group relative rounded-md transition-colors hover:bg-blue-50/60">
      <div
        role="button"
        tabIndex={0}
        aria-label="编辑段落"
        onClick={(event) => {
          if (!hasTextSelectionInside(event.currentTarget)) onStartEditing();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            onStartEditing();
          }
        }}
        className="cursor-text rounded-md outline-none focus:ring-2 focus:ring-blue-200"
      >
        {plainText ? <PlainTextRenderer content={text} /> : <MarkdownRenderer content={text} />}
      </div>
      <Pencil className="pointer-events-none absolute right-1 top-1 h-3.5 w-3.5 text-blue-400 opacity-0 transition-opacity group-hover:opacity-100" />
    </div>
  );
}

function InlineDiffHunk({ hunk, onAccept, onReject, onEditNew, onEditingChange, editingNew, onStartEditing, onStopEditing, readOnly = false, appMode = false }) {
  const type = hunk.type || "replace";
  const headerActions = !readOnly ? (
    <>
      <button
        type="button"
        aria-label="保留修改"
        onClick={onAccept}
        className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-50"
      >
        <Check className="h-3.5 w-3.5" />
        保留修改
      </button>
      <button
        type="button"
        aria-label="撤回修改"
        onClick={onReject}
        className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
      >
        <Undo2 className="h-3.5 w-3.5" />
        撤回修改
      </button>
    </>
  ) : null;
  return (
    <section data-testid="inline-diff-hunk" className="my-2 overflow-visible">
      <div className="space-y-1">
        {editingNew ? (
          <>
            {headerActions ? <div className="flex items-center justify-end gap-1 rounded-t-lg bg-slate-100 px-2 py-1">{headerActions}</div> : null}
            <div>
              <div className="mb-1 text-[11px] text-emerald-700">新文</div>
              <InlineTextEditor
                initialText={hunk.new_text || ""}
                label="编辑新文内容"
                saveLabel="保存新文"
                onSave={onEditNew}
                onCancel={onStopEditing}
                onEditingChange={onEditingChange}
                appMode={appMode}
              />
            </div>
          </>
        ) : (
          <div
            className={onEditNew && !readOnly && type !== "delete" ? "cursor-text" : ""}
            onClick={(event) => {
              if (!onEditNew || readOnly || type === "delete") return;
              if (event.target.closest('button, [role="button"]')) return;
              if (!event.target.closest('[data-testid="inline-diff-new"]')) return;
              if (!hasTextSelectionInside(event.currentTarget)) onStartEditing();
            }}
          >
            <InlineTextDiff
              oldText={hunk.old_text || ""}
              newText={hunk.new_text || ""}
              showOld={type !== "insert_after"}
              showNew={type !== "delete"}
              headerActions={headerActions}
            />
          </div>
        )}
      </div>
    </section>
  );
}

function NodeContentBody({ content, batches, onAcceptHunk, onRejectHunk, onEditParagraph, onEditHunkNew, onEditingChange, closeEditorOnOutside = false, readOnly = false, plainText = false, appMode = false }) {
  const quote = useContext(SourceReferenceContext);
  const [activeEditorKey, setActiveEditorKey] = useState(null);
  const pending = useMemo(() => pendingHunksFromBatches(batches), [batches]);
  const grouped = batches[0]?.grouping === "agent_replacements";
  const blocks = useMemo(() => grouped ? agentDiffBlocks(batches[0]) : buildStackedInlineDiffBlocks(batches), [batches, grouped]);
  useEffect(() => {
    if (!closeEditorOnOutside || !activeEditorKey) return undefined;
    const closeOnOutside = (event) => {
      if (event.target.closest?.('[data-inline-editor-active="true"]')) return;
      setActiveEditorKey(null);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    return () => document.removeEventListener("pointerdown", closeOnOutside);
  }, [activeEditorKey, closeEditorOnOutside]);
  if (quote) return plainText ? <PlainTextRenderer content={content} /> : <MarkdownRenderer content={content} />;
  if (!pending.length) {
    if (!content) return <p className="whitespace-pre-wrap">暂无内容</p>;
    if (!onEditParagraph || readOnly) return plainText ? <PlainTextRenderer content={content} /> : <MarkdownRenderer content={content} />;
    return (
      <div className="space-y-1">
        {splitParagraphs(content).map((paragraph, index) => (
          <EditableParagraph
            key={`editable-${index}`}
            text={paragraph}
            onSave={(nextText) => onEditParagraph(index + 1, nextText)}
            onEditingChange={onEditingChange}
            editing={activeEditorKey === `paragraph-${index}`}
            onStartEditing={() => setActiveEditorKey(`paragraph-${index}`)}
            onStopEditing={() => setActiveEditorKey(null)}
            plainText={plainText}
            appMode={appMode}
          />
        ))}
      </div>
    );
  }

  if (grouped) {
    const currentCharacters = Array.from(contentAfterBatches(batches));
    const renderUnchanged = (block, blockIndex) => {
      let position = block.currentStart;
      return splitParagraphs(block.text).map((text, index) => {
        const start = position;
        position += Array.from(text).length;
        const end = position;
        position += 2;
        const wholeParagraph = (start === 0 || currentCharacters.slice(start - 2, start).join("") === "\n\n")
          && (end === currentCharacters.length || currentCharacters.slice(end, end + 2).join("") === "\n\n");
        const key = `unchanged-${blockIndex}-${index}`;
        const paragraphIndex = currentCharacters.slice(0, start).join("").split("\n\n").length;
        return <span key={key}>
          {index > 0 ? "\n\n" : null}
          {text && wholeParagraph ? (onEditParagraph && !readOnly
            ? <EditableParagraph text={text} plainText={plainText} appMode={appMode}
              onSave={(nextText) => onEditParagraph(paragraphIndex, nextText)}
              onEditingChange={onEditingChange} editing={activeEditorKey === key}
              onStartEditing={() => setActiveEditorKey(key)} onStopEditing={() => setActiveEditorKey(null)} />
            : plainText ? <PlainTextRenderer content={text} /> : <MarkdownRenderer content={text} />)
            : text}
        </span>;
      });
    };
    return <div className="whitespace-pre-wrap leading-relaxed">
      {blocks.map((block, index) => block.kind === "text"
        ? <span key={`text-${index}`}>{renderUnchanged(block, index)}</span>
        : <InlineDiffHunk
          key={`group-${block.index}`} hunk={block.hunk} readOnly={readOnly}
          onAccept={() => onAcceptHunk(0, block.index)}
          onReject={() => onRejectHunk(0, block.index)}
          onEditNew={onEditHunkNew ? (text) => onEditHunkNew(block.index, text, true) : undefined}
          onEditingChange={onEditingChange}
          editingNew={activeEditorKey === `group-${block.index}`}
          onStartEditing={() => setActiveEditorKey(`group-${block.index}`)}
          onStopEditing={() => setActiveEditorKey(null)} appMode={appMode}
        />)}
    </div>;
  }

  let currentParagraphIndex = 0;
  return (
    <div className="space-y-1">
      {blocks.map((block, index) => {
        if (block.kind === "paragraph") {
          currentParagraphIndex += 1;
          const paragraphIndex = currentParagraphIndex;
          return onEditParagraph && !readOnly ? (
            <EditableParagraph
              key={`p-${index}`}
              text={block.text}
              onSave={(nextText) => onEditParagraph(paragraphIndex, nextText)}
              onEditingChange={onEditingChange}
              editing={activeEditorKey === `paragraph-${index}`}
              onStartEditing={() => setActiveEditorKey(`paragraph-${index}`)}
              onStopEditing={() => setActiveEditorKey(null)}
              plainText={plainText}
              appMode={appMode}
            />
          ) : plainText
            ? <PlainTextRenderer key={`p-${index}`} content={block.text} />
            : <MarkdownRenderer key={`p-${index}`} content={block.text} />;
        }
        if ((block.hunk.type || "replace") !== "delete") {
          currentParagraphIndex += Math.max(1, splitParagraphs(block.hunk.new_text || "").length);
        }
        const displayedParagraphIndex = currentParagraphIndex;
        return (
          <InlineDiffHunk
            key={`h-${block.batchIndex}-${block.hunkIndex}`}
            hunk={block.hunk}
            readOnly={readOnly}
            onAccept={() => onAcceptHunk(block.batchIndex, block.hunkIndex)}
            onReject={() => onRejectHunk(block.batchIndex, block.hunkIndex)}
            onEditNew={onEditHunkNew ? (nextText) => onEditHunkNew(displayedParagraphIndex, nextText) : undefined}
            onEditingChange={onEditingChange}
            editingNew={activeEditorKey === `hunk-${block.batchIndex}-${block.hunkIndex}`}
            onStartEditing={() => setActiveEditorKey(`hunk-${block.batchIndex}-${block.hunkIndex}`)}
            onStopEditing={() => setActiveEditorKey(null)}
            appMode={appMode}
          />
        );
      })}
    </div>
  );
}

function ChapterReadingView({ node, scrollRef, isFullscreen = false, appMode = false, onTextSelect, batches = [], notesBatches = [], onAcceptHunk, onRejectHunk, onEditParagraph, onEditHunkNew, onInlineEditingChange, onAcceptNotesHunk, onRejectNotesHunk, readOnlyDiff = false, previousChapter, nextChapter, onChapterNavigate }) {
  const generation = node.extra_data?.last_generation;
  const evaluations = generation?.sync_evaluations || [];
  const latestEvaluation = evaluations[evaluations.length - 1];
  const wordCount = (node.content || "").replace(/\s+/g, "").length;
  const chapterElements = node.extra_data?.chapter_elements || [];
  const chapterCharacters = node.extra_data?.characters || [];
  const characterOccurrenceRef = useRef({ nodeId: node.id, nextIndexByName: new Map() });
  const swipeStartRef = useRef(null);

  const [metaExpanded, setMetaExpanded] = useState(false);
  const hasChapterMeta = chapterCharacters.length > 0 || chapterElements.length > 0;
  const pendingNotesCount = useMemo(() => pendingHunksFromBatches(notesBatches).length, [notesBatches]);

  const handleTouchStart = (event) => {
    if (!appMode) return;
    const touch = event.touches[0];
    swipeStartRef.current = touch ? { x: touch.clientX, y: touch.clientY } : null;
  };

  const handleTouchEnd = (event) => {
    if (!appMode) return;
    const start = swipeStartRef.current;
    const touch = event.changedTouches[0];
    swipeStartRef.current = null;
    if (!start || !touch) return;

    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    if (Math.abs(dx) < 56 || Math.abs(dy) > 40) return;
    const targetChapter = dx < 0 ? nextChapter : previousChapter;
    if (targetChapter) onChapterNavigate?.(targetChapter);
  };

  const handleCharacterClick = (name) => {
    const scrollContainer = scrollRef.current;
    const ranges = textRangesIn(scrollContainer, name);
    if (!ranges.length) return;

    if (characterOccurrenceRef.current.nodeId !== node.id) {
      characterOccurrenceRef.current = { nodeId: node.id, nextIndexByName: new Map() };
    }
    const nextIndex = characterOccurrenceRef.current.nextIndexByName.get(name) || 0;
    const range = ranges[nextIndex % ranges.length];
    characterOccurrenceRef.current.nextIndexByName.set(name, (nextIndex + 1) % ranges.length);

    const selection = window.getSelection?.();
    selection?.removeAllRanges?.();
    selection?.addRange?.(range);

    const rangeRect = range.getBoundingClientRect?.();
    const containerRect = scrollContainer.getBoundingClientRect?.();
    if (rangeRect && containerRect && typeof scrollContainer.scrollTo === "function") {
      scrollContainer.scrollTo({
        top: scrollContainer.scrollTop + rangeRect.top - containerRect.top - scrollContainer.clientHeight / 2,
        behavior: "smooth",
      });
    } else {
      range.startContainer.parentElement?.scrollIntoView?.({ block: "center", behavior: "smooth" });
    }
  };

  return (
    <>
      <div data-testid="chapter-detail-header" className="shrink-0 border-b border-amber-200 bg-amber-50 text-left">
        {appMode ? (
          <div className="mx-auto flex max-w-6xl flex-col gap-1 px-6 py-2">
            <div className="flex items-center gap-2">
              <h1 className="min-w-0 flex-1 truncate text-sm font-bold text-gray-900">
                {node.label}
              </h1>
              {hasChapterMeta && (
                <button
                  type="button"
                  aria-label={metaExpanded ? "收起详情" : "展开详情"}
                  onClick={() => setMetaExpanded((value) => !value)}
                  className="shrink-0 rounded-md px-1.5 py-0.5 text-[10px] text-slate-500 hover:bg-amber-100"
                >
                  {metaExpanded ? "收起详情" : "展开详情"}
                </button>
              )}
            </div>
            <div className="flex items-center justify-start gap-2 text-gray-500">
              <span className="text-[10px]">{wordCount} 字</span>
              {latestEvaluation && (
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] ${
                    latestEvaluation.passed
                      ? "bg-emerald-100 text-emerald-700"
                      : "bg-amber-100 text-amber-700"
                  }`}
                >
                  {latestEvaluation.passed ? "与画布规划同步" : "同步检查未通过"}
                </span>
              )}
              {generation && (
                <span className="text-[10px]">自动修订 {Math.max(0, evaluations.length - 1)} 次</span>
              )}
            </div>
            {hasChapterMeta && metaExpanded && (
              <div className="flex flex-col gap-1.5">
                <ChapterCharactersBar stacked characters={chapterCharacters} onCharacterClick={handleCharacterClick} />
                <ChapterElementsBar stacked elements={chapterElements} />
              </div>
            )}
          </div>
        ) : (
        <div className={`${isFullscreen ? "px-16" : "px-8"} mx-auto flex min-h-20 max-w-6xl items-center gap-5 overflow-hidden py-3`}>
          <div className="min-w-48 shrink-0">
            <h1 className={`${isFullscreen ? "text-2xl" : "text-xl"} truncate font-bold text-gray-900`}>
              {node.label}
            </h1>
            <div className="mt-1.5 flex items-center justify-start gap-2 text-xs text-gray-500">
              <span>{wordCount} 字</span>
              {latestEvaluation && (
                <span
                  className={`rounded-full px-2 py-0.5 ${
                    latestEvaluation.passed
                      ? "bg-emerald-100 text-emerald-700"
                      : "bg-amber-100 text-amber-700"
                  }`}
                >
                  {latestEvaluation.passed ? "与画布规划同步" : "同步检查未通过"}
                </span>
              )}
              {generation && (
                <span>自动修订 {Math.max(0, evaluations.length - 1)} 次</span>
              )}
            </div>
          </div>
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <ChapterCharactersBar characters={chapterCharacters} onCharacterClick={handleCharacterClick} />
            <ChapterElementsBar elements={chapterElements} />
          </div>
        </div>
        )}
      </div>

      <div className="relative flex min-h-0 flex-1">
      {!appMode && (
        <>
          <button
            type="button"
            title="上一章"
            disabled={!previousChapter}
            onClick={() => previousChapter && onChapterNavigate?.(previousChapter)}
            className="absolute left-3 top-1/2 z-10 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full border border-amber-200 bg-white/90 text-gray-600 shadow-sm hover:bg-amber-50 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <ChevronLeft className="h-5 w-5" />
          </button>
          <button
            type="button"
            title="下一章"
            disabled={!nextChapter}
            onClick={() => nextChapter && onChapterNavigate?.(nextChapter)}
            className="absolute right-3 top-1/2 z-10 flex h-10 w-10 -translate-y-1/2 items-center justify-center rounded-full border border-amber-200 bg-white/90 text-gray-600 shadow-sm hover:bg-amber-50 disabled:cursor-not-allowed disabled:opacity-30"
          >
            <ChevronRight className="h-5 w-5" />
          </button>
        </>
      )}
      <div
        ref={scrollRef}
        onMouseUp={onTextSelect}
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
        data-testid="node-detail-scroll"
        className={`flex-1 touch-pan-y overflow-y-auto bg-amber-50 ${appMode ? "pb-32" : ""}`}
      >
        <details className="mx-auto max-w-3xl border-b border-amber-200 px-8 py-4">
          <summary className="cursor-pointer font-medium text-amber-900">章节笔记</summary>
          {pendingNotesCount > 0 && !readOnlyDiff && (
            <div className="mt-2 flex items-center gap-1">
              <button type="button" aria-label="全部保留笔记" onClick={() => onAcceptNotesHunk?.()} className="rounded-md px-2 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-50">全部保留</button>
              <button type="button" aria-label="全部撤回笔记" onClick={() => onRejectNotesHunk?.()} className="rounded-md px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50">全部撤回</button>
            </div>
          )}
          <div data-testid="chapter-notes" className="mt-3 break-words text-sm leading-relaxed text-gray-700">
            {(node.notes || pendingNotesCount > 0) ? (
              <NodeContentBody
                content={node.notes}
                batches={notesBatches}
                onAcceptHunk={onAcceptNotesHunk}
                onRejectHunk={onRejectNotesHunk}
                readOnly={readOnlyDiff}
              />
            ) : "暂无章节笔记"}
          </div>
        </details>
        <div data-testid="chapter-body" className={`${isFullscreen ? "max-w-5xl px-6 py-10 sm:px-12 sm:py-16" : "max-w-3xl px-8 py-12"} mx-auto`}>
          <div className={`${isFullscreen ? "prose-xl" : "prose-lg"} prose max-w-none`}>
            <div className={`${isFullscreen ? "text-xl leading-loose" : "text-lg leading-relaxed"} text-gray-800`}>
              <NodeContentBody
                key={`chapter-body-${node.id}`}
                content={node.content}
                batches={batches}
                onAcceptHunk={onAcceptHunk}
                onRejectHunk={onRejectHunk}
                onEditParagraph={onEditParagraph}
                onEditHunkNew={onEditHunkNew}
                onEditingChange={onInlineEditingChange}
                closeEditorOnOutside
                readOnly={readOnlyDiff}
                plainText
                appMode={appMode}
              />
            </div>
          </div>

          {latestEvaluation && (
            <div className="mt-16 pt-8 border-t border-gray-200">
              <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
                同步检查
              </h3>
              {latestEvaluation.plan_alignment?.completed?.length > 0 && (
                <div className="mt-6">
                  <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                    已完成的规划
                  </h4>
                  <ul className="space-y-1">
                    {latestEvaluation.plan_alignment.completed.map((item, i) => (
                      <li key={i} className="text-sm text-gray-600 flex items-start gap-2">
                        <span className="text-green-500 mt-1">•</span>
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {latestEvaluation.plan_alignment?.missing?.length > 0 && (
                <div className="mt-6">
                  <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                    尚未完成的规划
                  </h4>
                  <ul className="space-y-1">
                    {latestEvaluation.plan_alignment.missing.map((item, i) => (
                      <li key={i} className="text-sm text-gray-600 flex items-start gap-2">
                        <span className="text-amber-500 mt-1">•</span>
                        {item}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
      </div>
    </>
  );
}

function StorylinesPanel({ storylines }) {
  if (!Array.isArray(storylines) || storylines.length === 0) return null;

  return (
    <div data-testid="character-storylines" className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-pink-700">发展线</h4>
        <span className="text-xs text-pink-700/70">{storylines.length} 条</span>
      </div>
      <div className="space-y-3">
        {storylines.map((line, index) => {
          const name = line?.name || `线 ${index + 1}`;
          const steps = Array.isArray(line?.body) ? line.body : [];
          return (
            <section
              key={`${name}-${index}`}
              className="rounded-lg border border-pink-200 bg-pink-50/60 p-4"
            >
              <h5 className="text-sm font-semibold text-pink-900">{name}</h5>
              {line?.description ? (
                <p className="mt-1 text-sm leading-relaxed text-pink-800/80">{line.description}</p>
              ) : null}
              {steps.length > 0 && (
                <ol className="mt-3 space-y-2">
                  {steps.map((step, stepIndex) => (
                    <li key={`${name}-step-${stepIndex}`} className="flex gap-3 text-sm text-gray-800">
                      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-pink-200 text-[11px] font-semibold text-pink-900">
                        {stepIndex + 1}
                      </span>
                      <span className="leading-relaxed">{step}</span>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}

function DefaultNodeView({ node, scrollRef, onTextSelect, batches = [], onAcceptHunk, onRejectHunk, onEditParagraph, onEditHunkNew, onInlineEditingChange, readOnlyDiff = false, appMode = false, previousNode, nextNode, onNavigate }) {
  const config = NODE_TYPE_CONFIG[node.type] || DEFAULT_NODE_TYPE_CONFIG;
  const Icon = config.icon;
  const swipeStartRef = useRef(null);
  const pendingCount = useMemo(() => pendingHunksFromBatches(batches).length, [batches]);

  const handleTouchStart = (event) => {
    const touch = event.touches[0];
    swipeStartRef.current = touch ? { x: touch.clientX, y: touch.clientY } : null;
  };

  const handleTouchEnd = (event) => {
    const start = swipeStartRef.current;
    const touch = event.changedTouches[0];
    swipeStartRef.current = null;
    if (!start || !touch) return;
    const dx = touch.clientX - start.x;
    const dy = touch.clientY - start.y;
    if (Math.abs(dx) < 56 || Math.abs(dy) > 40) return;
    const target = dx < 0 ? nextNode : previousNode;
    if (target) onNavigate?.(target);
  };

  return (
    <div ref={scrollRef} onMouseUp={onTextSelect} onTouchStart={appMode ? handleTouchStart : undefined} onTouchEnd={appMode ? handleTouchEnd : undefined} data-testid="node-detail-scroll" className={`flex-1 overflow-y-auto ${appMode ? "pb-32" : ""}`}>
      <div className="p-6 space-y-6">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${config.bg}`}>
            <Icon className={`w-5 h-5 ${config.text}`} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-gray-900">{node.label}</h3>
            <span className={`text-xs px-2 py-0.5 rounded-full ${config.bg} ${config.badge}`}>
              {config.label}
            </span>
          </div>
        </div>

        {(node.content || pendingCount > 0) && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              内容
            </h4>
            <div className="text-sm text-gray-700 leading-relaxed bg-gray-50 rounded-lg p-4">
              <NodeContentBody
                key={`node-body-${node.id}`}
                content={node.content}
                batches={batches}
                onAcceptHunk={onAcceptHunk}
                onRejectHunk={onRejectHunk}
                onEditParagraph={onEditParagraph}
                onEditHunkNew={onEditHunkNew}
                onEditingChange={onInlineEditingChange}
                closeEditorOnOutside
                readOnly={readOnlyDiff}
                appMode={appMode}
              />
            </div>
          </div>
        )}

        {node.type === "character" && (
          <StorylinesPanel storylines={node.extra_data?.storylines || []} />
        )}

        {node.extra_data && Object.entries(node.extra_data).filter(([key]) => key !== "storylines").length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              额外信息
            </h4>
            <div className="bg-gray-50 rounded-lg p-4 space-y-2">
              {Object.entries(node.extra_data)
                .filter(([key]) => key !== "storylines")
                .map(([key, value]) => (
                <div key={key} className="flex items-start gap-2">
                  <span className="text-xs font-medium text-gray-500 min-w-[80px]">
                    {key}:
                  </span>
                  <span className="text-sm text-gray-700">
                    {typeof value === "object" ? JSON.stringify(value, null, 2) : String(value)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function EditView({
  title,
  content,
  notes,
  isChapter,
  chapterElements,
  onTitleChange,
  onContentChange,
  onNotesChange,
  onChapterElementsChange,
  isCharacter,
  storylines,
  onStorylinesChange,
  initialContentScrollRatio = 0,
}) {
  const positionContentEditor = useCallback((textarea) => {
    if (!textarea) return;
    const maxScrollTop = Math.max(0, textarea.scrollHeight - textarea.clientHeight);
    textarea.scrollTop = maxScrollTop * initialContentScrollRatio;
  }, [initialContentScrollRatio]);

  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-4">
      <div>
        <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">标题</label>
        <input
          value={title}
          onChange={(e) => onTitleChange(e.target.value)}
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
      </div>
      <div>
        <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">内容（支持 Markdown）</label>
        <textarea
          ref={positionContentEditor}
          onLoad={(event) => positionContentEditor(event.currentTarget)}
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
          className="w-full min-h-[360px] border border-gray-300 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none resize-y font-mono"
        />
      </div>
      {isChapter && (
        <div>
          <label htmlFor="chapter-notes-editor" className="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
            章节笔记（支持 Markdown）
          </label>
          <textarea
            id="chapter-notes-editor"
            value={notes}
            onChange={(e) => onNotesChange(e.target.value)}
            className="w-full min-h-[180px] border border-gray-300 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none resize-y font-mono"
          />
        </div>
      )}
      {isChapter && (
        <div data-testid="chapter-elements-editor">
          <div className="flex items-center justify-between mb-2">
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide">本章元素</label>
            <span className="text-xs text-gray-400">{chapterElements.length} 项</span>
          </div>
          <div className="space-y-3">
            {chapterElements.map((el, index) => (
              <div key={el.id || `new-${index}`} className="rounded-lg border border-gray-200 p-3 space-y-2 bg-gray-50/50">
                <div className="flex items-start gap-2">
                  <input
                    value={el.title}
                    onChange={(e) => onChapterElementsChange(chapterElements.map((x, i) => (i === index ? { ...x, title: e.target.value } : x)))}
                    placeholder="元素标题"
                    className="flex-1 border border-gray-300 rounded-md px-2 py-1 text-sm focus:border-blue-500 focus:outline-none bg-white"
                  />
                  <button
                    type="button"
                    onClick={() => onChapterElementsChange(chapterElements.filter((_, i) => i !== index))}
                    title="删除元素"
                    className="p-1 rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
                <textarea
                  value={el.content}
                  onChange={(e) => onChapterElementsChange(chapterElements.map((x, i) => (i === index ? { ...x, content: e.target.value } : x)))}
                  placeholder="元素内容"
                  className="w-full min-h-[60px] border border-gray-300 rounded-md px-2 py-1 text-sm focus:border-blue-500 focus:outline-none resize-y bg-white"
                />
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={() => onChapterElementsChange([...chapterElements, { title: "", content: "" }])}
            className="mt-2 inline-flex items-center gap-1 text-sm text-blue-600 hover:text-blue-700"
          >
            <Plus className="w-4 h-4" />
            添加元素
          </button>
        </div>
      )}
      {isCharacter && (
        <div data-testid="storylines-editor">
          <div className="flex items-center justify-between mb-2">
            <label className="block text-xs font-semibold text-gray-500 uppercase tracking-wide">发展线</label>
            <span className="text-xs text-gray-400">{storylines.length} 条</span>
          </div>
          <div className="space-y-3">
            {storylines.map((line, index) => (
              <div key={`storyline-${index}`} className="rounded-lg border border-pink-200 p-3 space-y-2 bg-pink-50/40">
                <div className="flex items-start gap-2">
                  <input
                    value={line.name}
                    onChange={(e) => onStorylinesChange(storylines.map((x, i) => (i === index ? { ...x, name: e.target.value } : x)))}
                    placeholder="线名，如力量线"
                    className="flex-1 border border-gray-300 rounded-md px-2 py-1 text-sm focus:border-blue-500 focus:outline-none bg-white"
                  />
                  <button
                    type="button"
                    onClick={() => onStorylinesChange(storylines.filter((_, i) => i !== index))}
                    title="删除发展线"
                    className="p-1 rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
                <textarea
                  value={line.description}
                  onChange={(e) => onStorylinesChange(storylines.map((x, i) => (i === index ? { ...x, description: e.target.value } : x)))}
                  placeholder="该线的说明"
                  className="w-full min-h-[48px] border border-gray-300 rounded-md px-2 py-1 text-sm focus:border-blue-500 focus:outline-none resize-y bg-white"
                />
                <textarea
                  value={Array.isArray(line.body) ? line.body.join("\n") : ""}
                  onChange={(e) => onStorylinesChange(storylines.map((x, i) => (
                    i === index ? { ...x, body: e.target.value.split("\n") } : x
                  )))}
                  placeholder="轨迹节点，一行一项"
                  className="w-full min-h-[80px] border border-gray-300 rounded-md px-2 py-1 text-sm focus:border-blue-500 focus:outline-none resize-y bg-white font-mono"
                />
              </div>
            ))}
          </div>
          <button
            type="button"
            onClick={() => onStorylinesChange([...storylines, { name: "", description: "", body: [] }])}
            className="mt-2 inline-flex items-center gap-1 text-sm text-pink-700 hover:text-pink-800"
          >
            <Plus className="w-4 h-4" />
            添加发展线
          </button>
        </div>
      )}
    </div>
  );
}

function NodeDetailDrawerInner({ appMode, node, contentDiff, notesDiff, agentRunning, onClose, onUpdate, onContentDiffDecision, onNotesDiffDecision, onAddContext, onContentDiffChange, onNotesDiffChange, chapterNodes, navigationNodes, onChapterNavigate, onEditingChange }) {
  const orderedChapterNodes = useMemo(
    () => [...chapterNodes].sort((left, right) => compareSiblings(
      { id: left.id, data: left },
      { id: right.id, data: right },
    )),
    [chapterNodes],
  );
  const isChapter = node.type === "chapter";
  const isCharacter = node.type === "character";
  const [isEditing, setIsEditing] = useState(false);
  const [inlineEditingCount, setInlineEditingCount] = useState(0);
  const [editContentScrollRatio, setEditContentScrollRatio] = useState(0);
  const returnToReadingPositionRef = useRef(false);
  const readingScrollRatioRef = useRef(0);
  const [editTitle, setEditTitle] = useState(node.label);
  const [editContent, setEditContent] = useState(node.content || "");
  const [editNotes, setEditNotes] = useState(node.notes || "");
  const [editChapterElements, setEditChapterElements] = useState(() =>
    isChapter ? (node.extra_data?.chapter_elements || []).map((el) => ({ ...el })) : []
  );
  const [editStorylines, setEditStorylines] = useState(() =>
    isCharacter
      ? (node.extra_data?.storylines || []).map((line) => ({
          name: line.name || "",
          description: line.description || "",
          body: Array.isArray(line.body) ? [...line.body] : [],
        }))
      : []
  );
  const [saving, setSaving] = useState(false);
  const [copyStatus, setCopyStatus] = useState("idle");
  const [isFullscreen, setIsFullscreen] = useState(appMode);
  const [selectionAction, setSelectionAction] = useState(null);
  const [diffBatches, setDiffBatches] = useState(() => hydrateDiffBatches(node.content || "", contentDiff).batches);
  const [notesDiffBatches, setNotesDiffBatches] = useState(() => hydrateDiffBatches(node.notes || "", notesDiff).batches);
  const operationHistoryRef = useRef({ undo: [], redo: [], running: false });
  const detailScrollRef = useRememberedDetailScroll(isEditing ? null : node.id);

  const recordOperation = useCallback((operation) => {
    operationHistoryRef.current.undo.push(operation);
    operationHistoryRef.current.redo = [];
  }, []);

  const replayOperation = useCallback(async (direction) => {
    const history = operationHistoryRef.current;
    if (history.running) return;
    const source = direction === "undo" ? history.undo : history.redo;
    const destination = direction === "undo" ? history.redo : history.undo;
    const operation = source.pop();
    if (!operation) return;
    history.running = true;
    try {
      await operation[direction]();
      destination.push(operation);
    } catch {
      source.push(operation);
    } finally {
      history.running = false;
    }
  }, []);

  useEffect(() => {
    operationHistoryRef.current = { undo: [], redo: [], running: false };
  }, [node.id]);

  useEffect(() => {
    const handleHistoryShortcut = (event) => {
      if (!event.ctrlKey || event.altKey || event.repeat || event.defaultPrevented) return;
      const target = event.target;
      if (target instanceof Element && target.closest("input, textarea, [contenteditable='true']")) return;
      const key = event.key.toLocaleLowerCase();
      const direction = key === "z" && !event.shiftKey
        ? "undo"
        : (key === "y" || (key === "z" && event.shiftKey) ? "redo" : null);
      if (!direction) return;
      event.preventDefault();
      replayOperation(direction);
    };
    document.addEventListener("keydown", handleHistoryShortcut);
    return () => document.removeEventListener("keydown", handleHistoryShortcut);
  }, [replayOperation]);
  useLayoutEffect(() => {
    if (isEditing || !returnToReadingPositionRef.current) return undefined;
    returnToReadingPositionRef.current = false;

    const scheduleRestore = typeof requestAnimationFrame === "function"
      ? requestAnimationFrame
      : (callback) => setTimeout(callback, 0);
    const cancelRestore = typeof cancelAnimationFrame === "function"
      ? cancelAnimationFrame
      : clearTimeout;
    const frame = scheduleRestore(() => {
      const reader = detailScrollRef.current;
      if (!reader) return;
      const maxScrollTop = Math.max(0, reader.scrollHeight - reader.clientHeight);
      const nextScrollTop = maxScrollTop * readingScrollRatioRef.current;
      reader.scrollTop = nextScrollTop;
      detailScrollPositions.set(node.id, nextScrollTop);
    });

    return () => cancelRestore(frame);
  }, [isEditing, node.id, detailScrollRef]);
  const handleInlineEditingChange = useCallback((editing) => {
    setInlineEditingCount((count) => Math.max(0, count + (editing ? 1 : -1)));
  }, []);
  useEffect(() => {
    onEditingChange?.(isEditing || inlineEditingCount > 0);
  }, [isEditing, inlineEditingCount, onEditingChange]);
  useEffect(() => () => onEditingChange?.(false), [onEditingChange]);
  useEffect(() => {
    if (appMode || !node.sourceReference || isEditing) return;
    const frame = requestAnimationFrame(() => detailScrollRef.current?.querySelector("[data-node-reference-hit]")?.scrollIntoView?.({ block: "center" }));
    return () => cancelAnimationFrame(frame);
  }, [node, appMode, isEditing, detailScrollRef]);

  const handleStartEditing = useCallback(() => {
    const reader = detailScrollRef.current;
    const maxScrollTop = reader
      ? Math.max(0, reader.scrollHeight - reader.clientHeight)
      : 0;
    const scrollRatio = maxScrollTop > 0 ? reader.scrollTop / maxScrollTop : 0;
    readingScrollRatioRef.current = scrollRatio;
    returnToReadingPositionRef.current = true;
    setEditContentScrollRatio(scrollRatio);
    setIsEditing(true);
  }, [detailScrollRef]);

  useEffect(() => {
    setIsFullscreen(appMode);
  }, [appMode]);

  useEffect(() => {
    setIsEditing(false);
    setCopyStatus("idle");
    setSelectionAction(null);
    setEditTitle(node.label);
    setEditContent(node.content || "");
    setEditNotes(node.notes || "");
    setEditChapterElements(
      node.type === "chapter"
        ? (node.extra_data?.chapter_elements || []).map((el) => ({ ...el }))
        : []
    );
    setEditStorylines(
      node.type === "character"
        ? (node.extra_data?.storylines || []).map((line) => ({
            name: line.name || "",
            description: line.description || "",
            body: Array.isArray(line.body) ? [...line.body] : [],
          }))
        : []
    );
  }, [appMode, node]);

  const handleCopyChapterContent = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(node.content || "");
      setCopyStatus("copied");
    } catch {
      setCopyStatus("failed");
    }
  }, [node.content]);

  useEffect(() => {
    setDiffBatches(hydrateDiffBatches(node.content || "", contentDiff).batches);
  }, [contentDiff]);

  useEffect(() => {
    setNotesDiffBatches(hydrateDiffBatches(node.notes || "", notesDiff).batches);
  }, [notesDiff]);

  useEffect(() => {
    if (!onAddContext) return undefined;
    const handleSelectionChange = () => {
      setSelectionAction(selectionQuoteFromContainer(detailScrollRef.current));
    };
    document.addEventListener("selectionchange", handleSelectionChange);
    return () => document.removeEventListener("selectionchange", handleSelectionChange);
  }, [onAddContext, node.id]);

  const handleSave = async () => {
    const payload = { title: editTitle, content: editContent, expected_content: node.content || "" };
    const previousPayload = {
      title: node.label,
      content: node.content || "",
      expected_content: editContent,
    };
    if (node.type === "chapter") {
      payload.notes = editNotes;
      payload.chapter_elements = editChapterElements
        .map((el) => ({ ...el }))
        .filter((el) => (el.title || "").trim() || (el.content || "").trim());
      previousPayload.notes = node.notes || "";
      previousPayload.chapter_elements = (node.extra_data?.chapter_elements || []).map((el) => ({ ...el }));
    }
    if (node.type === "character") {
      payload.storylines = editStorylines
        .map((line) => ({
          name: (line.name || "").trim(),
          description: (line.description || "").trim(),
          body: (Array.isArray(line.body) ? line.body : [])
            .map((step) => String(step).trim())
            .filter(Boolean),
        }))
        .filter((line) => line.name && line.body.length > 0);
      previousPayload.storylines = (node.extra_data?.storylines || []).map((line) => ({
        name: line.name || "",
        description: line.description || "",
        body: Array.isArray(line.body) ? [...line.body] : [],
      }));
    }
    setSaving(true);
    try {
      await onUpdate?.(node.id, payload);
      recordOperation({
        undo: () => onUpdate?.(node.id, previousPayload),
        redo: () => onUpdate?.(node.id, { ...payload, expected_content: previousPayload.content }),
      });
      setIsEditing(false);
    } catch {
      // 上层负责展示保存错误；保留编辑状态供用户处理冲突后重试。
    } finally {
      setSaving(false);
    }
  };

  const handleTextSelect = (event) => {
    const captured = selectionQuoteFromContainer(event.currentTarget);
    if (!captured) {
      setSelectionAction(null);
      return;
    }
    setSelectionAction({
      text: captured.text,
      x: Number.isFinite(event.clientX) ? event.clientX : captured.x,
      y: Number.isFinite(event.clientY) ? event.clientY : captured.y,
    });
  };

  const handleQuoteSelection = () => {
    if (!selectionAction?.text) return;
    onAddContext?.(node, selectionAction.text);
    setSelectionAction(null);
    window.getSelection?.()?.removeAllRanges?.();
  };

  const publishContentDiff = useCallback((baselineContent, currentContent, groupedDiff) => {
    if (groupedDiff) {
      setDiffBatches(hydrateDiffBatches(currentContent, groupedDiff).batches);
      onContentDiffChange?.(groupedDiff.hunks.length ? groupedDiff : null);
      return;
    }
    const hunks = buildContentDiffFromContents(baselineContent, currentContent);
    const batches = hunks.length ? [{ original_content: baselineContent, hunks }] : [];
    setDiffBatches(batches);
    if (hunks.length) {
      onContentDiffChange?.({
        original_content: baselineContent,
        current_content: currentContent,
        hunks,
        batches,
      });
    } else {
      onContentDiffChange?.(null);
    }
  }, [onContentDiffChange]);

  const writeContentDiffState = useCallback(async ({ expectedContent, expectedBaseline, nextBaseline, nextContent, nextDiff }) => {
    await onContentDiffDecision?.(node.id, {
      expected_content: expectedContent,
      expected_baseline: expectedBaseline,
      baseline_content: nextBaseline,
      current_content: nextContent,
      ...(nextDiff ? { groups: nextDiff.hunks.map(({ start_offset, old_text, new_text }) => ({ start_offset, old_text, new_text })) } : {}),
    });
    publishContentDiff(nextBaseline, nextContent, nextDiff);
  }, [node.id, onContentDiffDecision, publishContentDiff]);

  const persistContentDiff = async ({ expectedContent, expectedBaseline, nextBaseline, nextContent, nextDiff }) => {
    const previousDiff = diffBatches[0]?.grouping === "agent_replacements" ? {
      ...diffBatches[0], current_content: expectedContent,
    } : undefined;
    try {
      await writeContentDiffState({ expectedContent, expectedBaseline, nextBaseline, nextContent, nextDiff });
      recordOperation({
        undo: () => writeContentDiffState({
          expectedContent: nextContent,
          expectedBaseline: nextBaseline,
          nextBaseline: expectedBaseline,
          nextContent: expectedContent,
          nextDiff: previousDiff,
        }),
        redo: () => writeContentDiffState({
          expectedContent,
          expectedBaseline,
          nextBaseline,
          nextContent,
          nextDiff,
        }),
      });
      return true;
    } catch (error) {
      alert("处理正文修改失败：" + (error?.message || "未知错误"));
      return false;
    }
  };

  const applyHunkDecisions = async (nextBatches) => {
    if (diffBatches[0]?.grouping === "agent_replacements") {
      let nextDiff = diffBatches[0];
      for (let index = nextBatches[0].hunks.length - 1; index >= 0; index -= 1) {
        const status = nextBatches[0].hunks[index].status;
        if (status) nextDiff = decideAgentGroup(nextDiff, index, status === "accepted" ? "accept" : "reject");
      }
      return persistGroupedDiff(nextDiff);
    }
    // diffBatches 描述的是用户作决定前、Agent 已实际写入的正文。
    // 画布节点刷新带防抖，node.content 在短窗口内可能仍是修改前的旧值。
    const expectedContent = contentAfterBatches(diffBatches);
    const expectedBaseline = diffBatches[0]?.original_content ?? contentDiff?.original_content ?? "";
    const nextContent = contentAfterBatches(nextBatches);
    const nextBaseline = contentAfterBatches(setAllHunkStatusInBatches(nextBatches, "rejected"));
    return persistContentDiff({ expectedContent, expectedBaseline, nextBaseline, nextContent });
  };

  const persistGroupedDiff = (nextDiff) => persistContentDiff({
    expectedContent: contentAfterBatches(diffBatches),
    expectedBaseline: diffBatches[0].original_content,
    nextBaseline: nextDiff.original_content,
    nextContent: nextDiff.current_content,
    nextDiff,
  });

  const handleEditParagraph = async (paragraphIndex, nextText) => {
    const hasPendingDiff = pendingHunksFromBatches(diffBatches).length > 0;
    const currentContent = hasPendingDiff ? contentAfterBatches(diffBatches) : (node.content || "");
    const paragraphs = splitParagraphs(currentContent);
    if (paragraphIndex < 1 || paragraphIndex > paragraphs.length) return false;
    paragraphs[paragraphIndex - 1] = nextText;
    const nextContent = joinParagraphs(paragraphs);
    if (nextContent === currentContent) return true;

    if (hasPendingDiff && diffBatches[0]?.grouping !== "agent_replacements") {
      const expectedBaseline = diffBatches[0]?.original_content ?? contentDiff?.original_content ?? "";
      const baselineContent = contentAfterBatches(setAllHunkStatusInBatches(diffBatches, "rejected"));
      const committed = commitUserParagraphEdit(baselineContent, currentContent, paragraphIndex, nextText);
      return persistContentDiff({
        expectedContent: currentContent,
        expectedBaseline,
        nextBaseline: committed.baselineContent,
        nextContent: committed.currentContent,
      });
    }

    try {
      await onUpdate?.(node.id, { content: nextContent, expected_content: currentContent });
      recordOperation({
        undo: () => onUpdate?.(node.id, { content: currentContent, expected_content: nextContent }),
        redo: () => onUpdate?.(node.id, { content: nextContent, expected_content: currentContent }),
      });
      return true;
    } catch {
      return false;
    }
  };

  const handleEditHunkNew = (paragraphIndex, nextText, grouped = false) => {
    if (grouped) {
      const group = diffBatches[0].hunks[paragraphIndex];
      const committed = commitUserTextEdit(group.old_text, group.new_text, nextText);
      return persistGroupedDiff(decideAgentGroup(diffBatches[0], paragraphIndex, "update", {
        oldText: committed.baselineText, newText: committed.currentText,
      }));
    }
    const currentContent = contentAfterBatches(diffBatches);
    const baselineContent = contentAfterBatches(setAllHunkStatusInBatches(diffBatches, "rejected"));
    const currentParagraphs = splitParagraphs(currentContent);
    const baselineParagraphs = splitParagraphs(baselineContent);
    const position = paragraphIndex - 1;
    if (position < 0 || position >= currentParagraphs.length || position >= baselineParagraphs.length) return false;
    const committed = commitUserTextEdit(
      baselineParagraphs[position],
      currentParagraphs[position],
      nextText,
    );
    baselineParagraphs[position] = committed.baselineText;
    currentParagraphs[position] = committed.currentText;
    const nextBaseline = joinParagraphs(baselineParagraphs);
    const nextContent = joinParagraphs(currentParagraphs);
    const nextBatches = [{
      original_content: nextBaseline,
      hunks: buildContentDiffFromContents(nextBaseline, nextContent),
    }];
    return applyHunkDecisions(nextBatches);
  };

  const publishNotesDiff = useCallback((baselineNotes, currentNotes) => {
    const hunks = buildContentDiffFromContents(baselineNotes, currentNotes);
    const batches = hunks.length ? [{ original_content: baselineNotes, hunks }] : [];
    setNotesDiffBatches(batches);
    if (hunks.length) {
      onNotesDiffChange?.({
        original_content: baselineNotes,
        current_content: currentNotes,
        hunks,
        batches,
      });
    } else {
      onNotesDiffChange?.(null);
    }
  }, [onNotesDiffChange]);

  const writeNotesDiffState = useCallback(async ({ expectedNotes, expectedBaseline, nextBaseline, nextNotes }) => {
    await onNotesDiffDecision?.(node.id, {
      expected_notes: expectedNotes,
      expected_baseline: expectedBaseline,
      baseline_notes: nextBaseline,
      current_notes: nextNotes,
    });
    publishNotesDiff(nextBaseline, nextNotes);
  }, [node.id, onNotesDiffDecision, publishNotesDiff]);

  const applyNotesHunkDecisions = async (nextBatches) => {
    const expectedNotes = contentAfterBatches(notesDiffBatches);
    const expectedBaseline = notesDiffBatches[0]?.original_content ?? notesDiff?.original_content ?? "";
    const nextNotes = contentAfterBatches(nextBatches);
    const nextBaseline = contentAfterBatches(setAllHunkStatusInBatches(nextBatches, "rejected"));
    try {
      await writeNotesDiffState({ expectedNotes, expectedBaseline, nextBaseline, nextNotes });
      recordOperation({
        undo: () => writeNotesDiffState({
          expectedNotes: nextNotes,
          expectedBaseline: nextBaseline,
          nextBaseline: expectedBaseline,
          nextNotes: expectedNotes,
        }),
        redo: () => writeNotesDiffState({ expectedNotes, expectedBaseline, nextBaseline, nextNotes }),
      });
    } catch (error) {
      alert("处理笔记修改失败：" + (error?.message || "未知错误"));
    }
  };

  const handleAcceptNotesHunk = (batchIndex, hunkIndex) => {
    if (batchIndex == null) {
      applyNotesHunkDecisions(setAllHunkStatusInBatches(notesDiffBatches, "accepted"));
      return;
    }
    applyNotesHunkDecisions(setHunkStatusInBatches(notesDiffBatches, batchIndex, hunkIndex, "accepted"));
  };

  const handleRejectNotesHunk = (batchIndex, hunkIndex) => {
    if (batchIndex == null) {
      applyNotesHunkDecisions(setAllHunkStatusInBatches(notesDiffBatches, "rejected"));
      return;
    }
    applyNotesHunkDecisions(setHunkStatusInBatches(notesDiffBatches, batchIndex, hunkIndex, "rejected"));
  };

  const handleAcceptHunk = (batchIndex, hunkIndex) => {
    applyHunkDecisions(setHunkStatusInBatches(diffBatches, batchIndex, hunkIndex, "accepted"));
  };

  const handleRejectHunk = (batchIndex, hunkIndex) => {
    applyHunkDecisions(setHunkStatusInBatches(diffBatches, batchIndex, hunkIndex, "rejected"));
  };

  const handleAcceptAll = () => {
    applyHunkDecisions(setAllHunkStatusInBatches(diffBatches, "accepted"));
  };

  const handleRejectAll = () => {
    applyHunkDecisions(setAllHunkStatusInBatches(diffBatches, "rejected"));
  };

  const pendingDiffCount = pendingHunksFromBatches(diffBatches).length;
  const isDiffPreview = contentDiff?.preview === true && agentRunning !== false;
  const currentChapterIndex = isChapter
    ? orderedChapterNodes.findIndex((chapter) => chapter.id === node.id)
    : -1;
  const previousChapter = currentChapterIndex > 0
    ? orderedChapterNodes[currentChapterIndex - 1]
    : null;
  const nextChapter = currentChapterIndex >= 0
    ? orderedChapterNodes[currentChapterIndex + 1]
    : null;
  const orderedNodes = navigationNodes ?? orderedChapterNodes;
  const currentNodeIndex = orderedNodes.findIndex((item) => item.id === node.id);
  const previousNode = currentNodeIndex > 0 ? orderedNodes[currentNodeIndex - 1] : null;
  const nextNode = currentNodeIndex >= 0 ? orderedNodes[currentNodeIndex + 1] : null;

  return (
    <div
      data-testid="node-detail-drawer"
      className={`nodrag nopan nowheel select-text relative flex flex-col shadow-xl animate-in slide-in-from-left ${isChapter ? "bg-amber-50" : "bg-white"} ${
        isFullscreen
          ? "h-full w-full"
          : isEditing || isChapter || isCharacter
            ? "h-full w-[860px] max-w-[90vw]"
            : "h-full w-[420px] max-w-[90vw]"
      }`}
    >
      {selectionAction && onAddContext && (
        <button
          type="button"
          aria-label="引用此段"
          onPointerDown={(event) => event.preventDefault()}
          onMouseDown={(event) => event.preventDefault()}
          onClick={handleQuoteSelection}
          className="fixed z-[60] rounded-md bg-slate-800 px-3 py-1.5 text-xs font-medium text-white shadow-lg hover:bg-slate-700"
          style={{ left: Math.max(8, selectionAction.x + 8), top: Math.max(8, selectionAction.y + 8) }}
        >
          引用此段
        </button>
      )}
      <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">{isEditing ? "✏️" : isChapter ? "📖" : "📄"}</span>
          <span className="font-medium text-gray-800">
            {isEditing ? "编辑节点" : isChapter ? "章节阅读" : "节点详情"}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {!isEditing && pendingDiffCount > 0 && !isDiffPreview && (
            <div className="mr-1 flex items-center gap-1">
              <button
                type="button"
                aria-label="全部保留"
                onClick={handleAcceptAll}
                className="rounded-md px-2 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-50"
              >
                全部保留
              </button>
              <button
                type="button"
                aria-label="全部撤回"
                onClick={handleRejectAll}
                className="rounded-md px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
              >
                全部撤回
              </button>
            </div>
          )}
          {!isEditing && pendingDiffCount > 0 && isDiffPreview && (
            <span className="mr-1 rounded-full bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700">
              生成预览
            </span>
          )}
          {isEditing ? (
            <>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-3 py-1 rounded-md bg-blue-500 text-white text-sm hover:bg-blue-600 disabled:opacity-50 transition-colors"
              >
                {saving ? "保存中..." : "保存"}
              </button>
              <button
                onClick={() => setIsEditing(false)}
                className="px-3 py-1 rounded-md text-gray-500 text-sm hover:bg-gray-100 transition-colors"
              >
                取消
              </button>
            </>
          ) : (
            <>
              {isChapter && (
                <button
                  type="button"
                  onClick={handleCopyChapterContent}
                  className={`flex items-center gap-1 rounded-md px-2 py-1.5 text-xs transition-colors ${
                    copyStatus === "copied"
                      ? "bg-emerald-50 text-emerald-600"
                      : copyStatus === "failed"
                        ? "bg-red-50 text-red-600"
                        : "text-gray-500 hover:bg-amber-100 hover:text-amber-700"
                  }`}
                  title={copyStatus === "copied" ? "正文已复制" : copyStatus === "failed" ? "复制失败" : "复制正文"}
                  aria-label={copyStatus === "copied" ? "正文已复制" : copyStatus === "failed" ? "复制失败" : "复制正文"}
                >
                  {copyStatus === "copied" ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  <span>{copyStatus === "copied" ? "已复制" : copyStatus === "failed" ? "复制失败" : "复制正文"}</span>
                </button>
              )}
              {onUpdate && (
                <button
                  onClick={handleStartEditing}
                  className="p-1.5 rounded-md text-gray-400 hover:text-blue-500 hover:bg-blue-50 transition-colors"
                  title="编辑全文"
                  aria-label="编辑全文"
                >
                  <Pencil className="w-4 h-4" />
                </button>
              )}
            </>
          )}
          {!appMode && (
            <button
              onClick={() => setIsFullscreen((value) => !value)}
              className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
              title={isFullscreen ? "退出全屏" : "全屏查看"}
              aria-label={isFullscreen ? "退出全屏" : "全屏查看"}
            >
              {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
            </button>
          )}
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {isEditing ? (
        <EditView
          title={editTitle}
          content={editContent}
          notes={editNotes}
          isChapter={isChapter}
          chapterElements={editChapterElements}
          onTitleChange={setEditTitle}
          onContentChange={setEditContent}
          onNotesChange={setEditNotes}
          onChapterElementsChange={setEditChapterElements}
          isCharacter={isCharacter}
          storylines={editStorylines}
          onStorylinesChange={setEditStorylines}
          initialContentScrollRatio={editContentScrollRatio}
        />
      ) : isChapter ? (
        <ChapterReadingView
          node={node}
          scrollRef={detailScrollRef}
          isFullscreen={isFullscreen}
          appMode={appMode}
          onTextSelect={handleTextSelect}
          batches={diffBatches}
          notesBatches={notesDiffBatches}
          onAcceptHunk={handleAcceptHunk}
          onRejectHunk={handleRejectHunk}
          onEditParagraph={onUpdate ? handleEditParagraph : undefined}
          onEditHunkNew={onContentDiffDecision ? handleEditHunkNew : undefined}
          onInlineEditingChange={handleInlineEditingChange}
          onAcceptNotesHunk={handleAcceptNotesHunk}
          onRejectNotesHunk={handleRejectNotesHunk}
          readOnlyDiff={isDiffPreview}
          previousChapter={navigationNodes ? previousNode : previousChapter}
          nextChapter={navigationNodes ? nextNode : nextChapter}
          onChapterNavigate={onChapterNavigate}
        />
      ) : (
        <DefaultNodeView
          node={node}
          scrollRef={detailScrollRef}
          onTextSelect={handleTextSelect}
          batches={diffBatches}
          onAcceptHunk={handleAcceptHunk}
          onRejectHunk={handleRejectHunk}
          onEditParagraph={onUpdate ? handleEditParagraph : undefined}
          onEditHunkNew={onContentDiffDecision ? handleEditHunkNew : undefined}
          onInlineEditingChange={handleInlineEditingChange}
          readOnlyDiff={isDiffPreview}
          appMode={appMode}
          previousNode={previousNode}
          nextNode={nextNode}
          onNavigate={onChapterNavigate}
        />
      )}
      {!isChapter && !appMode && !isEditing && (
        <div className="pointer-events-none absolute inset-x-0 top-1/2 z-10 flex -translate-y-1/2 justify-between px-3">
          <button type="button" title="上一节点" disabled={!previousNode} onClick={() => previousNode && onChapterNavigate?.(previousNode)} className="pointer-events-auto flex h-10 w-10 items-center justify-center rounded-full border border-gray-200 bg-white/90 text-gray-600 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-30"><ChevronLeft className="h-5 w-5" /></button>
          <button type="button" title="下一节点" disabled={!nextNode} onClick={() => nextNode && onChapterNavigate?.(nextNode)} className="pointer-events-auto flex h-10 w-10 items-center justify-center rounded-full border border-gray-200 bg-white/90 text-gray-600 shadow-sm hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-30"><ChevronRight className="h-5 w-5" /></button>
        </div>
      )}
    </div>
  );
}

export default function NodeDetailDrawer({ appMode = false, node, contentDiff, notesDiff, agentRunning, onClose, onUpdate, onContentDiffDecision, onNotesDiffDecision, onAddContext, onContentDiffChange, onNotesDiffChange, chapterNodes = [], navigationNodes, onChapterNavigate, onEditingChange }) {
  if (!node) return null;

  return (
    <div className="absolute inset-0 z-50 flex justify-start">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      <SourceReferenceContext.Provider value={appMode ? null : node.sourceReference}>
        <NodeDetailDrawerInner appMode={appMode} node={node} contentDiff={contentDiff} notesDiff={notesDiff} agentRunning={agentRunning} onClose={onClose} onUpdate={onUpdate} onContentDiffDecision={onContentDiffDecision} onNotesDiffDecision={onNotesDiffDecision} onAddContext={onAddContext} onContentDiffChange={onContentDiffChange} onNotesDiffChange={onNotesDiffChange} chapterNodes={chapterNodes} navigationNodes={navigationNodes} onChapterNavigate={onChapterNavigate} onEditingChange={onEditingChange} />
      </SourceReferenceContext.Provider>
    </div>
  );
}
