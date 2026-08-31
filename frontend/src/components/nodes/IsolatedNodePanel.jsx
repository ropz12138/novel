import { memo, useMemo } from "react";
import { isIsolatedNode } from "../../lib/canvasRelation";
import { compareSiblings } from "../../lib/canvasOrder";

/**
 * 孤立节点入口。
 *
 * worldbuilding、note 与主角 character 被后端禁止连线，在图中没有任何边。
 * 若让它们以"根节点"身份进入画布，数十条世界观与笔记会占满画布，
 * 主干结构的紧凑性就没有意义了。这里改为按类型聚合的侧边列表。
 */
const GROUPS = [
  { key: "character", label: "主角" },
  { key: "worldbuilding", label: "世界观" },
  { key: "note", label: "笔记" },
];

const ICONS = {
  character: "👤",
  worldbuilding: "🌍",
  note: "📝",
};

const IsolatedNodePanel = memo(({ nodes = [], onSelect }) => {
  const grouped = useMemo(() => {
    const isolated = nodes.filter(isIsolatedNode);
    return GROUPS.map((group) => ({
      ...group,
      items: isolated
        .filter((node) => node.data?.type === group.key)
        .sort(compareSiblings),
    })).filter((group) => group.items.length > 0);
  }, [nodes]);

  return (
    <aside className="w-52 shrink-0 border-l border-slate-200 bg-slate-50/80 overflow-y-auto">
      <div className="px-3 py-2 text-xs font-medium text-slate-400 border-b border-slate-200">
        全局节点
      </div>
      {grouped.length === 0 ? (
        <p className="px-3 py-3 text-xs text-slate-400">暂无全局节点</p>
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
                    <span>{ICONS[group.key]}</span>
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
