import { API_BASE } from "../lib/runtime-config";
import { authFetch } from "../lib/authFetch";
import { useEffect, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Loader2,
  Pencil,
  Plus,
  Trash2,
  UserCircle,
  Search,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";


const ROLE_TYPES = ["主角", "配角", "反派", "龙套", "路人"];
const STATUS_OPTIONS = ["存活", "死亡", "失踪", "受伤", "修炼中", "昏迷"];

/* ────────── Role type color mapping ────────── */
const ROLE_COLORS = {
  主角: "bg-blue-500",
  male_lead: "bg-blue-500",
  女主: "bg-pink-500",
  female_lead: "bg-pink-500",
  配角: "bg-slate-400",
  supporting: "bg-slate-400",
  反派: "bg-red-500",
  villain: "bg-red-500",
  龙套: "bg-slate-300",
  passerby: "bg-slate-300",
};

function roleColor(roleType) {
  return ROLE_COLORS[roleType] || "bg-slate-300";
}

/* ────────── Character Form Modal ────────── */
function CharacterForm({ character, onSave, onCancel }) {
  const [form, setForm] = useState({
    name: "",
    role_type: "配角",
    gender: "",
    age: "",
    appearance: "",
    personality: "",
    background: "",
    skills: "",
    current_status: "存活",
    current_goal: "",
    last_location: "",
    first_chapter: "",
    notes: "",
    ...character,
  });

  const handleChange = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleSubmit = () => {
    const data = {
      ...form,
      first_chapter: form.first_chapter ? parseInt(form.first_chapter, 10) : null,
    };
    onSave(data);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="max-h-[90vh] w-[520px] overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold text-slate-800">
          {character ? "编辑角色" : "新建角色"}
        </h2>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">角色名 *</label>
              <Input value={form.name} onChange={(e) => handleChange("name", e.target.value)} placeholder="张三" />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">角色类型</label>
              <select value={form.role_type} onChange={(e) => handleChange("role_type", e.target.value)} className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm">
                {ROLE_TYPES.map((r) => (<option key={r} value={r}>{r}</option>))}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">性别</label>
              <Input value={form.gender} onChange={(e) => handleChange("gender", e.target.value)} placeholder="男" />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">年龄</label>
              <Input value={form.age} onChange={(e) => handleChange("age", e.target.value)} placeholder="约二十五岁" />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">外貌</label>
            <Textarea value={form.appearance} onChange={(e) => handleChange("appearance", e.target.value)} rows={2} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">性格</label>
            <Textarea value={form.personality} onChange={(e) => handleChange("personality", e.target.value)} rows={2} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">背景</label>
            <Textarea value={form.background} onChange={(e) => handleChange("background", e.target.value)} rows={2} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">能力</label>
            <Textarea value={form.skills} onChange={(e) => handleChange("skills", e.target.value)} rows={2} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">状态</label>
              <select value={form.current_status} onChange={(e) => handleChange("current_status", e.target.value)} className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm">
                {STATUS_OPTIONS.map((s) => (<option key={s} value={s}>{s}</option>))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">首次出场</label>
              <Input type="number" value={form.first_chapter} onChange={(e) => handleChange("first_chapter", e.target.value)} placeholder="1" />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">当前目的</label>
            <Input value={form.current_goal} onChange={(e) => handleChange("current_goal", e.target.value)} placeholder="角色当前目标" />
          </div>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="outline" onClick={onCancel}>取消</Button>
          <Button onClick={handleSubmit} disabled={!form.name.trim()}>保存</Button>
        </div>
      </div>
    </div>
  );
}

/* ────────── Compact Character Card (sidebar mode) ────────── */
function CompactCard({ char, onEdit, onDelete, expanded, onToggle }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white transition-shadow hover:shadow-sm">
      {/* Header row — always visible */}
      <button
        onClick={onToggle}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <span className={`h-2 w-2 shrink-0 rounded-full ${roleColor(char.role_type)}`} />
        <span className="flex-1 truncate text-xs font-medium text-slate-800">{char.name}</span>
        <span className="shrink-0 rounded-full bg-slate-100 px-1.5 py-0.5 text-[9px] text-slate-500">
          {char.role_type}
        </span>
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-slate-100 px-3 pb-2 pt-1.5 space-y-1 text-[11px] text-slate-500">
          {char.current_status && (
            <p><span className="text-slate-400">状态：</span>{char.current_status}</p>
          )}
          {char.current_goal && (
            <p className="truncate"><span className="text-slate-400">目的：</span>{char.current_goal}</p>
          )}
          {char.gender && <p><span className="text-slate-400">性别：</span>{char.gender}</p>}
          {char.age && <p><span className="text-slate-400">年龄：</span>{char.age}</p>}
          {char.appearance && (
            <p className="line-clamp-2"><span className="text-slate-400">外貌：</span>{char.appearance}</p>
          )}
          {char.personality && (
            <p className="line-clamp-2"><span className="text-slate-400">性格：</span>{char.personality}</p>
          )}
          {char.skills && (
            <p className="line-clamp-2"><span className="text-slate-400">能力：</span>{char.skills}</p>
          )}
          {char.first_chapter && (
            <p><span className="text-slate-400">出场：</span>第{char.first_chapter}章</p>
          )}
          <div className="flex gap-1 pt-1">
            <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px]" onClick={(e) => { e.stopPropagation(); onEdit(char); }}>
              <Pencil className="mr-1 h-3 w-3" /> 编辑
            </Button>
            <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px] text-red-500 hover:text-red-600" onClick={(e) => { e.stopPropagation(); onDelete(char.id); }}>
              <Trash2 className="mr-1 h-3 w-3" /> 删除
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ────────── Main Sidebar Component ────────── */
export function CharacterSidebar({ workId, open, onToggle }) {
  const [characters, setCharacters] = useState([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);

  const fetchCharacters = async () => {
    if (!workId) return;
    setLoading(true);
    try {
      const res = await authFetch(`${API_BASE}/works/${workId}/characters`);
      const data = await res.json();
      setCharacters(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCharacters();
  }, [workId]);

  const handleSave = async (data) => {
    const isEdit = editing && editing.id;
    const url = isEdit
      ? `${API_BASE}/works/${workId}/characters/${editing.id}`
      : `${API_BASE}/works/${workId}/characters`;
    const method = isEdit ? "PUT" : "POST";

    try {
      const res = await authFetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json();
        alert(err.detail || "保存失败");
        return;
      }
      await fetchCharacters();
      setShowForm(false);
      setEditing(null);
    } catch (e) {
      console.error(e);
      alert("保存失败");
    }
  };

  const handleDelete = async (id) => {
    if (!confirm("确定要删除这个角色吗？")) return;
    try {
      await authFetch(`${API_BASE}/works/${workId}/characters/${id}`, { method: "DELETE" });
      await fetchCharacters();
    } catch (e) {
      console.error(e);
    }
  };

  const filtered = search
    ? characters.filter((c) => c.name.includes(search))
    : characters;

  /* ── Collapsed state: narrow strip ── */
  if (!open) {
    return (
      <div className="flex w-[36px] shrink-0 flex-col items-center border-r border-slate-200 bg-slate-50 py-3">
        <button
          onClick={onToggle}
          className="flex h-8 w-8 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-200 hover:text-slate-600"
          title="展开角色面板"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
        <div className="mt-3 flex flex-col items-center gap-1.5">
          {characters.slice(0, 6).map((c) => (
            <div
              key={c.id}
              className={`h-2 w-2 rounded-full ${roleColor(c.role_type)}`}
              title={c.name}
            />
          ))}
        </div>
        {characters.length > 6 && (
          <span className="mt-1 text-[9px] text-slate-400">+{characters.length - 6}</span>
        )}
      </div>
    );
  }

  /* ── Expanded state ── */
  return (
    <>
      <div className="flex w-[260px] shrink-0 flex-col border-r border-slate-200 bg-slate-50">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-200 px-3 py-2">
          <div className="flex items-center gap-1.5">
            <UserCircle className="h-3.5 w-3.5 text-slate-500" />
            <span className="text-xs font-medium text-slate-700">角色</span>
            <span className="rounded-full bg-slate-200 px-1.5 py-0.5 text-[9px] text-slate-500">
              {characters.length}
            </span>
          </div>
          <button
            onClick={onToggle}
            className="flex h-6 w-6 items-center justify-center rounded text-slate-400 hover:bg-slate-200 hover:text-slate-600"
            title="收起"
          >
            <ChevronLeft className="h-4 w-4" />
          </button>
        </div>

        {/* Search + Add */}
        <div className="flex items-center gap-1.5 border-b border-slate-200 px-3 py-2">
          <div className="relative flex-1">
            <Search className="absolute left-2 top-1/2 h-3 w-3 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="搜索角色..."
              className="w-full rounded-md border border-slate-200 bg-white py-1 pl-7 pr-2 text-[11px] placeholder:text-slate-400 focus:border-blue-300 focus:outline-none"
            />
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-7 w-7 shrink-0 p-0"
            onClick={() => { setEditing(null); setShowForm(true); }}
            title="新建角色"
          >
            <Plus className="h-4 w-4 text-slate-500" />
          </Button>
        </div>

        {/* Character list */}
        <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center py-8 text-slate-400">
              <UserCircle className="h-6 w-6 mb-1" />
              <p className="text-[10px]">{search ? "未找到角色" : "暂无角色"}</p>
            </div>
          ) : (
            filtered.map((char) => (
              <CompactCard
                key={char.id}
                char={char}
                expanded={expandedId === char.id}
                onToggle={() => setExpandedId(expandedId === char.id ? null : char.id)}
                onEdit={(c) => { setEditing(c); setShowForm(true); }}
                onDelete={handleDelete}
              />
            ))
          )}
        </div>
      </div>

      {/* Form modal */}
      {showForm && (
        <CharacterForm
          character={editing}
          onSave={handleSave}
          onCancel={() => { setShowForm(false); setEditing(null); }}
        />
      )}
    </>
  );
}
