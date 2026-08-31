import { memo, useMemo } from "react";
import { isIsolatedNode } from "../../lib/canvasRelation";
import { compareSiblings } from "../../lib/canvasOrder";

/**
 * 非层级链节点的侧栏入口。
 *
 * character、worldbuilding、note 不参与树布局。worldbuilding 与 note 被后端
 * 禁止连线，在图中没有任何边；若让它们以"根节点"身份进入画布，数十条设定
 * 会占满画布，主干的紧凑性就没有意义了。配角虽有关联边，但只在选中关联结构
 * 节点时作为卫星出现，因此同样需要一个常驻入口，否则默认视图下无处可寻。
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
  const grouped = useMemo(() => {
    const isolated = nodes.filter(isIsolatedNode);
    return GROUPS.map((group) => ({
      ...group,
      items: isolated.filter((node) => group.matches(node.data)).sort(compareSiblings),
    })).filter((group) => group.items.length > 0);
  }, [nodes]);

  return (
    <aside className="w-52 shrink-0 border-l border-slate-200 bg-slate-50/80 overflow-y-auto">
      <div className="px-3 py-2 text-xs font-medium text-slate-400 border-b border-slate-200">
        角色与设定
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
