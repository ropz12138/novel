import { memo, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Globe, Search, StickyNote, User } from "lucide-react";
import { isIsolatedNode } from "../../lib/canvasRelation";
import { compareSiblings } from "../../lib/canvasOrder";
import { NODE_LONG_PRESS_MOVE_PX, NODE_LONG_PRESS_MS } from "./CustomNode";

/**
 * 非层级链节点的侧栏入口。
 *
 * character、worldbuilding、note 不参与树布局，也不渲染到画布主干。
 * 右侧「角色与设定」提供常驻入口：角色按 scope 分组，另加世界观与笔记。
 *
 * character 按 scope 细分：后端强校验其取值只能是以下四种。
 */
const CHARACTER_SCOPES = [
  { scope: "global", label: "主角", color: "#d97706" },
  { scope: "major", label: "主要配角", color: "#db2777" },
  { scope: "minor", label: "次要配角", color: "#f472b6" },
  { scope: "temp", label: "临时角色", color: "#94a3b8" },
];

const GROUPS = [
  ...CHARACTER_SCOPES.map(({ scope, label, color }) => ({
    key: `character:${scope}`,
    label,
    icon: User,
    color,
    matches: (data) => data?.type === "character" && data?.scope === scope,
  })),
  {
    key: "worldbuilding",
    label: "世界观",
    icon: Globe,
    color: "#7c3aed",
    matches: (data) => data?.type === "worldbuilding",
  },
  {
    key: "note",
    label: "笔记",
    icon: StickyNote,
    color: "#9333ea",
    matches: (data) => data?.type === "note",
  },
  {
    key: "reviewer_note",
    label: "评审笔记",
    icon: Search,
    color: "#b45309",
    matches: (data) => data?.type === "reviewer_note",
  },
];

function IsolatedNodeRow({ node, icon: Icon, color, onSelect, onOpenMenu, appMode }) {
  const timerRef = useRef(null);
  const startRef = useRef(null);
  const suppressClickRef = useRef(false);

  useEffect(() => () => {
    if (timerRef.current != null) clearTimeout(timerRef.current);
  }, []);

  const clearTimer = () => {
    if (timerRef.current != null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  const handlePointerDown = (event) => {
    if (!appMode || !onOpenMenu) return;
    if (event.button != null && event.button !== 0) return;
    startRef.current = { x: event.clientX, y: event.clientY };
    suppressClickRef.current = false;
    clearTimer();
    const point = { clientX: event.clientX, clientY: event.clientY };
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      suppressClickRef.current = true;
      onOpenMenu(point, node);
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

  const longPressProps = appMode && onOpenMenu
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

  return (
    <li>
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] text-slate-700 transition-colors hover:bg-white"
        onClick={() => {
          if (suppressClickRef.current) {
            suppressClickRef.current = false;
            return;
          }
          onSelect?.({ id: node.id, ...node.data });
        }}
        onContextMenu={(event) => {
          if (!onOpenMenu) return;
          event.preventDefault();
          onOpenMenu(event, node);
        }}
        {...longPressProps}
      >
        <Icon className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} style={{ color }} />
        <span className="truncate">{node.data?.label}</span>
      </button>
    </li>
  );
}

const IsolatedNodePanel = memo(({
  nodes = [],
  onSelect,
  onCopyNode,
  initialCollapsed = false,
  collapsed: controlledCollapsed,
  onCollapsedChange,
  showCollapsedTrigger = true,
  appMode = false,
}) => {
  const [internalCollapsed, setInternalCollapsed] = useState(initialCollapsed);
  const [contextMenu, setContextMenu] = useState(null);
  const menuRef = useRef(null);
  const collapsed = controlledCollapsed ?? internalCollapsed;
  const setCollapsed = (value) => {
    if (controlledCollapsed === undefined) setInternalCollapsed(value);
    onCollapsedChange?.(value);
  };
  const grouped = useMemo(() => {
    const isolated = nodes.filter(isIsolatedNode);
    return GROUPS.map((group) => ({
      ...group,
      items: isolated.filter((node) => group.matches(node.data)).sort(compareSiblings),
    })).filter((group) => group.items.length > 0);
  }, [nodes]);

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

  const openMenu = (event, node) => {
    const width = 168;
    const height = 44;
    setContextMenu({
      node,
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - width - 8)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - height - 8)),
    });
  };

  if (collapsed) {
    if (!showCollapsedTrigger) return null;
    return (
      <aside className="flex w-10 shrink-0 flex-col items-center border-l border-slate-200 bg-slate-50/80 py-2">
        <button
          type="button"
          onClick={() => setCollapsed(false)}
          className="rounded-md p-1.5 text-slate-500 transition-colors hover:bg-white hover:text-slate-700"
          title="展开角色与设定侧栏"
          aria-label="展开角色与设定侧栏"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="mt-2 select-none text-[11px] text-slate-400 [writing-mode:vertical-rl]">
          角色与设定
        </span>
      </aside>
    );
  }

  return (
    <aside
      data-testid="isolated-node-panel"
      className={`relative z-[55] w-52 shrink-0 overflow-y-auto border-l border-slate-200 bg-slate-50/80 ${
        appMode ? "pb-[calc(7rem+env(safe-area-inset-bottom))]" : ""
      }`}
    >
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 text-[13px] font-medium text-slate-500">
        <span>角色与设定</span>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className="rounded p-0.5 text-slate-400 transition-colors hover:bg-white hover:text-slate-600"
          title="收起角色与设定侧栏"
          aria-label="收起角色与设定侧栏"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
      {grouped.length === 0 ? (
        <p className="px-3 py-3 text-xs text-slate-400">暂无角色或设定</p>
      ) : (
        grouped.map((group) => (
          <section key={group.key} className="py-1">
            <h3 className="px-3 pb-0.5 pt-2 text-xs font-medium text-slate-400">
              {`${group.label} ${group.items.length}`}
            </h3>
            <ul>
              {group.items.map((node) => (
                <IsolatedNodeRow
                  key={node.id}
                  node={node}
                  icon={group.icon}
                  color={group.color}
                  onSelect={onSelect}
                  onOpenMenu={onCopyNode ? openMenu : undefined}
                  appMode={appMode}
                />
              ))}
            </ul>
          </section>
        ))
      )}
      {contextMenu && createPortal(
        <div
          ref={menuRef}
          className="fixed z-[80] min-w-[160px] rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button
            type="button"
            aria-label="复制到其他作品"
            onClick={() => {
              const node = contextMenu.node;
              setContextMenu(null);
              onCopyNode?.(node);
            }}
            className="w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
          >
            复制到其他作品
          </button>
        </div>,
        document.body,
      )}
    </aside>
  );
});

IsolatedNodePanel.displayName = "IsolatedNodePanel";

export default IsolatedNodePanel;
