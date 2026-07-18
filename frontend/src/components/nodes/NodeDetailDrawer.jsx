import { useState, useEffect, useLayoutEffect, useRef } from "react";
import { X, Trash2, BookOpen, FileText, User, Target, Map as MapIcon, Zap, Layers, Pencil, Pin, MessageSquarePlus } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import AuthIllustrationImage, { isIllustrationApiPath } from "./AuthIllustrationImage";

function MarkdownRenderer({ content }) {
  return (
    <div className="prose prose-sm max-w-none">
    <Markdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => <h1 className="text-2xl font-bold mt-6 mb-3 text-gray-900">{children}</h1>,
        h2: ({ children }) => <h2 className="text-xl font-bold mt-5 mb-2 text-gray-900">{children}</h2>,
        h3: ({ children }) => <h3 className="text-lg font-semibold mt-4 mb-2 text-gray-800">{children}</h3>,
        h4: ({ children }) => <h4 className="text-base font-semibold mt-3 mb-1 text-gray-800">{children}</h4>,
        p: ({ children }) => <p className="mb-3 leading-relaxed text-gray-700">{children}</p>,
        ul: ({ children }) => <ul className="list-disc pl-5 mb-3 space-y-1">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-5 mb-3 space-y-1">{children}</ol>,
        li: ({ children }) => <li className="text-gray-700">{children}</li>,
        blockquote: ({ children }) => (
          <blockquote className="border-l-4 border-gray-300 pl-4 italic text-gray-600 my-3">
            {children}
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
        th: ({ children }) => <th className="border border-gray-300 px-4 py-2 text-left font-semibold text-gray-700">{children}</th>,
        td: ({ children }) => <td className="border border-gray-300 px-4 py-2 text-gray-700">{children}</td>,
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
      {content}
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
  style: { icon: Target, label: "风格", bg: "bg-fuchsia-100", text: "text-fuchsia-600", badge: "text-fuchsia-700" },
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

function ChapterReadingView({ node, scrollRef }) {
  const generation = node.extra_data?.last_generation;
  const evaluations = generation?.sync_evaluations || [];
  const latestEvaluation = evaluations[evaluations.length - 1];
  const wordCount = (node.content || "").replace(/\s+/g, "").length;

  return (
    <div ref={scrollRef} data-testid="node-detail-scroll" className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-8 py-12">
        <div className="text-center mb-12">
          <h1 className="text-3xl font-serif font-bold text-gray-900 mb-2">
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

        <div className="prose prose-lg max-w-none font-serif">
          <div className="text-lg leading-relaxed text-gray-800">
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

function DefaultNodeView({ node, scrollRef }) {
  const config = NODE_TYPE_CONFIG[node.type] || DEFAULT_NODE_TYPE_CONFIG;
  const Icon = config.icon;

  return (
    <div ref={scrollRef} data-testid="node-detail-scroll" className="flex-1 overflow-y-auto">
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

        {node.extra_data && Object.keys(node.extra_data).length > 0 && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              额外信息
            </h4>
            <div className="bg-gray-50 rounded-lg p-4 space-y-2">
              {Object.entries(node.extra_data).map(([key, value]) => (
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

function EditView({ title, content, onTitleChange, onContentChange }) {
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
    </div>
  );
}

function NodeDetailDrawerInner({ node, onClose, onDelete, onUpdate, onAddContext, onToggleLocked }) {
  const [isEditing, setIsEditing] = useState(false);
  const [editTitle, setEditTitle] = useState(node.label);
  const [editContent, setEditContent] = useState(node.content || "");
  const [saving, setSaving] = useState(false);
  const detailScrollRef = useRememberedDetailScroll(isEditing ? null : node.id);

  useEffect(() => {
    setIsEditing(false);
    setEditTitle(node.label);
    setEditContent(node.content || "");
  }, [node]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onUpdate?.(node.id, { title: editTitle, content: editContent });
      setIsEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const isChapter = node.type === "chapter";

  return (
    <div
      className={`relative flex flex-col bg-white shadow-xl animate-in slide-in-from-left ${
        isEditing || isChapter ? "w-[700px] max-w-[90vw]" : "w-[420px] max-w-[90vw]"
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
                  onClick={() => onAddContext(node)}
                  className="p-1.5 rounded-md text-gray-400 hover:text-amber-500 hover:bg-amber-50 transition-colors"
                  title="加入对话上下文"
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
          <button
            onClick={onClose}
            className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {isEditing ? (
        <EditView title={editTitle} content={editContent} onTitleChange={setEditTitle} onContentChange={setEditContent} />
      ) : isChapter ? (
        <ChapterReadingView node={node} scrollRef={detailScrollRef} />
      ) : (
        <DefaultNodeView node={node} scrollRef={detailScrollRef} />
      )}
    </div>
  );
}

export default function NodeDetailDrawer({ node, onClose, onDelete, onUpdate, onAddContext, onToggleLocked }) {
  if (!node) return null;

  return (
    <div className="absolute inset-0 z-50 flex justify-start">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      <NodeDetailDrawerInner node={node} onClose={onClose} onDelete={onDelete} onUpdate={onUpdate} onAddContext={onAddContext} onToggleLocked={onToggleLocked} />
    </div>
  );
}
