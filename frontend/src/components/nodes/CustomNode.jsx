import { memo, useCallback } from "react";
import { Handle, Position } from "@xyflow/react";

const nodeStyles = {
  // 三层大纲节点
  macro_outline: { bg: "#fee2e2", border: "#dc2626", icon: "🏗️", label: "宏观" },
  meso_outline: { bg: "#ffedd5", border: "#ea580c", icon: "📋", label: "中纲" },
  micro_outline: { bg: "#fef3c7", border: "#d97706", icon: "📝", label: "小纲" },
  // 其他节点
  idea: { bg: "#fef3c7", border: "#f59e0b", icon: "💡", label: "灵感" },
  outline: { bg: "#dbeafe", border: "#3b82f6", icon: "📋", label: "大纲" },
  chapter: { bg: "#dcfce7", border: "#22c55e", icon: "📖", label: "章节" },
  character: { bg: "#fce7f3", border: "#ec4899", icon: "👤", label: "角色" },
  style: { bg: "#e0e7ff", border: "#6366f1", icon: "🎨", label: "风格" },
  conflict: { bg: "#fee2e2", border: "#ef4444", icon: "⚔️", label: "冲突" },
  foreshadow: { bg: "#f3e8ff", border: "#a855f7", icon: "🔮", label: "伏笔" },
  theme: { bg: "#fef9c3", border: "#eab308", icon: "🎯", label: "主题" },
  worldbuilding: { bg: "#ccfbf1", border: "#14b8a6", icon: "🌍", label: "世界观" },
  event: { bg: "#ffedd5", border: "#f97316", icon: "⚡", label: "事件" },
};

const CustomNode = memo(({ id, data, selected, onNodeClick }) => {
  const style = nodeStyles[data.type] || nodeStyles.idea;
  const isOutlineNode = ["macro_outline", "meso_outline", "micro_outline"].includes(data.type);

  const handleClick = useCallback((e) => {
    e.stopPropagation();
    onNodeClick?.({ id, ...data });
  }, [id, data, onNodeClick]);

  return (
    <div
      className={`px-4 py-3 rounded-lg shadow-md border-2 min-w-[150px] max-w-[250px] cursor-pointer hover:shadow-lg transition-shadow ${
        selected ? "ring-2 ring-blue-500" : ""
      } ${isOutlineNode ? "border-l-4" : ""}`}
      style={{
        backgroundColor: style.bg,
        borderColor: style.border,
      }}
      onClick={handleClick}
    >
      <Handle type="target" position={Position.Top} className="w-3 h-3" />

      <div className="flex items-center gap-2 mb-1">
        <span className="text-lg">{style.icon}</span>
        <span
          className="font-semibold text-sm truncate"
          style={{ color: style.border }}
        >
          {data.label}
        </span>
      </div>

      {data.content && (
        <p className="text-xs text-gray-600 mt-1 line-clamp-2">
          {data.content.substring(0, 60)}
          {data.content.length > 60 ? "..." : ""}
        </p>
      )}

      <div className="mt-2">
        <span
          className="text-xs px-2 py-0.5 rounded-full"
          style={{
            backgroundColor: style.border + "20",
            color: style.border,
          }}
        >
          {style.label}
        </span>
      </div>

      <Handle type="source" position={Position.Bottom} className="w-3 h-3" />
    </div>
  );
});

CustomNode.displayName = "CustomNode";

export default CustomNode;
