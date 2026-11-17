import { memo, useCallback, useRef } from "react";
import { Handle, Position } from "@xyflow/react";
import { BookOpen, ChevronDown, ChevronRight, Globe, Lock, Search, StickyNote, User } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { BOUNDARY_HANDLE_STYLES, ELEMENT_SIZE } from "../../lib/nodeDimensions";
import { remarkHtmlBreaks } from "../../lib/markdown";

/** Compact markdown for canvas card previews (keeps line-clamp usable). */
const previewMdComponents = {
  h1: ({ children }) => <span className="font-semibold">{children}{" "}</span>,
  h2: ({ children }) => <span className="font-semibold">{children}{" "}</span>,
  h3: ({ children }) => <span className="font-semibold">{children}{" "}</span>,
  h4: ({ children }) => <span className="font-semibold">{children}{" "}</span>,
  p: ({ children }) => <span>{children}{" "}</span>,
  ul: ({ children }) => <span>{children}</span>,
  ol: ({ children }) => <span>{children}</span>,
  li: ({ children }) => <span>{"· "}{children}{" "}</span>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em>{children}</em>,
  code: ({ inline, children, ...props }) => (
    <code className="text-[10px] font-mono" {...props}>{children}</code>
  ),
  blockquote: ({ children }) => <span>{children}{" "}</span>,
  hr: () => null,
  a: ({ children }) => <span>{children}</span>,
  img: () => null,
  table: () => null,
  thead: () => null,
  tbody: ({ children }) => <span>{children}</span>,
  tr: ({ children }) => <span>{children}{" "}</span>,
  th: ({ children }) => <span className="font-semibold">{children}{" "}</span>,
  td: ({ children }) => <span>{children}{" "}</span>,
  pre: ({ children }) => <span>{children}</span>,
};

function NodePreviewMarkdown({ content }) {
  const preview = content.length > 240 ? `${content.slice(0, 240)}` : content;
  return (
    <div
      data-testid="node-preview-markdown"
      className="text-xs text-gray-600 mt-1 line-clamp-2 break-words"
    >
      <Markdown remarkPlugins={[remarkGfm, remarkHtmlBreaks]} components={previewMdComponents}>
        {preview}
      </Markdown>
    </div>
  );
}

const ELEMENT_SIDES = ["top", "right", "bottom", "left"];
const ELEMENT_POSITIONS = {
  top: Position.Top,
  right: Position.Right,
  bottom: Position.Bottom,
  left: Position.Left,
};

const nodeStyles = {
  chapter: { bg: "#dcfce7", border: "#62d28b", ink: "#15803d", icon: BookOpen, label: "章节" },
  character: { bg: "#fce7f3", border: "#ec4899", icon: User, label: "角色" },
  worldbuilding: { bg: "#ede9fe", border: "#8b5cf6", icon: Globe, label: "世界观" },
  note: { bg: "#f3e8ff", border: "#a855f7", icon: StickyNote, label: "笔记" },
  reviewer_note: { bg: "#fef3c7", border: "#d97706", icon: Search, label: "评审笔记" },
  element: { bg: "#fef3c7", border: "#d97706", icon: "🔹", label: "元素" },
};

const DEFAULT_STYLE = { bg: "#f1f5f9", border: "#94a3b8", icon: "📄", label: "节点" };
export const NODE_LONG_PRESS_MS = 500;
export const NODE_LONG_PRESS_MOVE_PX = 8;

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
  isExpanded,
  hasChildren,
  hiddenDescendantCount = 0,
  hiddenDescendantText = "",
  onCollapseToggle,
  onNodeLongPress,
  appMode = false,
}) => {
  const style = nodeStyles[data.type] || DEFAULT_STYLE;
  const NodeIcon = style.icon;
  const isCharacter = data.type === "character";
  const charScope = isCharacter ? CHARACTER_SCOPE_STYLE[data.scope] : null;
  const isChapter = data.type === "chapter";
  const isLocked = !!data.locked;
  const collapseLabel = isExpanded ? "收起子节点" : "展开子节点";
  const wordCount = isChapter
    ? (data.content || "").replace(/\s+/g, "").length
    : 0;
  const lastEvaluation = data.extra_data?.last_generation?.sync_evaluations?.at?.(-1);
  const chapterCharacters = isChapter
    ? (Array.isArray(data.extra_data?.characters) ? data.extra_data.characters : [])
    : [];

  const longPressTimerRef = useRef(null);
  const longPressStartRef = useRef(null);
  const suppressClickRef = useRef(false);

  const clearLongPress = useCallback(() => {
    if (longPressTimerRef.current != null) {
      clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
  }, []);

  const handleClick = useCallback((e) => {
    e.stopPropagation();
    if (suppressClickRef.current) {
      suppressClickRef.current = false;
      return;
    }
    onNodeClick?.({ id, ...data });
  }, [id, data, onNodeClick]);

  const handlePointerDown = useCallback((event) => {
    if (event.button != null && event.button !== 0) return;
    longPressStartRef.current = { x: event.clientX, y: event.clientY };
    suppressClickRef.current = false;
    clearLongPress();
    const pressEvent = {
      preventDefault: () => event.preventDefault(),
      clientX: event.clientX,
      clientY: event.clientY,
      target: event.currentTarget,
      currentTarget: event.currentTarget,
    };
    longPressTimerRef.current = setTimeout(() => {
      longPressTimerRef.current = null;
      suppressClickRef.current = true;
      onNodeLongPress?.(pressEvent, { id, data });
    }, NODE_LONG_PRESS_MS);
  }, [clearLongPress, data, id, onNodeLongPress]);

  const handlePointerMove = useCallback((event) => {
    const start = longPressStartRef.current;
    if (!start) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if ((dx * dx) + (dy * dy) > NODE_LONG_PRESS_MOVE_PX * NODE_LONG_PRESS_MOVE_PX) {
      clearLongPress();
    }
  }, [clearLongPress]);

  const handlePointerUp = useCallback(() => {
    clearLongPress();
    longPressStartRef.current = null;
  }, [clearLongPress]);

  const longPressProps = appMode
    ? {
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: handlePointerUp,
      onPointerCancel: handlePointerUp,
      onMouseDown: handlePointerDown,
      onMouseMove: handlePointerMove,
      onMouseUp: handlePointerUp,
    }
    : {};

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
        } ${isLocked ? "ring-2 ring-sky-500" : ""}`}
        style={{
          width: ELEMENT_SIZE,
          height: ELEMENT_SIZE,
          "--element-bg": style.bg,
          "--element-border": style.border,
          "--element-fill-opacity": "0.76",
        }}
        onClick={handleClick}
        {...longPressProps}
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
      className={`box-border relative h-[120px] w-[250px] overflow-hidden rounded-xl border-[1.5px] px-3.5 py-3 cursor-pointer transition-shadow group ${
        charScope?.dashed ? "border-dashed" : ""
      } ${isLocked ? "ring-2 ring-sky-500" : ""}`}
      style={{
        backgroundColor: style.bg,
        borderColor: isLocked ? "#0ea5e9" : (charScope ? charScope.border : style.border),
        boxShadow: selected
          ? "0 0 0 3px #fff, 0 0 0 5.5px #2563eb, 0 10px 20px -10px rgba(37,99,235,.5)"
          : "0 1px 2px rgba(16,24,40,.06), 0 8px 16px -10px rgba(16,24,40,.22)",
      }}
      onClick={handleClick}
      {...longPressProps}
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
        {typeof NodeIcon === "string" ? <span className="text-lg">{NodeIcon}</span> : <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-[7px] bg-white/70"><NodeIcon className="h-3.5 w-3.5" strokeWidth={1.75} style={{ color: style.ink || style.border }} /></span>}
        <span className="min-w-0 truncate text-[15px] font-semibold" style={{ color: style.ink || "#131a26" }}>
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
            {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        )}
      </div>

      {data.content && !(isCharacter && (data.extra_data?.storylines || []).length) && (
        <NodePreviewMarkdown content={data.content} />
      )}

      {chapterCharacters.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {chapterCharacters.map((character, index) => {
            const name = character?.name;
            if (!name) return null;
            return (
              <span
                key={character?.id || `${name}-${index}`}
                className="text-[10px] px-1.5 py-0.5 rounded-full bg-pink-50 text-pink-700"
              >
                {name}
              </span>
            );
          })}
        </div>
      )}

      <div className="mt-2">
        <div className="flex flex-wrap items-center gap-1.5">
          {isCharacter && charScope ? (
            <span className="rounded-full bg-white/60 px-2 py-0.5 text-xs text-[#5b6676]">
              {charScope.label}
            </span>
          ) : (
            <span className="rounded-full bg-white/60 px-2 py-0.5 text-xs text-[#5b6676]">
              {style.label}
            </span>
          )}
          {isChapter && (
            <span className="font-mono text-[11px] text-[#5b6676]">
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
          {isCharacter && (data.extra_data?.storylines || []).map((line, index) => (
            <span
              key={`${line?.name || "line"}-${index}`}
              className="text-[10px] px-1.5 py-0.5 rounded-full bg-white/80 text-pink-700"
            >
              {line?.name || `线 ${index + 1}`}
            </span>
          ))}
          {hiddenDescendantCount > 0 && hiddenDescendantText && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded-full bg-slate-100 text-slate-500"
              title={`${hiddenDescendantCount} 个节点已折叠`}
            >
              {hiddenDescendantText}
            </span>
          )}
        </div>
      </div>

      <Handle id="source-top" type="source" position={Position.Top} className="w-3 h-3" />
      <Handle id="source-right" type="source" position={Position.Right} className="w-3 h-3" />
      <Handle id="source-bottom" type="source" position={Position.Bottom} className="w-3 h-3" />
      <Handle id="source-left" type="source" position={Position.Left} className="w-3 h-3" />
    </div>
  );
});

CustomNode.displayName = "CustomNode";

export default CustomNode;
