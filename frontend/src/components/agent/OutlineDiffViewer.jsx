import { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Plus,
  Minus,
  Pencil,
  Trash2,
  BookOpen,
  GitBranch,
  Target,
  Star,
} from "lucide-react";

const SECTION_META = {
  story: { label: "主线故事", icon: Star, color: "text-violet-600 bg-violet-50" },
  macro_phases: { label: "大纲", icon: BookOpen, color: "text-blue-600 bg-blue-50" },
  meso_stages: { label: "中纲", icon: GitBranch, color: "text-teal-600 bg-teal-50" },
  foreshadowing: { label: "伏笔", icon: Target, color: "text-amber-600 bg-amber-50" },
};

const TYPE_ICON = {
  added: { Icon: Plus, color: "text-green-600 bg-green-50 border-green-200", label: "新增" },
  modified: { Icon: Pencil, color: "text-amber-600 bg-amber-50 border-amber-200", label: "修改" },
  removed: { Icon: Trash2, color: "text-red-600 bg-red-50 border-red-200", label: "删除" },
};

/**
 * 大纲结构化 diff 查看器。
 *
 * Props:
 * - diff: { story: [...], macro_phases: [...], meso_stages: [...], foreshadowing: [...] }
 * - summary: { total_added, total_modified, total_removed, total_changes }
 * - collapsed: boolean (initial collapsed state)
 */
export function OutlineDiffViewer({ diff = {}, summary = {}, collapsed: initialCollapsed = false }) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);

  const totalAdded = summary.total_added ?? 0;
  const totalModified = summary.total_modified ?? 0;
  const totalRemoved = summary.total_removed ?? 0;
  const total = summary.total_changes ?? totalAdded + totalModified + totalRemoved;

  if (total === 0) return null;

  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 bg-slate-50 border-b border-slate-200 text-left"
      >
        <BookOpen className="h-3.5 w-3.5 text-slate-500" />
        <span className="text-xs font-medium text-slate-700">大纲变更</span>
        <span className="ml-auto flex items-center gap-2 text-[11px]">
          {totalAdded > 0 && (
            <span className="flex items-center gap-0.5 text-green-600">
              <Plus className="h-3 w-3" /> {totalAdded}
            </span>
          )}
          {totalModified > 0 && (
            <span className="flex items-center gap-0.5 text-amber-600">
              <Pencil className="h-3 w-3" /> {totalModified}
            </span>
          )}
          {totalRemoved > 0 && (
            <span className="flex items-center gap-0.5 text-red-600">
              <Minus className="h-3 w-3" /> {totalRemoved}
            </span>
          )}
        </span>
        {collapsed ? (
          <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
        ) : (
          <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
        )}
      </button>

      {/* Content */}
      {!collapsed && (
        <div className="max-h-[500px] overflow-y-auto overscroll-contain p-3 space-y-3">
          {/* Story section */}
          {diff.story && diff.story.length > 0 && (
            <OutlineSection key="story" sectionKey="story" items={diff.story} />
          )}
          {/* Macro phases section */}
          {diff.macro_phases && diff.macro_phases.length > 0 && (
            <OutlineSection key="macro_phases" sectionKey="macro_phases" items={diff.macro_phases} />
          )}
          {/* Meso stages section */}
          {diff.meso_stages && diff.meso_stages.length > 0 && (
            <OutlineSection key="meso_stages" sectionKey="meso_stages" items={diff.meso_stages} />
          )}
          {/* Foreshadowing section */}
          {diff.foreshadowing && diff.foreshadowing.length > 0 && (
            <OutlineSection key="foreshadowing" sectionKey="foreshadowing" items={diff.foreshadowing} />
          )}
        </div>
      )}
    </div>
  );
}

function OutlineSection({ sectionKey, items }) {
  const meta = SECTION_META[sectionKey] || { label: sectionKey, icon: Star, color: "text-slate-600 bg-slate-50" };
  const Icon = meta.icon;

  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className={`inline-flex items-center justify-center rounded p-1 ${meta.color}`}>
          <Icon className="h-3 w-3" />
        </span>
        <span className="text-[11px] font-semibold text-slate-600 uppercase tracking-wide">{meta.label}</span>
      </div>
      <div className="space-y-1.5">
        {sectionKey === "story"
          ? items.map((item, i) => <StoryFieldChange key={i} item={item} />)
          : items.map((item, i) => <NodeChange key={i} item={item} />)}
      </div>
    </div>
  );
}

function StoryFieldChange({ item }) {
  const ti = TYPE_ICON[item.type] || TYPE_ICON.modified;
  const Icon = ti.Icon;

  return (
    <div className={`flex items-start gap-2 rounded border px-2 py-1.5 text-[12px] ${ti.color}`}>
      <Icon className="h-3 w-3 mt-0.5 shrink-0" />
      <div className="min-w-0">
        <span className="font-medium text-slate-700">{item.field}</span>
        {item.type === "added" && (
          <span className="ml-1.5 text-green-700">{String(item.new ?? "")}</span>
        )}
        {item.type === "removed" && (
          <span className="ml-1.5 text-red-700 line-through">{String(item.old ?? "")}</span>
        )}
        {item.type === "modified" && (
          <span className="ml-1.5">
            <span className="text-red-600 line-through">{String(item.old ?? "")}</span>
            <span className="mx-1 text-slate-400">→</span>
            <span className="text-green-600">{String(item.new ?? "")}</span>
          </span>
        )}
      </div>
    </div>
  );
}

function NodeChange({ item }) {
  const ti = TYPE_ICON[item.type] || TYPE_ICON.modified;
  const Icon = ti.Icon;
  const label = item.node_id || "?";

  return (
    <div className={`rounded border px-2 py-1.5 text-[12px] ${ti.color}`}>
      <div className="flex items-center gap-1.5 mb-1">
        <Icon className="h-3 w-3 shrink-0" />
        <span className="font-mono font-semibold text-[11px] text-slate-600">[{label}]</span>
        <span className="text-[10px] text-slate-500">{ti.label}</span>
        {item.data?.development_node && (
          <span className="text-slate-600 truncate ml-1">{item.data.development_node}</span>
        )}
        {item.data?.name && (
          <span className="text-slate-600 truncate ml-1">{item.data.name}</span>
        )}
        {item.data?.content && (
          <span className="text-slate-600 truncate ml-1 max-w-[200px]">{item.data.content}</span>
        )}
      </div>
      {/* Show added node data */}
      {item.type === "added" && item.data && <NodeDataFields data={item.data} />}
      {/* Show removed node data */}
      {item.type === "removed" && item.data && (
        <NodeDataFields data={item.data} strikeThrough />
      )}
      {/* Show modified fields */}
      {item.type === "modified" && item.changes && (
        <div className="ml-5 space-y-0.5">
          {item.changes.map((c, i) => (
            <FieldChange key={i} change={c} />
          ))}
        </div>
      )}
    </div>
  );
}

function NodeDataFields({ data, strikeThrough }) {
  const displayFields = ["development_node", "name", "summary", "content", "time_node", "chapter_start", "chapter_end", "attach_to", "side", "plant_node", "payoff_node"];
  const entries = Object.entries(data).filter(([k]) => displayFields.includes(k) && data[k]);
  if (entries.length === 0) return null;

  return (
    <div className="ml-5 space-y-0.5">
      {entries.map(([key, val]) => (
        <div key={key} className={`text-[11px] ${strikeThrough ? "line-through text-red-600/70" : "text-green-700"}`}>
          <span className="text-slate-500">{key}: </span>
          {String(val)}
        </div>
      ))}
    </div>
  );
}

function FieldChange({ change }) {
  if (change.type === "added") {
    return (
      <div className="text-[11px]">
        <span className="text-slate-500">{change.field}: </span>
        <span className="text-green-700">{String(change.new ?? "")}</span>
      </div>
    );
  }
  if (change.type === "removed") {
    return (
      <div className="text-[11px]">
        <span className="text-slate-500">{change.field}: </span>
        <span className="text-red-600 line-through">{String(change.old ?? "")}</span>
      </div>
    );
  }
  return (
    <div className="text-[11px]">
      <span className="text-slate-500">{change.field}: </span>
      <span className="text-red-600 line-through">{String(change.old ?? "")}</span>
      <span className="mx-0.5 text-slate-400">→</span>
      <span className="text-green-600">{String(change.new ?? "")}</span>
    </div>
  );
}
