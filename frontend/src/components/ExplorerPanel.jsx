import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import {
  BookOpen,
  ChevronDown,
  ChevronRight,
  Globe,
  MessageSquareWarning,
  Plus,
  StickyNote,
  Users,
} from "lucide-react";

export const CHARACTER_SCOPES = [
  { scope: "global", label: "主角", color: "#d97706" },
  { scope: "major", label: "主要配角", color: "#db2777" },
  { scope: "minor", label: "次要配角", color: "#f472b6" },
  { scope: "temp", label: "临时角色", color: "#94a3b8" },
];

export const NEW_NODE_TITLES = {
  chapter: "新章节",
  character: "新角色",
  worldbuilding: "新世界观",
  note: "新笔记",
  reviewer_note: "新评审笔记",
};

const SECTIONS = [
  { type: "chapter", label: "章节", icon: BookOpen, color: "#c2402a" },
  { type: "character", label: "角色", icon: Users, color: "#d97706" },
  { type: "worldbuilding", label: "世界观", icon: Globe, color: "#0d9488" },
  { type: "note", label: "笔记", icon: StickyNote, color: "#ca8a04" },
  { type: "reviewer_note", label: "评审笔记", icon: MessageSquareWarning, color: "#7c3aed" },
];

const NODE_LONG_PRESS_MS = 500;
const NODE_LONG_PRESS_MOVE_PX = 8;

export function compareExplorerNodes(a, b) {
  const orderA = a.data?.sort_order ?? 0;
  const orderB = b.data?.sort_order ?? 0;
  if (orderA !== orderB) return orderA - orderB;
  const labelA = a.data?.label || "";
  const labelB = b.data?.label || "";
  if (labelA !== labelB) return labelA.localeCompare(labelB, "zh");
  return a.id.localeCompare(b.id);
}

export function groupExplorerNodes(nodes = []) {
  const chapters = nodes
    .filter((node) => node.data?.type === "chapter")
    .sort(compareExplorerNodes);
  const characters = CHARACTER_SCOPES.map((scope) => ({
    ...scope,
    items: nodes
      .filter((node) => node.data?.type === "character" && node.data?.scope === scope.scope)
      .sort(compareExplorerNodes),
  }));
  const byType = (type) => nodes
    .filter((node) => node.data?.type === type)
    .sort(compareExplorerNodes);
  return {
    chapter: chapters,
    character: characters,
    worldbuilding: byType("worldbuilding"),
    note: byType("note"),
    reviewer_note: byType("reviewer_note"),
  };
}

function useLongPressMenu(appMode, onOpenMenu, node) {
  const startRef = useRef(null);
  const timerRef = useRef(null);
  const suppressClickRef = useRef(false);

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(() => () => clearTimer(), []);

  if (!appMode || !onOpenMenu) {
    return { longPressProps: {}, suppressClickRef };
  }

  const handlePointerDown = (event) => {
    if (event.button != null && event.button !== 0) return;
    startRef.current = { x: event.clientX, y: event.clientY };
    clearTimer();
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      suppressClickRef.current = true;
      onOpenMenu({ clientX: startRef.current.x, clientY: startRef.current.y }, node);
    }, NODE_LONG_PRESS_MS);
  };

  const handlePointerMove = (event) => {
    const start = startRef.current;
    if (!start) return;
    const dx = event.clientX - start.x;
    const dy = event.clientY - start.y;
    if ((dx * dx) + (dy * dy) > NODE_LONG_PRESS_MOVE_PX * NODE_LONG_PRESS_MOVE_PX) {
      clearTimer();
    }
  };

  const handlePointerUp = () => {
    clearTimer();
    startRef.current = null;
  };

  return {
    suppressClickRef,
    longPressProps: {
      onPointerDown: handlePointerDown,
      onPointerMove: handlePointerMove,
      onPointerUp: handlePointerUp,
      onPointerCancel: handlePointerUp,
    },
  };
}

function ExplorerRow({
  node,
  index,
  selected,
  icon: Icon,
  color,
  draggable,
  onSelect,
  onOpenMenu,
  onDragStart,
  onDragOver,
  onDrop,
  appMode,
}) {
  const { longPressProps, suppressClickRef } = useLongPressMenu(appMode, onOpenMenu, node);
  const label = node.data?.label || "未命名";

  return (
    <li
      onDragOver={draggable ? onDragOver : undefined}
      onDrop={draggable ? onDrop : undefined}
    >
      <button
        type="button"
        data-testid={`explorer-item-${node.id}`}
        draggable={draggable}
        onDragStart={draggable ? onDragStart : undefined}
        aria-current={selected ? "page" : undefined}
        className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] transition-colors ${
          selected
            ? "bg-blue-50 text-slate-900"
            : "text-slate-700 hover:bg-white"
        }`}
        onClick={(event) => {
          if (suppressClickRef.current) {
            suppressClickRef.current = false;
            return;
          }
          onSelect?.({ id: node.id, ...node.data }, event);
        }}
        onContextMenu={(event) => {
          if (!onOpenMenu) return;
          event.preventDefault();
          onOpenMenu(event, node);
        }}
        {...longPressProps}
      >
        <Icon className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} style={{ color }} />
        {typeof index === "number" && (
          <span aria-hidden="true" className="w-5 shrink-0 text-right text-[11px] text-slate-400">{index}</span>
        )}
        <span className="truncate">{label}</span>
      </button>
    </li>
  );
}

function SectionHeader({ label, count, collapsed, onToggle, onAdd, addLabel }) {
  return (
    <div className="flex items-center gap-1 px-2 pb-0.5 pt-2">
      <button
        type="button"
        className="flex min-w-0 flex-1 items-center gap-1 rounded px-1 py-0.5 text-left text-xs font-medium text-slate-400 hover:bg-white hover:text-slate-600"
        aria-expanded={!collapsed}
        onClick={onToggle}
      >
        {collapsed
          ? <ChevronRight className="h-3 w-3 shrink-0" />
          : <ChevronDown className="h-3 w-3 shrink-0" />}
        <span className="truncate">{label}</span>
        <span className="tabular-nums text-slate-300">{count}</span>
      </button>
      {onAdd && (
        <button
          type="button"
          aria-label={addLabel}
          title={addLabel}
          onClick={onAdd}
          className="rounded p-0.5 text-slate-400 hover:bg-white hover:text-slate-700"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  );
}

export default function ExplorerPanel({
  nodes = [],
  selectedIds = [],
  onSelect,
  onAdd,
  onReorderChapters,
  onCopyNode,
  onDeleteNode,
  onAddContext,
  appMode = false,
}) {
  const grouped = useMemo(() => groupExplorerNodes(nodes), [nodes]);
  const [collapsedSections, setCollapsedSections] = useState(() => new Set());
  const [contextMenu, setContextMenu] = useState(null);
  const menuRef = useRef(null);
  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const toggleSection = (key) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const openMenu = (event, node) => {
    setContextMenu({ x: event.clientX, y: event.clientY, node });
  };

  useEffect(() => {
    if (!contextMenu) return undefined;
    const close = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setContextMenu(null);
      }
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [contextMenu]);

  const handleChapterDrop = (targetId) => (event) => {
    event.preventDefault();
    const sourceId = event.dataTransfer.getData("text/plain");
    if (!sourceId || sourceId === targetId) return;
    const ids = grouped.chapter.map((node) => node.id);
    const from = ids.indexOf(sourceId);
    const to = ids.indexOf(targetId);
    if (from < 0 || to < 0) return;
    const next = [...ids];
    next.splice(from, 1);
    next.splice(to, 0, sourceId);
    onReorderChapters?.(next);
  };

  return (
    <div data-testid="workbench-explorer" className="flex h-full min-h-0 flex-col overflow-y-auto pb-8">
      {SECTIONS.map((section) => {
        const Icon = section.icon;
        const collapsed = collapsedSections.has(section.type);
        if (section.type === "character") {
          const total = grouped.character.reduce((sum, group) => sum + group.items.length, 0);
          return (
            <section key={section.type}>
              <SectionHeader
                label={section.label}
                count={total}
                collapsed={collapsed}
                onToggle={() => toggleSection(section.type)}
                onAdd={onAdd ? () => onAdd("character") : undefined}
                addLabel="添加角色"
              />
              {!collapsed && grouped.character.map((group) => (
                <div key={group.scope}>
                  <h3 className="px-4 pb-0.5 pt-1 text-[11px] font-medium text-slate-400">
                    {`${group.label} ${group.items.length}`}
                  </h3>
                  {group.items.length === 0 ? (
                    <p className="px-4 py-1 text-[11px] text-slate-300">暂无</p>
                  ) : (
                    <ul>
                      {group.items.map((node) => (
                        <ExplorerRow
                          key={node.id}
                          node={node}
                          selected={selectedSet.has(node.id)}
                          icon={Users}
                          color={group.color}
                          onSelect={onSelect}
                          onOpenMenu={onCopyNode || onDeleteNode || onAddContext ? openMenu : undefined}
                          appMode={appMode}
                        />
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </section>
          );
        }

        const items = grouped[section.type] || [];
        return (
          <section key={section.type}>
            <SectionHeader
              label={section.label}
              count={items.length}
              collapsed={collapsed}
              onToggle={() => toggleSection(section.type)}
              onAdd={onAdd ? () => onAdd(section.type) : undefined}
              addLabel={`添加${section.label}`}
            />
            {!collapsed && (
              items.length === 0 ? (
                <p className="px-4 py-1 text-[11px] text-slate-300">暂无</p>
              ) : (
                <ul>
                  {items.map((node, index) => (
                    <ExplorerRow
                      key={node.id}
                      node={node}
                      index={section.type === "chapter" ? index + 1 : undefined}
                      selected={selectedSet.has(node.id)}
                      icon={Icon}
                      color={section.color}
                      draggable={section.type === "chapter" && !!onReorderChapters}
                      onSelect={onSelect}
                      onOpenMenu={onCopyNode || onDeleteNode || onAddContext ? openMenu : undefined}
                      onDragStart={(event) => {
                        event.dataTransfer.setData("text/plain", node.id);
                        event.dataTransfer.effectAllowed = "move";
                      }}
                      onDragOver={(event) => event.preventDefault()}
                      onDrop={handleChapterDrop(node.id)}
                      appMode={appMode}
                    />
                  ))}
                </ul>
              )
            )}
          </section>
        );
      })}

      {contextMenu && createPortal(
        <div
          ref={menuRef}
          className="fixed z-[80] min-w-[160px] rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          {onAddContext && (
            <button
              type="button"
              aria-label="引用此节点"
              onClick={() => {
                const node = contextMenu.node;
                setContextMenu(null);
                onAddContext({ id: node.id, ...node.data });
              }}
              className="w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
            >
              引用此节点
            </button>
          )}
          {onCopyNode && (
            <button
              type="button"
              aria-label="复制到其他作品"
              onClick={() => {
                const node = contextMenu.node;
                setContextMenu(null);
                onCopyNode(node);
              }}
              className="w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
            >
              复制到其他作品
            </button>
          )}
          {onDeleteNode && (
            <button
              type="button"
              aria-label="删除节点"
              onClick={() => {
                const node = contextMenu.node;
                setContextMenu(null);
                if (window.confirm("确定删除该节点？")) {
                  onDeleteNode({ id: node.id, ...node.data });
                }
              }}
              className="w-full px-3 py-2 text-left text-sm text-red-600 hover:bg-red-50"
            >
              删除节点
            </button>
          )}
        </div>,
        document.body,
      )}
    </div>
  );
}
