import { memo, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { isIsolatedNode } from "../../lib/canvasRelation";
import { compareSiblings } from "../../lib/canvasOrder";

/**
 * 非层级链节点的侧栏入口。
 *
 * character、worldbuilding、note 不参与树布局，也不渲染到画布主干。
 * 右侧「角色与设定」提供常驻入口：角色按 scope 分组，另加世界观与笔记。
 *
 * character 按 scope 细分：后端强校验其取值只能是以下四种。
 */
const CHARACTER_SCOPES = [
  { scope: "global", label: "主角" },
  { scope: "major", label: "主要配角" },
  { scope: "minor", label: "次要配角" },
  { scope: "temp", label: "临时角色" },
];

const GROUPS = [
  ...CHARACTER_SCOPES.map(({ scope, label }) => ({
    key: `character:${scope}`,
    label,
    icon: "👤",
    matches: (data) => data?.type === "character" && data?.scope === scope,
  })),
  {
    key: "worldbuilding",
    label: "世界观",
    icon: "🌍",
    matches: (data) => data?.type === "worldbuilding",
  },
  {
    key: "note",
    label: "笔记",
    icon: "📝",
    matches: (data) => data?.type === "note",
  },
];

const IsolatedNodePanel = memo(({ nodes = [], onSelect }) => {
  const [collapsed, setCollapsed] = useState(false);
  const grouped = useMemo(() => {
    const isolated = nodes.filter(isIsolatedNode);
    return GROUPS.map((group) => ({
      ...group,
      items: isolated.filter((node) => group.matches(node.data)).sort(compareSiblings),
    })).filter((group) => group.items.length > 0);
  }, [nodes]);

  if (collapsed) {
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
    <aside className="w-52 shrink-0 border-l border-slate-200 bg-slate-50/80 overflow-y-auto">
      <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2 text-xs font-medium text-slate-400">
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
            <h3 className="px-3 py-1 text-[11px] text-slate-400">
              {`${group.label} ${group.items.length}`}
            </h3>
            <ul>
              {group.items.map((node) => (
                <li key={node.id}>
                  <button
                    type="button"
                    className="w-full flex items-center gap-1.5 px-3 py-1.5 text-left text-xs text-slate-600 hover:bg-white transition-colors"
                    onClick={() => onSelect?.({ id: node.id, ...node.data })}
                  >
                    <span>{group.icon}</span>
                    <span className="truncate">{node.data?.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ))
      )}
    </aside>
  );
});

IsolatedNodePanel.displayName = "IsolatedNodePanel";

export default IsolatedNodePanel;
