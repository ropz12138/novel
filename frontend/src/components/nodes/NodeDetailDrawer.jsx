import { useState, useEffect } from "react";
import { X, Trash2, BookOpen, FileText, User, Lightbulb, Scroll, Layers, Target, Map, Zap, Eye } from "lucide-react";
import { fetchChapter } from "../../lib/canvasApi";

const NODE_TYPE_CONFIG = {
  macro_outline: { icon: Layers, label: "宏观大纲", color: "red" },
  meso_outline: { icon: FileText, label: "中纲", color: "orange" },
  micro_outline: { icon: Scroll, label: "小纲", color: "amber" },
  idea: { icon: Lightbulb, label: "灵感", color: "yellow" },
  chapter: { icon: BookOpen, label: "章节", color: "green" },
  character: { icon: User, label: "角色", color: "pink" },
  foreshadow: { icon: Eye, label: "伏笔", color: "purple" },
  outline: { icon: FileText, label: "大纲", color: "blue" },
  style: { icon: Target, label: "风格", color: "indigo" },
  conflict: { icon: Zap, label: "冲突", color: "red" },
  theme: { icon: Target, label: "主题", color: "yellow" },
  worldbuilding: { icon: Map, label: "世界观", color: "teal" },
  event: { icon: Zap, label: "事件", color: "orange" },
};

function ChapterReadingView({ node, chapter }) {
  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-2xl mx-auto px-8 py-12">
        <div className="text-center mb-12">
          <h1 className="text-3xl font-serif font-bold text-gray-900 mb-2">
            {node.label}
          </h1>
          <div className="w-16 h-px bg-gray-300 mx-auto" />
        </div>

        <div className="prose prose-lg max-w-none font-serif">
          <div className="text-lg leading-relaxed text-gray-800 whitespace-pre-wrap first-letter:text-4xl first-letter:font-bold first-letter:float-left first-letter:mr-2 first-letter:mt-1">
            {node.content || "暂无内容"}
          </div>
        </div>

        {chapter && (
          <div className="mt-16 pt-8 border-t border-gray-200">
            <h3 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
              章节摘要
            </h3>
            <p className="text-sm text-gray-600 leading-relaxed">
              {chapter.summary || "暂无摘要"}
            </p>

            {chapter.new_facts?.length > 0 && (
              <div className="mt-6">
                <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  新增事实
                </h4>
                <ul className="space-y-1">
                  {chapter.new_facts.map((fact, i) => (
                    <li key={i} className="text-sm text-gray-600 flex items-start gap-2">
                      <span className="text-green-500 mt-1">•</span>
                      {fact}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {chapter.foreshadows?.length > 0 && (
              <div className="mt-6">
                <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
                  伏笔
                </h4>
                <ul className="space-y-1">
                  {chapter.foreshadows.map((f, i) => (
                    <li key={i} className="text-sm text-gray-600 flex items-start gap-2">
                      <span className="text-purple-500 mt-1">•</span>
                      {f}
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

function DefaultNodeView({ node }) {
  const config = NODE_TYPE_CONFIG[node.type] || NODE_TYPE_CONFIG.idea;
  const Icon = config.icon;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="p-6 space-y-6">
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg bg-${config.color}-100`}>
            <Icon className={`w-5 h-5 text-${config.color}-600`} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-gray-900">{node.label}</h3>
            <span className={`text-xs px-2 py-0.5 rounded-full bg-${config.color}-100 text-${config.color}-700`}>
              {config.label}
            </span>
          </div>
        </div>

        {node.content && (
          <div>
            <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
              内容
            </h4>
            <div className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap bg-gray-50 rounded-lg p-4">
              {node.content}
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

export default function NodeDetailDrawer({ node, onClose, onDelete }) {
  const [chapter, setChapter] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (node?.type === "chapter" && node?.id) {
      setLoading(true);
      fetchChapter(node.id)
        .then(setChapter)
        .catch(() => setChapter(null))
        .finally(() => setLoading(false));
    } else {
      setChapter(null);
    }
  }, [node]);

  if (!node) return null;

  const isChapter = node.type === "chapter";
  const config = NODE_TYPE_CONFIG[node.type] || NODE_TYPE_CONFIG.idea;

  return (
    <div className="fixed inset-0 z-50 flex justify-start">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      <div
        className={`relative flex flex-col bg-white shadow-xl animate-in slide-in-from-left ${
          isChapter ? "w-[700px] max-w-[90vw]" : "w-[420px] max-w-[90vw]"
        }`}
      >
        <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
          <div className="flex items-center gap-2">
            <span className="text-lg">{isChapter ? "📖" : "📄"}</span>
            <span className="font-medium text-gray-800">
              {isChapter ? "章节阅读" : "节点详情"}
            </span>
          </div>
          <div className="flex items-center gap-1">
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
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-100 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <div className="h-8 w-8 animate-spin rounded-full border-4 border-green-500 border-t-transparent" />
              <div className="text-sm text-gray-500">加载章节内容...</div>
            </div>
          </div>
        ) : isChapter ? (
          <ChapterReadingView node={node} chapter={chapter} />
        ) : (
          <DefaultNodeView node={node} />
        )}
      </div>
    </div>
  );
}
