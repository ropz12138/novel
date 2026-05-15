import { useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Plus,
  Minus,
  Pencil,
  Trash2,
  Users,
} from "lucide-react";

const TYPE_ICON = {
  added: { Icon: Plus, color: "text-green-600 bg-green-50 border-green-200", label: "新增" },
  modified: { Icon: Pencil, color: "text-amber-600 bg-amber-50 border-amber-200", label: "修改" },
  removed: { Icon: Trash2, color: "text-red-600 bg-red-50 border-red-200", label: "删除" },
};

const FIELD_LABELS = {
  name: "姓名",
  role_type: "角色类型",
  gender: "性别",
  age: "年龄",
  appearance: "外貌",
  personality: "性格",
  background: "背景",
  skills: "能力",
  current_status: "状态",
  current_goal: "目的",
  first_chapter: "出场章节",
  notes: "备注",
};

/**
 * 角色结构化 diff 查看器。
 *
 * Props:
 * - diff: { changes: [{ type, name, data?, changes? }] }
 * - summary: { total_added, total_modified, total_removed, total_changes }
 * - collapsed: boolean (initial collapsed state)
 */
export function CharacterDiffViewer({ diff = {}, summary = {}, collapsed: initialCollapsed = false }) {
  const [collapsed, setCollapsed] = useState(initialCollapsed);

  const changes = diff.changes || [];
  const totalAdded = summary.total_added ?? 0;
  const totalModified = summary.total_modified ?? 0;
  const totalRemoved = summary.total_removed ?? 0;
  const total = summary.total_changes ?? totalAdded + totalModified + totalRemoved;

  if (total === 0 || changes.length === 0) return null;

  return (
    <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 bg-slate-50 border-b border-slate-200 text-left"
      >
        <Users className="h-3.5 w-3.5 text-slate-500" />
        <span className="text-xs font-medium text-slate-700">角色变更</span>
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
        <div className="max-h-[500px] overflow-y-auto overscroll-contain p-3 space-y-2">
          {changes.map((item, i) => (
            <CharacterChange key={i} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

function CharacterChange({ item }) {
  const ti = TYPE_ICON[item.type] || TYPE_ICON.modified;
  const Icon = ti.Icon;

  return (
    <div className={`rounded border px-2.5 py-2 text-[12px] ${ti.color}`}>
      <div className="flex items-center gap-1.5 mb-1">
        <Icon className="h-3 w-3 shrink-0" />
        <span className="font-semibold text-slate-700">{item.name}</span>
        <span className="text-[10px] text-slate-500">{ti.label}</span>
      </div>

      {/* Added: show full data */}
      {item.type === "added" && item.data && (
        <div className="ml-5 grid grid-cols-2 gap-x-3 gap-y-0.5">
          {Object.entries(item.data)
            .filter(([, v]) => v)
            .map(([key, val]) => (
              <div key={key} className="text-[11px]">
                <span className="text-slate-500">{FIELD_LABELS[key] || key}: </span>
                <span className="text-green-700">{String(val)}</span>
              </div>
            ))}
        </div>
      )}

      {/* Removed: show summary */}
      {item.type === "removed" && item.data && (
        <div className="ml-5 text-[11px] text-red-600/70">
          {item.data.role_type && <span>{item.data.role_type} · </span>}
          {item.data.gender && <span>{item.data.gender} · </span>}
          {item.data.personality && <span>{item.data.personality}</span>}
        </div>
      )}

      {/* Modified: show field changes */}
      {item.type === "modified" && item.changes && (
        <div className="ml-5 space-y-0.5">
          {item.changes.map((c, i) => (
            <CharFieldChange key={i} change={c} />
          ))}
        </div>
      )}
    </div>
  );
}

function CharFieldChange({ change }) {
  const label = FIELD_LABELS[change.field] || change.field;

  if (change.type === "added") {
    return (
      <div className="text-[11px]">
        <span className="text-slate-500">{label}: </span>
        <span className="text-green-700">{String(change.new ?? "")}</span>
      </div>
    );
  }
  if (change.type === "removed") {
    return (
      <div className="text-[11px]">
        <span className="text-slate-500">{label}: </span>
        <span className="text-red-600 line-through">{String(change.old ?? "")}</span>
      </div>
    );
  }
  return (
    <div className="text-[11px]">
      <span className="text-slate-500">{label}: </span>
      <span className="text-red-600 line-through">{String(change.old ?? "")}</span>
      <span className="mx-0.5 text-slate-400">→</span>
      <span className="text-green-600">{String(change.new ?? "")}</span>
    </div>
  );
}
