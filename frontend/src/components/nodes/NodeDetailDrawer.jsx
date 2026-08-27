import { Children, useState, useEffect, useLayoutEffect, useRef } from "react";
import { X, Trash2, BookOpen, FileText, User, StickyNote, Map as MapIcon, Zap, Layers, Pencil, Pin, MessageSquarePlus, Plus, Maximize2, Minimize2, ChevronLeft, ChevronRight } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import AuthIllustrationImage, { isIllustrationApiPath } from "./AuthIllustrationImage";

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

function MarkdownRenderer({ content }) {
  const { masked, highlights } = maskPlotHighlights(content || "");
  const renderChildren = (children, keyPrefix) => renderMarkdownChildrenWithHighlights(children, highlights, keyPrefix);

  return (
    <div className="prose prose-sm max-w-none">
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => <h1 className="text-2xl font-bold mt-6 mb-3 text-gray-900">{renderChildren(children, "h1")}</h1>,
        h2: ({ children }) => <h2 className="text-xl font-bold mt-5 mb-2 text-gray-900">{renderChildren(children, "h2")}</h2>,
        h3: ({ children }) => <h3 className="text-lg font-semibold mt-4 mb-2 text-gray-800">{renderChildren(children, "h3")}</h3>,
        h4: ({ children }) => <h4 className="text-base font-semibold mt-3 mb-1 text-gray-800">{renderChildren(children, "h4")}</h4>,
        p: ({ children }) => <p className="mb-3 leading-relaxed text-gray-700">{renderChildren(children, "p")}</p>,
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
      }}
    >
      {masked}
    </Markdown>
    </div>
  );
}

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

function ChapterElementsBar({ elements }) {
  if (!Array.isArray(elements) || elements.length === 0) return null;

  return (
    <div className="mb-10 rounded-lg border border-amber-200 bg-amber-50/70 px-4 py-3 text-left">
      <div className="mb-2 flex items-center justify-between gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-amber-700">本章元素</h2>
        <span className="text-xs text-amber-700/70">{elements.length} 项</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {elements.map((element, index) => {
          const title = element?.title || element?.content || `元素 ${index + 1}`;
          const content = element?.content || "";
          return (
            <span
              key={element?.id || `${title}-${index}`}
              className="inline-flex max-w-full items-center rounded-full border border-amber-200 bg-white px-3 py-1 text-xs font-medium text-amber-900 shadow-sm"
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

function ChapterReadingView({ node, scrollRef, isFullscreen = false, onTextSelect }) {
  const generation = node.extra_data?.last_generation;
  const evaluations = generation?.sync_evaluations || [];
  const latestEvaluation = evaluations[evaluations.length - 1];
  const wordCount = (node.content || "").replace(/\s+/g, "").length;
  const chapterElements = node.extra_data?.chapter_elements || [];

  return (
    <div ref={scrollRef} onMouseUp={onTextSelect} data-testid="node-detail-scroll" className="flex-1 overflow-y-auto">
      <div className={`${isFullscreen ? "max-w-4xl px-16 py-16" : "max-w-2xl px-8 py-12"} mx-auto`}>
        <div className="text-center mb-12">
          <h1 className={`${isFullscreen ? "text-4xl" : "text-3xl"} font-serif font-bold text-gray-900 mb-2`}>
            {node.label}
          </h1>
          <div className="w-16 h-px bg-gray-300 mx-auto" />
          <div className="mt-3 flex items-center justify-center gap-2 text-xs text-gray-500">
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

        <ChapterElementsBar elements={chapterElements} />

        <div className={`${isFullscreen ? "prose-xl" : "prose-lg"} prose max-w-none font-serif`}>
          <div className={`${isFullscreen ? "text-xl leading-loose" : "text-lg leading-relaxed"} text-gray-800`}>
            {node.content ? <MarkdownRenderer content={node.content} /> : <p className="whitespace-pre-wrap">暂无内容</p>}
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

function DefaultNodeView({ node, scrollRef, onTextSelect }) {
  const config = NODE_TYPE_CONFIG[node.type] || DEFAULT_NODE_TYPE_CONFIG;
  const Icon = config.icon;

  return (
    <div ref={scrollRef} onMouseUp={onTextSelect} data-testid="node-detail-scroll" className="flex-1 overflow-y-auto">
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

        {node.content && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              内容
            </h4>
            <div className="text-sm text-gray-700 leading-relaxed bg-gray-50 rounded-lg p-4">
              <MarkdownRenderer content={node.content} />
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
  isChapter,
  chapterElements,
  onTitleChange,
  onContentChange,
  onChapterElementsChange,
  isCharacter,
  storylines,
  onStorylinesChange,
}) {
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
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
          className="w-full min-h-[360px] border border-gray-300 rounded-lg px-3 py-2 text-sm focus:border-blue-500 focus:outline-none resize-y font-mono"
        />
      </div>
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

function NodeDetailDrawerInner({ node, onClose, onDelete, onUpdate, onAddContext, onToggleLocked, chapterNodes, onChapterNavigate }) {
  const isChapter = node.type === "chapter";
  const isCharacter = node.type === "character";
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(node.label);
  const [editContent, setEditContent] = useState(node.content || "");
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
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [selectedText, setSelectedText] = useState("");
  const detailScrollRef = useRememberedDetailScroll(isEditing ? null : node.id);

  useEffect(() => {
    setIsEditing(false);
    setSelectedText("");
    setEditTitle(node.label);
    setEditContent(node.content || "");
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
  }, [node]);

  const handleSave = async () => {
    const payload = { title: editTitle, content: editContent };
    if (node.type === "chapter") {
      payload.chapter_elements = editChapterElements
        .map((el) => ({ ...el }))
        .filter((el) => (el.title || "").trim() || (el.content || "").trim());
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
    }
    setSaving(true);
    try {
      await onUpdate?.(node.id, payload);
      setIsEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const handleTextSelect = (event) => {
    const selection = window.getSelection?.();
    if (!selection || selection.rangeCount === 0) return;
    const range = selection.getRangeAt(0);
    if (!event.currentTarget.contains(range.commonAncestorContainer)) return;
    setSelectedText(selection.toString().trim());
  };

  const handleAddContext = () => {
    onAddContext?.(node, selectedText || undefined);
    setSelectedText("");
  };

  return (
    <div
      className={`relative flex flex-col bg-white shadow-xl animate-in slide-in-from-left ${
        isFullscreen
          ? "h-full w-full"
          : isEditing || isChapter || isCharacter
            ? "h-full w-[700px] max-w-[90vw]"
            : "h-full w-[420px] max-w-[90vw]"
      }`}
    >
      <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
        <div className="flex items-center gap-2">
          <span className="text-lg">{isEditing ? "✏️" : isChapter ? "📖" : "📄"}</span>
          <span className="font-medium text-gray-800">
            {isEditing ? "编辑节点" : isChapter ? "章节阅读" : "节点详情"}
          </span>
        </div>
        <div className="flex items-center gap-1">
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
              {onAddContext && (
                <button
                  onClick={handleAddContext}
                  className="p-1.5 rounded-md text-gray-400 hover:text-amber-500 hover:bg-amber-50 transition-colors"
                  title={selectedText ? "加入选中文本到对话上下文" : "加入对话上下文"}
                  aria-label={selectedText ? "加入选中文本到对话上下文" : "加入对话上下文"}
                >
                  <MessageSquarePlus className="w-4 h-4" />
                </button>
              )}
              {onToggleLocked && (
                <button
                  onClick={() => onToggleLocked(node)}
                  className={
                    "p-1.5 rounded-md transition-colors " + (
                      node.locked
                        ? "text-sky-600 bg-sky-50 hover:bg-sky-100"
                        : "text-gray-400 hover:text-sky-500 hover:bg-sky-50"
                    )
                  }
                  title={node.locked ? "取消固定（固定后坐标锁定，agent 与拖拽都无法移动）" : "固定节点（固定后坐标锁定，agent 与拖拽都无法移动）"}
                >
                  <Pin className={"w-4 h-4 " + (node.locked ? "fill-sky-500" : "")} />
                </button>
              )}
              {onUpdate && (
                <button
                  onClick={() => setIsEditing(true)}
                  className="p-1.5 rounded-md text-gray-400 hover:text-blue-500 hover:bg-blue-50 transition-colors"
                  title="编辑节点"
                >
                  <Pencil className="w-4 h-4" />
                </button>
              )}
              {onDelete && (
                <button
                  onClick={() => {
                    if (window.confirm(`确定删除节点「${node.label}」？关联的连线也会被删除。`)) {
                      onDelete(node);
                    }
                  }}
                  className="p-1.5 rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                  title="删除节点"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              )}
            </>
          )}
          {isChapter && isFullscreen && Array.isArray(chapterNodes) && chapterNodes.length > 1 && (() => {
            const currentIndex = chapterNodes.findIndex((chapter) => chapter.id === node.id);
            const previousChapter = currentIndex > 0 ? chapterNodes[currentIndex - 1] : null;
            const nextChapter = currentIndex >= 0 ? chapterNodes[currentIndex + 1] : null;
            return (
              <div className="mr-1 flex items-center gap-1 border-r border-gray-200 pr-1">
                <button
                  onClick={() => previousChapter && onChapterNavigate?.(previousChapter)}
                  disabled={!previousChapter}
                  className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-30 transition-colors"
                  title="上一章"
                  aria-label="上一章"
                >
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <button
                  onClick={() => nextChapter && onChapterNavigate?.(nextChapter)}
                  disabled={!nextChapter}
                  className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 disabled:cursor-not-allowed disabled:opacity-30 transition-colors"
                  title="下一章"
                  aria-label="下一章"
                >
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            );
          })()}
          <button
            onClick={() => setIsFullscreen((value) => !value)}
            className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            title={isFullscreen ? "退出全屏" : "全屏查看"}
            aria-label={isFullscreen ? "退出全屏" : "全屏查看"}
          >
            {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
          </button>
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
          isChapter={isChapter}
          chapterElements={editChapterElements}
          onTitleChange={setEditTitle}
          onContentChange={setEditContent}
          onChapterElementsChange={setEditChapterElements}
          isCharacter={isCharacter}
          storylines={editStorylines}
          onStorylinesChange={setEditStorylines}
        />
      ) : isChapter ? (
        <ChapterReadingView node={node} scrollRef={detailScrollRef} isFullscreen={isFullscreen} onTextSelect={handleTextSelect} />
      ) : (
        <DefaultNodeView node={node} scrollRef={detailScrollRef} onTextSelect={handleTextSelect} />
      )}
    </div>
  );
}

export default function NodeDetailDrawer({ node, onClose, onDelete, onUpdate, onAddContext, onToggleLocked, chapterNodes = [], onChapterNavigate }) {
  if (!node) return null;

  return (
    <div className="absolute inset-0 z-50 flex justify-start">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      <NodeDetailDrawerInner node={node} onClose={onClose} onDelete={onDelete} onUpdate={onUpdate} onAddContext={onAddContext} onToggleLocked={onToggleLocked} chapterNodes={chapterNodes} onChapterNavigate={onChapterNavigate} />
    </div>
  );
}
