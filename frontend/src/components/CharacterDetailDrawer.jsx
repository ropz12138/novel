import { X } from "lucide-react";

const LINK_TYPE_LABELS = {
  appear: "出场",
  lead: "主导",
  conflict: "冲突",
  ally: "结盟",
  foreshadow_trigger: "伏笔埋设",
  foreshadow_payoff: "伏笔回收",
};

const LINK_TYPE_COLORS = {
  appear: "bg-blue-100 text-blue-700",
  lead: "bg-blue-100 text-blue-700",
  conflict: "bg-red-100 text-red-700",
  ally: "bg-emerald-100 text-emerald-700",
  foreshadow_trigger: "bg-amber-100 text-amber-700",
  foreshadow_payoff: "bg-amber-100 text-amber-700",
};

/**
 * Extract character_links for a specific character and enrich with timeline info.
 */
export function getCharacterLinks(characterName, characterLinks, macroPhases) {
  if (!characterName || !Array.isArray(characterLinks)) return [];
  const links = characterLinks.filter(
    (link) => link && link.character_name === characterName
  );
  return links.map((link) => {
    const node = Array.isArray(macroPhases)
      ? macroPhases.find((t) => t && t.id === link.timeline_id)
      : null;
    return {
      ...link,
      timeline_title: node
        ? `${node.id} ${node.name || "宏观阶段"}`
        : link.timeline_id,
    };
  });
}

function Section({ title, children }) {
  return (
    <div className="border-t border-slate-200 px-5 py-3">
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
        {title}
      </h4>
      {children}
    </div>
  );
}

function FieldRow({ label, value }) {
  if (!value) return null;
  return (
    <div className="mb-1.5 text-sm">
      <span className="text-slate-500">{label}：</span>
      <span className="text-slate-800">{value}</span>
    </div>
  );
}

function FieldBlock({ label, value }) {
  if (!value) return null;
  return (
    <div className="mb-2">
      <div className="mb-0.5 text-xs text-slate-500">{label}</div>
      <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
        {value}
      </div>
    </div>
  );
}

/**
 * CharacterDetailDrawer — 右侧抽屉展示角色完整信息
 *
 * Props:
 *   character: object | null   — 当前选中的角色数据（CharacterOut）
 *   outlineTree: object        — outline_tree，用于提取 character_links 和 timeline
 *   onClose: function          — 关闭抽屉回调
 *   onLinkClick: function      — 点击剧情参与记录时回调 (link对象)
 */
export function CharacterDetailDrawer({
  character,
  outlineTree,
  onClose,
  onLinkClick,
}) {
  if (!character) return null;

  const characterLinks = getCharacterLinks(
    character.name,
    outlineTree?.character_links || [],
    outlineTree?.outline?.macro_phases || []
  );
  const relationships =
    character.relationships && typeof character.relationships === "object"
      ? character.relationships
      : {};

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* 遮罩 */}
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />

      {/* 抽屉面板 */}
      <div className="relative w-[380px] max-w-[90vw] flex flex-col bg-white shadow-xl animate-in slide-in-from-right">
        {/* 头部 */}
        <div className="flex items-start justify-between border-b border-slate-200 px-5 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {character.name || "未知角色"}
            </h2>
            <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
              <span className="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-medium text-violet-700">
                {character.role_type || "配角"}
              </span>
              {character.first_appearance_stage && (
                <span>首次出场阶段：{character.first_appearance_stage}</span>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="mt-1 flex h-7 w-7 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* 可滚动内容 */}
        <div className="flex-1 overflow-y-auto">
          {/* 基础设定 */}
          <Section title="基础设定">
            <div className="grid grid-cols-2 gap-x-4">
              <FieldRow label="性别" value={character.gender} />
              <FieldRow label="年龄" value={character.age} />
            </div>
            <FieldBlock label="外貌" value={character.appearance} />
            <FieldBlock label="性格" value={character.personality} />
            <FieldBlock label="背景" value={character.background} />
            <FieldBlock label="技能" value={character.skills} />
          </Section>

          {/* 动态状态 */}
          <Section title="动态状态">
            <FieldRow label="状态" value={character.current_status} />
            <FieldRow label="目标" value={character.current_goal} />
            <FieldRow label="位置" value={character.last_location} />
            {character.last_chapter && (
              <FieldRow
                label="最后出场"
                value={`第${character.last_chapter}章`}
              />
            )}
          </Section>

          {/* 剧情参与 */}
          <Section title={`剧情参与 (${characterLinks.length})`}>
            {characterLinks.length === 0 ? (
              <p className="text-xs text-slate-400">
                暂无剧情关联记录
              </p>
            ) : (
              <div className="space-y-2">
                {characterLinks.map((link, idx) => (
                  <button
                    key={`${link.timeline_id}-${link.link_type}-${idx}`}
                    type="button"
                    className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-left transition-colors hover:bg-slate-100"
                    onClick={() => onLinkClick?.(link)}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-slate-700">
                        {link.timeline_title}
                      </span>
                      <span
                        className={`shrink-0 rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${
                          LINK_TYPE_COLORS[link.link_type] ||
                          "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {LINK_TYPE_LABELS[link.link_type] || link.link_type}
                      </span>
                    </div>
                    {link.summary && (
                      <p className="mt-1 text-[11px] text-slate-500">
                        {link.summary}
                      </p>
                    )}
                  </button>
                ))}
              </div>
            )}
          </Section>

          {/* 角色关系 */}
          <Section title={`角色关系 (${Object.keys(relationships).length})`}>
            {Object.keys(relationships).length === 0 ? (
              <p className="text-xs text-slate-400">暂无角色关系记录</p>
            ) : (
              <div className="space-y-1.5">
                {Object.entries(relationships).map(([name, desc]) => (
                  <div
                    key={name}
                    className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-1.5 text-sm"
                  >
                    <span className="font-medium text-slate-700">{name}</span>
                    <span className="text-slate-400">—</span>
                    <span className="text-slate-600">{String(desc)}</span>
                  </div>
                ))}
              </div>
            )}
          </Section>

          {/* 备注 */}
          {character.notes && (
            <Section title="备注">
              <div className="whitespace-pre-wrap text-sm leading-relaxed text-slate-700">
                {character.notes}
              </div>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}
