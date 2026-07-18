import { memo, useCallback } from "react";
import { Handle, Position } from "@xyflow/react";
import { Lock } from "lucide-react";
import { BOUNDARY_HANDLE_STYLES, ELEMENT_SIZE } from "../../lib/nodeDimensions";

const ELEMENT_SIDES = ["top", "right", "bottom", "left"];
const ELEMENT_POSITIONS = {
  top: Position.Top,
  right: Position.Right,
  bottom: Position.Bottom,
  left: Position.Left,
};

const nodeStyles = {
  outline: { bg: "#dbeafe", border: "#3b82f6", icon: "📋", label: "大纲" },
  volume: { bg: "#e0e7ff", border: "#6366f1", icon: "📚", label: "卷" },
  plot: { bg: "#ffedd5", border: "#f97316", icon: "⚡", label: "情节" },
  chapter: { bg: "#dcfce7", border: "#22c55e", icon: "📖", label: "章节" },
  character: { bg: "#fce7f3", border: "#ec4899", icon: "👤", label: "角色" },
  worldbuilding: { bg: "#ede9fe", border: "#8b5cf6", icon: "🌍", label: "世界观" },
  style: { bg: "#f3e8ff", border: "#a855f7", icon: "🎨", label: "风格" },
  element: { bg: "#fef3c7", border: "#d97706", icon: "🔹", label: "元素" },
};

const DEFAULT_STYLE = { bg: "#f1f5f9", border: "#94a3b8", icon: "📄", label: "节点" };

// character 按 scope 做视觉区分：边框色 + 角色徽章（temp 用虚线弱化）
const CHARACTER_SCOPE_STYLE = {
  global: { border: "#f59e0b", label: "主角", dashed: false },
  major: { border: "#ec4899", label: "主要配角", dashed: false },
  minor: { border: "#f9a8d4", label: "次要配角", dashed: false },
  temp: { border: "#94a3b8", label: "临时", dashed: true },
};

const CustomNode = memo(({
  id,
  data,
  selected,
  onNodeClick,
  onFocusEdges,
  isEdgesFocused,
  isHighlighted,
  isCollapsed,
  hasChildren,
  linkedElementCount = 0,
  onCollapseToggle,
}) => {
  const style = nodeStyles[data.type] || DEFAULT_STYLE;
  const isCharacter = data.type === "character";
  const charScope = isCharacter ? CHARACTER_SCOPE_STYLE[data.scope] : null;
  const isChapter = data.type === "chapter";
  const isLocked = !!data.locked;
  const collapseLabel = isChapter && linkedElementCount > 0
    ? (isCollapsed ? "展开元素" : "收起元素")
    : (isCollapsed ? "展开子节点" : "收起子节点");
  const wordCount = isChapter
    ? (data.content || "").replace(/\s+/g, "").length
    : 0;
  const lastEvaluation = data.extra_data?.last_generation?.sync_evaluations?.at?.(-1);

  const handleClick = useCallback((e) => {
    e.stopPropagation();
    onNodeClick?.({ id, ...data });
  }, [id, data, onNodeClick]);

  const handleFocusEdges = useCallback((e) => {
    e.stopPropagation();
    onFocusEdges?.(id);
  }, [id, onFocusEdges]);

  const handleCollapseToggle = useCallback((e) => {
    e.stopPropagation();
    onCollapseToggle?.(id);
  }, [id, onCollapseToggle]);

  // element 节点：圆形小尺寸，只显示图标 + 标题
  if (data.type === "element") {
    return (
      <div
        className={`element-node-3d relative box-border rounded-full flex flex-col items-center justify-center px-2 cursor-pointer transition-all ${
          selected ? "ring-2 ring-blue-500" : ""
        } ${isHighlighted ? "node-highlighted" : ""} ${isLocked ? "ring-2 ring-sky-500" : ""}`}
        style={{
          width: ELEMENT_SIZE,
          height: ELEMENT_SIZE,
          "--element-bg": style.bg,
          "--element-border": isHighlighted ? "#3b82f6" : style.border,
          "--element-fill-opacity": "0.76",
        }}
        onClick={handleClick}
      >
        {ELEMENT_SIDES.map((side) => (
          <Handle
            key={`target-${side}`}
            id={`target-${side}`}
            type="target"
            position={ELEMENT_POSITIONS[side]}
            style={BOUNDARY_HANDLE_STYLES[side]}
            className="!w-0 !h-0 !min-w-0 !min-h-0 !border-0 opacity-0"
          />
        ))}
        <span className="element-node-shine" aria-hidden="true" />
        <span className="element-node-reflection" aria-hidden="true" />
        {isLocked && (
          <span
            className="absolute -top-1.5 -left-1.5 nodrag"
            title="已固定"
            aria-label="已固定"
          >
            <Lock className="w-3.5 h-3.5 text-sky-600 bg-white rounded-full p-0.5 shadow" />
          </span>
        )}
        <span
          className="element-node-label text-xs font-semibold text-center leading-tight line-clamp-2 px-1"
          style={{ color: style.border }}
        >
          {data.label}
        </span>
        {ELEMENT_SIDES.map((side) => (
          <Handle
            key={`source-${side}`}
            id={`source-${side}`}
            type="source"
            position={ELEMENT_POSITIONS[side]}
            style={BOUNDARY_HANDLE_STYLES[side]}
            className="!w-0 !h-0 !min-w-0 !min-h-0 !border-0 opacity-0"
          />
        ))}
      </div>
    );
  }

  return (
    <div
      className={`box-border relative h-[120px] w-[250px] overflow-hidden px-4 py-3 rounded-lg shadow-md border-2 cursor-pointer hover:shadow-lg transition-all group ${
        charScope?.dashed ? "border-dashed" : ""
      } ${selected ? "ring-2 ring-blue-500" : ""} ${isHighlighted ? "node-highlighted" : ""} ${isLocked ? "ring-2 ring-sky-500" : ""}`}
      style={{
        backgroundColor: style.bg,
        borderColor: isLocked ? "#0ea5e9" : (isHighlighted ? "#3b82f6" : (charScope ? charScope.border : style.border)),
      }}
      onClick={handleClick}
    >
      {isLocked && (
        <span
          className="absolute top-1 right-1 nodrag"
          title="已固定"
          aria-label="已固定"
        >
          <Lock className="w-3.5 h-3.5 text-sky-600" />
        </span>
      )}
      <Handle id="target-top" type="target" position={Position.Top} className="w-3 h-3" />
      <Handle id="target-right" type="target" position={Position.Right} className="w-3 h-3" />
      <Handle id="target-bottom" type="target" position={Position.Bottom} className="w-3 h-3" />
      <Handle id="target-left" type="target" position={Position.Left} className="w-3 h-3" />

      <div className="flex items-center gap-2 mb-1">
        <span className="text-lg">{style.icon}</span>
        <span
          className="font-semibold text-sm truncate"
          style={{ color: style.border }}
        >
          {data.label}
        </span>
        {hasChildren && (
          <button
            type="button"
            aria-label={collapseLabel}
            title={collapseLabel}
            className="nodrag ml-auto rounded px-1.5 py-0.5 text-xs bg-white/70 text-slate-500 hover:bg-white transition-colors"
            onClick={handleCollapseToggle}
          >
            {isCollapsed ? "▸" : "▾"}
          </button>
        )}
        <button
          type="button"
          aria-label={isEdgesFocused ? "显示全部连线" : "只显示相关连线"}
          title={isEdgesFocused ? "显示全部连线" : "只显示相关连线"}
          className={`nodrag ${!hasChildren ? "ml-auto" : ""} rounded px-1.5 py-0.5 text-xs transition-colors ${
            isEdgesFocused
              ? "bg-slate-700 text-white"
              : "bg-white/70 text-slate-500 hover:bg-white"
          }`}
          onClick={handleFocusEdges}
        >
          ⤢
        </button>
      </div>

      {data.content && (
        <p className="text-xs text-gray-600 mt-1 line-clamp-2">
          {data.content.substring(0, 60)}
          {data.content.length > 60 ? "..." : ""}
        </p>
      )}

      <div className="mt-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {isCharacter && charScope ? (
            <span
              className="text-xs px-2 py-0.5 rounded-full"
              style={{
                backgroundColor: charScope.border + "20",
                color: charScope.border,
              }}
            >
              {charScope.label}
            </span>
          ) : (
            <span
              className="text-xs px-2 py-0.5 rounded-full"
              style={{
                backgroundColor: style.border + "20",
                color: style.border,
              }}
            >
              {style.label}
            </span>
          )}
          {isChapter && (
            <span className="text-[10px] text-gray-500">
              {wordCount > 0 ? `${wordCount} 字` : "未写"}
            </span>
          )}
          {isChapter && lastEvaluation && (
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                lastEvaluation.passed
                  ? "bg-emerald-100 text-emerald-700"
                  : "bg-amber-100 text-amber-700"
              }`}
            >
              {lastEvaluation.passed ? "同步通过" : "同步异常"}
            </span>
          )}
        </div>
      </div>

      <Handle id="source-top" type="source" position={Position.Top} className="w-3 h-3" />
      <Handle id="source-right" type="source" position={Position.Right} className="w-3 h-3" />
      <Handle id="source-bottom" type="source" position={Position.Bottom} className="w-3 h-3" />
      <Handle id="source-left" type="source" position={Position.Left} className="w-3 h-3" />

      {isCharacter && (
        <>
          <Handle
            id="rel-target-top"
            type="target"
            position={Position.Top}
            className="!w-2.5 !h-2.5 !bg-amber-400 !border-2 !border-amber-600 opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ top: 8 }}
          />
          <Handle
            id="rel-target-right"
            type="target"
            position={Position.Right}
            className="!w-2.5 !h-2.5 !bg-amber-400 !border-2 !border-amber-600 opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ right: 8 }}
          />
          <Handle
            id="rel-target-bottom"
            type="target"
            position={Position.Bottom}
            className="!w-2.5 !h-2.5 !bg-amber-400 !border-2 !border-amber-600 opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ bottom: 8 }}
          />
          <Handle
            id="rel-target-left"
            type="target"
            position={Position.Left}
            className="!w-2.5 !h-2.5 !bg-amber-400 !border-2 !border-amber-600 opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ left: 8 }}
          />
          <Handle
            id="rel-source-top"
            type="source"
            position={Position.Top}
            className="!w-2.5 !h-2.5 !bg-amber-400 !border-2 !border-amber-600 opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ top: 16 }}
          />
          <Handle
            id="rel-source-right"
            type="source"
            position={Position.Right}
            className="!w-2.5 !h-2.5 !bg-amber-400 !border-2 !border-amber-600 opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ right: 16 }}
          />
          <Handle
            id="rel-source-bottom"
            type="source"
            position={Position.Bottom}
            className="!w-2.5 !h-2.5 !bg-amber-400 !border-2 !border-amber-600 opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ bottom: 16 }}
          />
          <Handle
            id="rel-source-left"
            type="source"
            position={Position.Left}
            className="!w-2.5 !h-2.5 !bg-amber-400 !border-2 !border-amber-600 opacity-0 group-hover:opacity-100 transition-opacity"
            style={{ left: 16 }}
          />
        </>
      )}
    </div>
  );
});

CustomNode.displayName = "CustomNode";

export default CustomNode;
