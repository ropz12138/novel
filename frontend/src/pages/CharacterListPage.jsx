import { characterApi } from "../lib/rpcApi";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Loader2,
  Plus,
  Trash2,
  UserCircle,
  Pencil,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";


const ROLE_TYPES = ["主角", "配角", "反派", "龙套", "路人"];
const STATUS_OPTIONS = ["存活", "死亡", "失踪", "受伤", "修炼中", "昏迷"];

function CharacterCard({ char, onEdit, onDelete }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 transition-shadow hover:shadow-md">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-blue-100 text-blue-600">
            <UserCircle className="h-5 w-5" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-slate-800">{char.name}</h3>
            <span className="rounded-full bg-purple-100 px-2 py-0.5 text-[10px] font-medium text-purple-700">
              {char.role_type}
            </span>
          </div>
        </div>
        <div className="flex gap-1">
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => onEdit(char)}>
            <Pencil className="h-3.5 w-3.5 text-slate-400" />
          </Button>
          <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => onDelete(char.id)}>
            <Trash2 className="h-3.5 w-3.5 text-red-400" />
          </Button>
        </div>
      </div>
      <div className="mt-2 space-y-1 text-xs text-slate-500">
        {char.gender && <p>性别：{char.gender}</p>}
        {char.age && <p>年龄：{char.age}</p>}
        <p>状态：{char.current_status || "—"}</p>
        <p>目的：{char.current_goal || "—"}</p>
        {char.last_location && <p>位置：{char.last_location}</p>}
        {char.first_appearance_stage && <p>首次出场阶段：{char.first_appearance_stage}</p>}
        {char.appearance && <p>外貌：{char.appearance}</p>}
        {char.personality && <p>性格：{char.personality}</p>}
        {char.background && <p>背景：{char.background}</p>}
        {char.skills && <p>技能：{char.skills}</p>}
        {char.notes && <p>备注：{char.notes}</p>}
      </div>
    </div>
  );
}

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
    first_appearance_stage: "",
    notes: "",
    ...character,
  });

  const handleChange = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const handleSubmit = () => {
    const data = {
      ...form,
      first_appearance_stage: form.first_appearance_stage || null,
    };
    onSave(data);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="max-h-[90vh] w-[600px] overflow-y-auto rounded-lg bg-white p-6 shadow-xl">
        <h2 className="mb-4 text-lg font-semibold text-slate-800">
          {character ? "编辑角色" : "新建角色"}
        </h2>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">角色名 *</label>
              <Input
                value={form.name}
                onChange={(e) => handleChange("name", e.target.value)}
                placeholder="张三"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">角色类型</label>
              <select
                value={form.role_type}
                onChange={(e) => handleChange("role_type", e.target.value)}
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
              >
                {ROLE_TYPES.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">性别</label>
              <Input
                value={form.gender}
                onChange={(e) => handleChange("gender", e.target.value)}
                placeholder="男"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">年龄</label>
              <Input
                value={form.age}
                onChange={(e) => handleChange("age", e.target.value)}
                placeholder="约二十五岁"
              />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">外貌描写</label>
            <Textarea
              value={form.appearance}
              onChange={(e) => handleChange("appearance", e.target.value)}
              placeholder="描述角色的外貌特征..."
              rows={2}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">性格特征</label>
            <Textarea
              value={form.personality}
              onChange={(e) => handleChange("personality", e.target.value)}
              placeholder="描述角色的性格..."
              rows={2}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">背景/来历</label>
            <Textarea
              value={form.background}
              onChange={(e) => handleChange("background", e.target.value)}
              placeholder="描述角色的背景故事..."
              rows={2}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">能力/技能</label>
            <Textarea
              value={form.skills}
              onChange={(e) => handleChange("skills", e.target.value)}
              placeholder="描述角色的能力..."
              rows={2}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">当前状态</label>
              <select
                value={form.current_status}
                onChange={(e) => handleChange("current_status", e.target.value)}
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
              >
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-slate-600">首次出场阶段（中纲阶段ID）</label>
              <Input
                type="text"
                value={form.first_appearance_stage}
                onChange={(e) => handleChange("first_appearance_stage", e.target.value)}
                placeholder="M1"
              />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">当前目的/动机</label>
            <Textarea
              value={form.current_goal}
              onChange={(e) => handleChange("current_goal", e.target.value)}
              placeholder="角色当前的目标或动机..."
              rows={2}
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-slate-600">补充备注</label>
            <Textarea
              value={form.notes}
              onChange={(e) => handleChange("notes", e.target.value)}
              placeholder="其他需要记录的信息..."
              rows={2}
            />
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <Button variant="outline" onClick={onCancel}>取消</Button>
          <Button onClick={handleSubmit} disabled={!form.name.trim()}>保存</Button>
        </div>
      </div>
    </div>
  );
}

export function CharacterListPage() {
  const { workId } = useParams();
  const [characters, setCharacters] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("全部");
  const [editing, setEditing] = useState(null);
  const [showForm, setShowForm] = useState(false);

  const fetchCharacters = async () => {
    try {
      const res = await characterApi.list(workId);
      const data = await res.json();
      setCharacters(data);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    (async () => {
      await fetchCharacters();
      setLoading(false);
    })();
  }, [workId]);

  const handleSave = async (data) => {
    const isEdit = editing && editing.id;

    try {
      const res = isEdit
        ? await characterApi.update(workId, editing.id, data)
        : await characterApi.create(workId, data);
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
      await characterApi.delete(workId, id);
      await fetchCharacters();
    } catch (e) {
      console.error(e);
    }
  };

  const filtered = filter === "全部"
    ? characters
    : characters.filter((c) => c.role_type === filter);

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </main>
    );
  }

  return (
    <main className="flex min-h-screen flex-col bg-slate-50">
      {/* Header */}
      <header className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-6 py-3">
        <div className="flex items-center gap-3">
          <Button asChild variant="ghost" size="sm" className="h-7 px-2">
            <Link to={`/works/${workId}`}>
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </Button>
          <div className="h-4 w-px bg-slate-200" />
          <h1 className="text-sm font-semibold text-slate-800">角色管理</h1>
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-500">
            {characters.length} 个角色
          </span>
        </div>
        <Button size="sm" onClick={() => { setEditing(null); setShowForm(true); }}>
          <Plus className="mr-1 h-4 w-4" /> 新建角色
        </Button>
      </header>

      {/* Filters */}
      <div className="flex gap-2 border-b border-slate-200 bg-white px-6 py-2">
        {["全部", ...ROLE_TYPES].map((r) => (
          <button
            key={r}
            onClick={() => setFilter(r)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              filter === r
                ? "bg-blue-100 text-blue-700"
                : "text-slate-500 hover:bg-slate-100"
            }`}
          >
            {r}
          </button>
        ))}
      </div>

      {/* Character grid */}
      <div className="flex-1 overflow-y-auto p-6">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-slate-400">
            <UserCircle className="h-12 w-12 mb-3" />
            <p className="text-sm">暂无角色</p>
            <p className="text-xs text-slate-300 mt-1">点击右上角"新建角色"开始创建</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4">
            {filtered.map((char) => (
              <CharacterCard
                key={char.id}
                char={char}
                onEdit={(c) => { setEditing(c); setShowForm(true); }}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </div>

      {/* Form modal */}
      {showForm && (
        <CharacterForm
          character={editing}
          onSave={handleSave}
          onCancel={() => { setShowForm(false); setEditing(null); }}
        />
      )}
    </main>
  );
}
