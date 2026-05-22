import { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Plus,
  Minus,
  Pencil,
  FileText,
  ListChecks,
  Users,
  Target,
  BookOpen,
  Link2,
  Lightbulb,
} from "lucide-react";

const TYPE_ICON = {
  added: { Icon: Plus, color: "text-green-600 bg-green-50 border-green-200", label: "新增" },
  modified: { Icon: Pencil, color: "text-amber-600 bg-amber-50 border-amber-200", label: "修改" },
  removed: { Icon: Minus, color: "text-red-600 bg-red-50 border-red-200", label: "删除" },
};

const SECTION_META = {
  summary: { label: "摘要", icon: FileText, color: "text-slate-600 bg-slate-50" },
  key_plot_points: { label: "关键剧情点", icon: ListChecks, color: "text-blue-600 bg-blue-50" },
  involved_characters: { label: "出场角色", icon: Users, color: "text-purple-600 bg-purple-50" },
  foreshadows: { label: "伏笔", icon: Target, color: "text-amber-600 bg-amber-50" },
  facts: { label: "事实设定", icon: Lightbulb, color: "text-teal-600 bg-teal-50" },
  outline_links: { label: "大纲关联", icon: Link2, color: "text-indigo-600 bg-indigo-50" },
};

/**
 * Metadata structured diff viewer.
 *
 * Props:
 * - diff: structured diff data from backend
 * - summary: { total_added, total_modified, total_removed, total_changes }
 * - collapsed: boolean (initial collapsed state)
 */
export function MetadataDiffViewer({ diff = {}, summary = {}, collapsed: initialCollapsed = false }) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);

  const totalAdded = summary.total_added ?? 0;
  const totalModified = summary.total_modified ?? 0;
  const totalRemoved = summary.total_removed ?? 0;
  const total = summary.total_changes ?? totalAdded + totalModified + totalRemoved;

  if (total === 0) return null;

  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 bg-slate-50 border-b border-slate-200 text-left"
      >
        <BookOpen className="h-3.5 w-3.5 text-slate-500" />
        <span className="text-xs font-medium text-slate-700">元数据变更</span>
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

      {!collapsed && (
        <div className="max-h-[500px] overflow-y-auto overscroll-contain p-3 space-y-3">
          {diff.summary && <SummaryChange key="summary" data={diff.summary} />}
          {diff.key_plot_points && diff.key_plot_points.length > 0 && (
            <StringListSection key="key_plot_points" sectionKey="key_plot_points" items={diff.key_plot_points} />
          )}
          {diff.involved_characters && diff.involved_characters.length > 0 && (
            <DictListSection key="involved_characters" sectionKey="involved_characters" items={diff.involved_characters} />
          )}
          {diff.foreshadows && diff.foreshadows.length > 0 && (
            <DictListSection key="foreshadows" sectionKey="foreshadows" items={diff.foreshadows} />
          )}
          {diff.facts && diff.facts.length > 0 && (
            <DictListSection key="facts" sectionKey="facts" items={diff.facts} />
          )}
          {diff.outline_links && diff.outline_links.length > 0 && (
            <DictListSection key="outline_links" sectionKey="outline_links" items={diff.outline_links} />
          )}
        </div>
      )}
    </div>
  );
}

function SummaryChange({ data }) {
  const ti = TYPE_ICON[data.type] || TYPE_ICON.modified;
  const Icon = ti.Icon;

  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="inline-flex items-center justify-center rounded p-1 text-slate-600 bg-slate-50">
          <FileText className="h-3 w-3" />
        </span>
        <span className="text-[11px] font-semibold text-slate-600 uppercase tracking-wide">摘要</span>
      </div>
      <div className={`rounded border px-2 py-1.5 text-[12px] ${ti.color}`}>
        <div className="flex items-center gap-1.5 mb-1">
          <Icon className="h-3 w-3 shrink-0" />
          <span className="text-[10px] text-slate-500">{ti.label}</span>
        </div>
        {data.type === "added" && (
          <p className="text-green-700 whitespace-pre-wrap ml-5">{data.new || "（空）"}</p>
        )}
        {data.type === "modified" && (
          <div className="ml-5 space-y-1">
            <p className="text-red-600 line-through whitespace-pre-wrap">{data.old || "（空）"}</p>
            <p className="text-green-600 whitespace-pre-wrap">{data.new || "（空）"}</p>
          </div>
        )}
      </div>
    </div>
  );
}

function StringListSection({ sectionKey, items }) {
  const meta = SECTION_META[sectionKey] || { label: sectionKey, icon: ListChecks, color: "text-slate-600 bg-slate-50" };
  const Icon = meta.icon;

  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className={`inline-flex items-center justify-center rounded p-1 ${meta.color}`}>
          <Icon className="h-3 w-3" />
        </span>
        <span className="text-[11px] font-semibold text-slate-600 uppercase tracking-wide">{meta.label}</span>
      </div>
      <div className="space-y-1">
        {items.map((item, i) => {
          const ti = TYPE_ICON[item.type] || TYPE_ICON.added;
          const TIcon = ti.Icon;
          return (
            <div key={i} className={`flex items-start gap-2 rounded border px-2 py-1 text-[12px] ${ti.color}`}>
              <TIcon className="h-3 w-3 mt-0.5 shrink-0" />
              <span className={item.type === "removed" ? "line-through text-red-700" : item.type === "added" ? "text-green-700" : "text-slate-700"}>
                {item.value || item.content || String(item)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function DictListSection({ sectionKey, items }) {
  const meta = SECTION_META[sectionKey] || { label: sectionKey, icon: ListChecks, color: "text-slate-600 bg-slate-50" };
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
        {items.map((item, i) => (
          <DictItemChange key={i} item={item} />
        ))}
      </div>
    </div>
  );
}

function DictItemChange({ item }) {
  const ti = TYPE_ICON[item.type] || TYPE_ICON.modified;
  const Icon = ti.Icon;
  const label = item.name || item.content || item.key || item.id || "?";

  return (
    <div className={`rounded border px-2 py-1.5 text-[12px] ${ti.color}`}>
      <div className="flex items-center gap-1.5 mb-1">
        <Icon className="h-3 w-3 shrink-0" />
        <span className="font-medium text-slate-700 truncate max-w-[300px]">{label}</span>
        <span className="text-[10px] text-slate-500">{ti.label}</span>
      </div>
      {item.type === "added" && item.data && <DictDataFields data={item.data} />}
      {item.type === "removed" && item.data && <DictDataFields data={item.data} strikeThrough />}
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

function DictDataFields({ data, strikeThrough }) {
  const entries = Object.entries(data).filter(([, v]) => v !== null && v !== undefined && v !== "");
  if (entries.length === 0) return null;

  return (
    <div className="ml-5 space-y-0.5">
      {entries.map(([key, val]) => (
        <div key={key} className={`text-[11px] ${strikeThrough ? "line-through text-red-600/70" : "text-green-700"}`}>
          <span className="text-slate-500">{key}: </span>
          {typeof val === "object" ? JSON.stringify(val) : String(val)}
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
        <span className="text-green-700">{formatValue(change.new)}</span>
      </div>
    );
  }
  if (change.type === "removed") {
    return (
      <div className="text-[11px]">
        <span className="text-slate-500">{change.field}: </span>
        <span className="text-red-600 line-through">{formatValue(change.old)}</span>
      </div>
    );
  }
  return (
    <div className="text-[11px]">
      <span className="text-slate-500">{change.field}: </span>
      <span className="text-red-600 line-through">{formatValue(change.old)}</span>
      <span className="mx-0.5 text-slate-400">{"\u2192"}</span>
      <span className="text-green-600">{formatValue(change.new)}</span>
    </div>
  );
}

function formatValue(val) {
  if (val === null || val === undefined) return "";
  if (typeof val === "object") return JSON.stringify(val);
  return String(val);
}
